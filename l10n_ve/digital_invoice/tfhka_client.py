import json
from typing import Optional

import frappe
import requests
from frappe import _


# ─────────────────────────────────────────────────────────────────────────────
# Estructura esperada en site_config.json:
#
#   "digital_billing_settings": {
#       "is_production_mode": 0,
#       "demo_url":           "https://demo.imprentadigital.com",
#       "production_url":     "https://imprentadigital.com",
#       "username":           "usuario_api",
#       "password":           "clave_api"
#   }
# ─────────────────────────────────────────────────────────────────────────────


class TFHKAClient:
    def __init__(self) -> None:
        self.base_url: str = ""
        self.username: str = ""
        self.password: str = ""
        self.token: Optional[str] = None

    def _load_settings(self) -> None:
        """
        Carga credenciales desde site_config.json (digital_billing_settings).
        El DocType TFHKA Settings sólo se usa para configuración no sensible
        (enabled flag, series de sucursal, etc.).
        """
        site_cfg: dict = frappe.get_site_config().get("digital_billing_settings") or {}

        if not site_cfg:
            frappe.throw(
                _("Faltan las credenciales de Facturación Digital. "
                  "Configure 'digital_billing_settings' en site_config.json.")
            )

        doctype_cfg = frappe.get_cached_doc("TFHKA Settings")
        if not doctype_cfg.enabled:
            frappe.throw(_("La integración de Facturación Digital TFHKA está deshabilitada."))

        is_production: bool = bool(site_cfg.get("is_production_mode", 0))
        url_key = "production_url" if is_production else "demo_url"
        self.base_url = (site_cfg.get(url_key) or "").rstrip("/")

        self.username = site_cfg.get("username") or ""
        self.password = site_cfg.get("password") or ""

        missing = [
            k for k in ("username", "password")
            if not site_cfg.get(k)
        ] + ([url_key] if not self.base_url else [])

        if missing:
            frappe.throw(
                _("Faltan campos en 'digital_billing_settings' de site_config.json: {0}").format(
                    ", ".join(missing)
                )
            )

    def authenticate(self, force: bool = False) -> str:
        """Obtiene el token JWT. LoginResponse.codigo es int (200 = éxito)."""
        self._load_settings()
        if not force:
            cached_token = frappe.cache().get_value("tfhka_jwt_token")
            if cached_token:
                self.token = cached_token
                return self.token
        url = f"{self.base_url}/api/Autenticacion"
        payload = {"usuario": self.username, "clave": self.password}

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("codigo") != 200:
                self._log_error("Autenticacion", payload, response.text)
                frappe.throw(
                    _("Error de autenticación TFHKA: {0}").format(data.get("mensaje"))
                )

            self.token = data.get("token")
            frappe.cache().set_value("tfhka_jwt_token", self.token, expires_in_sec=3600)
            return self.token

        except requests.exceptions.HTTPError as err:
            raw = err.response.text if err.response else str(err)
            self._log_error("Autenticacion", payload, raw)
            frappe.throw(_("Error HTTP en Autenticación TFHKA: {0}").format(str(err)))
        except frappe.ValidationError:
            raise
        except Exception as e:
            self._log_error("Autenticacion", payload, str(e))
            frappe.throw(_("Error de Conexión TFHKA: {0}").format(str(e)))

    def emitir_documento(self, payload: dict) -> dict:
        """
        Envía a /api/Emision. SendResponseDTO:
          { codigo, mensaje, validaciones, resultado: { numeroControl, transaccionId, ... } }
        """
        if not self.token:
            self.authenticate()

        url = f"{self.base_url}/api/Emision"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

        try:
            payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response = requests.post(url, data=payload_bytes, headers=headers, timeout=60)

            try:
                data = response.json()
            except Exception:
                data = {"error": True, "message": response.text, "codigo": str(response.status_code)}

            if not response.ok:
                data["error"] = True
                data.setdefault("message", response.text)
                frappe.logger("l10n_ve").error(
                    f"TFHKA Emision HTTP {response.status_code}: {response.text[:2000]}"
                )

            return data

        except requests.exceptions.HTTPError as err:
            raw = err.response.text if err.response else str(err)
            try:
                return json.loads(raw)
            except Exception:
                return {"error": True, "message": raw}
        except Exception as e:
            return {"error": True, "message": str(e)}

    def void_document(self, payload: dict) -> dict:
        """
        Envía a /api/Anular. Payload esperado:
          { serie, tipoDocumento, numeroDocumento, motivoAnulacion, fechaAnulacion, horaAnulacion }
        Respuesta exitosa: { codigo: 200, mensaje: "..." }
        """
        if not self.token:
            self.authenticate()

        url = f"{self.base_url}/api/Anular"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            try:
                data = response.json()
            except Exception:
                data = {
                    "error": True,
                    "message": response.text,
                    "codigo": str(response.status_code),
                }

            # Log EVERY response (success and error) for traceability
            frappe.logger("l10n_ve").info(
                f"TFHKA Anular | HTTP {response.status_code} | payload={payload} | response={data}"
            )

            if response.ok:
                data["_http_ok"] = True
                # Save a clean copy (without the internal flag) to the DB log
                log_data = {k: v for k, v in data.items() if k != "_http_ok"}
                self._log_response("Anular", payload, log_data, status="Success")
            else:
                data["error"] = True
                data.setdefault("message", response.text)
                self._log_response("Anular", payload, data, status="Error")

            return data

        except requests.exceptions.HTTPError as err:
            raw = err.response.text if err.response else str(err)
            self._log_error("Anular", payload, raw)
            try:
                return json.loads(raw)
            except Exception:
                return {"error": True, "message": raw}
        except Exception as e:
            self._log_error("Anular", payload, str(e))
            return {"error": True, "message": str(e)}

    def void_fiscal_document(
        self,
        doc,
        reason: str,
        void_date: str,
        void_time: str,
        tipo_documento: str,
    ) -> dict:
        """
        Lógica centralizada para anular un documento fiscal en TFHKA.

        Extrae la serie desde `remarks`, convierte la hora al formato 12h,
        construye el payload, llama a /api/Anular y valida la respuesta.

        Args:
            doc:             Documento Frappe (Sales Invoice o VE Sales Credit Note).
            reason:          Motivo de anulación (texto libre).
            void_date:       Fecha en formato DD/MM/YYYY.
            void_time:       Hora en HH:MM:SS (24h); se convierte a 12h internamente.
            tipo_documento:  Catálogo 1 SENIAT: "01" Factura, "02" NC, "03" ND.

        Returns:
            dict con status y message si fue exitoso.

        Raises:
            frappe.ValidationError si el documento no tiene bill_no, serie,
            o si HKA rechaza la anulación.
        """
        from datetime import datetime

        if not doc.bill_no:
            frappe.throw(
                _(
                    "El documento no tiene número de documento HKA. "
                    "Solo se pueden anular documentos enviados a la imprenta digital."
                )
            )

        # Convertir hora 24h (HH:MM:SS) a 12h (hh:mm:ss am/pm) para TFHKA
        try:
            time_obj = datetime.strptime(void_time, "%H:%M:%S")
            formatted_time: str = time_obj.strftime("%I:%M:%S %p").lower()
        except ValueError:
            formatted_time = void_time

        # Extraer la serie desde la respuesta HKA original almacenada en remarks
        serie: str = ""
        if doc.remarks:
            try:
                hka_response: dict = json.loads(doc.remarks)
                serie = (hka_response.get("resultado") or {}).get("serie") or ""
            except Exception:
                pass

        if not serie:
            frappe.throw(
                _(
                    "El documento no tiene serie HKA. "
                    "Solo se pueden anular documentos enviados a la imprenta digital."
                )
            )

        payload: dict = {
            "serie": serie,
            "tipoDocumento": tipo_documento,
            "numeroDocumento": doc.bill_no,
            "motivoAnulacion": reason,
            "fechaAnulacion": void_date,
            "horaAnulacion": formatted_time,
        }

        self.authenticate()
        result: dict = self.void_document(payload)

        if result.get("error") or not result.get("_http_ok"):
            error_message: str = (
                result.get("mensaje") or result.get("message") or "Error desconocido"
            )
            frappe.throw(
                _(
                    "HKA rechazó la anulación. Código: {0} | Respuesta: {1}"
                ).format(result.get("codigo", "—"), error_message),
                title=_("Error al Anular en HKA"),
            )

        return {
            "status": "success",
            "result": result,
        }

    def download_file(
        self,
        numero_documento: str,
        tipo_documento: str = "01",
        tipo_archivo: str = "pdf",
        serie: str = "",
    ) -> dict:
        """
        Descarga archivo desde /api/DescargaArchivo.
        Retorna { codigo, mensaje, archivo } donde 'archivo' es base64.
        tipo_documento: 01=Factura, 02=NotaCredito, 03=NotaDebito (Catálogo 1 SENIAT)
        tipo_archivo: pdf, xml, json
        """
        if not self.token:
            self.authenticate()

        url = f"{self.base_url}/api/DescargaArchivo"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        payload = {
            "tipoDocumento": tipo_documento,
            "numeroDocumento": numero_documento,
            "tipoArchivo": tipo_archivo,
        }
        if serie:
            payload["serie"] = serie

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)

            if response.status_code == 401:
                # Token expirado/inválido. Limpiar caché, forzar re-autenticación y reintentar.
                frappe.cache().delete_value("tfhka_jwt_token")
                self.token = None
                self.authenticate(force=True)
                headers["Authorization"] = f"Bearer {self.token}"
                response = requests.post(url, json=payload, headers=headers, timeout=15)

            try:
                data = response.json()
            except Exception:
                data = {
                    "error": True,
                    "message": response.text,
                    "codigo": str(response.status_code),
                }

            if not response.ok:
                data["error"] = True
                data.setdefault("message", response.text)
                self._log_error("DescargaArchivo", payload, response.text)

            return data

        except Exception as e:
            self._log_error("DescargaArchivo", payload, str(e))
            return {"error": True, "message": str(e)}

    def _log_error(self, endpoint: str, payload: dict, response_text: str) -> None:
        self._log_response(endpoint, payload, response_text, status="Error")

    def _log_response(
        self,
        endpoint: str,
        payload: dict,
        response_data,
        status: str = "Error",
    ) -> None:
        try:
            sanitized = {
                k: "***" if k in ("usuario", "clave") else v
                for k, v in (payload.items() if isinstance(payload, dict) else {})
            }
            response_text = (
                json.dumps(response_data, ensure_ascii=False)
                if isinstance(response_data, dict)
                else str(response_data)
            )
            doc = frappe.new_doc("VE Digital Invoice Log")
            doc.endpoint = endpoint
            doc.payload_sent = json.dumps(sanitized, indent=2, ensure_ascii=False)
            doc.response_received = response_text
            doc.status = status
            doc.insert(ignore_permissions=True)
        except Exception as e:
            frappe.logger("l10n_ve").error(f"No se pudo guardar el log TFHKA: {str(e)}")


ALLOWED_DOCTYPES: list[str] = [
    "Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note",
    "VAT Withholding Voucher", "ISLR Withholding Voucher",
]


@frappe.whitelist()
def get_fiscal_invoice_pdf(invoice_name: str, doctype: str = "Sales Invoice") -> dict:
    """
    Descarga el PDF de la factura fiscal desde TFHKA
    y retorna el base64 para renderizar en el frontend.
    Soporta Sales Invoice, VE Sales Credit Note, VE Sales Debit Note
    y VAT Withholding Voucher.
    """
    if doctype not in ALLOWED_DOCTYPES:
        return {"base64": None, "error": f"DocType '{doctype}' no soportado."}

    doc = frappe.get_cached_doc(doctype, invoice_name)
    frappe.has_permission(doctype, "read", doc=doc, throw=True)

    # VAT/ISLR Withholding Voucher guarda la respuesta HKA en hka_response
    if doctype in ("VAT Withholding Voucher", "ISLR Withholding Voucher"):
        raw_hka = doc.hka_response or ""
    else:
        raw_hka = doc.remarks or ""

    if not raw_hka or '"numeroDocumento"' not in raw_hka:
        return {"base64": None, "error": "Este documento no tiene datos de facturación digital."}

    try:
        hka_data = json.loads(raw_hka)
    except (json.JSONDecodeError, TypeError):
        return {"base64": None, "error": "Los datos HKA no son válidos."}

    resultado = (hka_data.get("resultado") or {})
    numero_documento = resultado.get("numeroDocumento")
    serie = resultado.get("serie") or ""
    if not numero_documento:
        return {"base64": None, "error": "No se encontró el número de documento en los datos HKA."}

    # Catálogo SENIAT: 01=Factura, 02=NC, 03=ND, 05=Retención IVA, 06=Retención ISLR
    document_map = {
        "Sales Invoice": "01",
        "VE Sales Credit Note": "02",
        "VE Sales Debit Note": "03",
        "VAT Withholding Voucher": "05",
        "ISLR Withholding Voucher": "06",
    }

    tipo_documento = document_map.get(doctype)
    if not tipo_documento:
        frappe.throw(f"DocType '{doctype}' no soportado.")

    import base64

    # 1. Buscar si ya existe el PDF adjunto al documento en el Doctype File
    attached_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": doctype,
            "attached_to_name": invoice_name,
            "file_name": ["like", "%.pdf"]
        },
        fields=["name", "file_name"]
    )

    if attached_files:
        try:
            file_doc = frappe.get_doc("File", attached_files[0].get("name"))
            file_content = file_doc.get_content()
            if isinstance(file_content, str):
                file_content = file_content.encode("utf-8")
            archivo_base64 = base64.b64encode(file_content).decode("utf-8")
            return {
                "base64": archivo_base64,
                "numero_documento": numero_documento,
                "numero_control": resultado.get("numeroControl", ""),
            }
        except Exception as e:
            frappe.logger("l10n_ve").error(
                f"Error al leer PDF adjunto local para {invoice_name}: {str(e)}"
            )

    # 2. Si no existe, lo descargamos de HKA
    client = TFHKAClient()
    response = client.download_file(
        numero_documento=str(numero_documento),
        tipo_documento=tipo_documento,
        tipo_archivo="pdf",
        serie=serie,
    )

    archivo_base64 = response.get("archivo")
    if not archivo_base64:
        frappe.logger("l10n_ve").warning(
            f"DescargaArchivo sin PDF: {response.get('mensaje', 'Sin mensaje')} "
            f"(doc={numero_documento}, serie={serie})"
        )
        return {
            "base64": None,
            "error": response.get("mensaje", "TFHKA no retornó el archivo PDF."),
        }

    # 3. Guardar y adjuntar el archivo descargado para futuras consultas rápidas
    try:
        from frappe.utils.file_manager import save_file
        pdf_bytes = base64.b64decode(archivo_base64)
        filename = f"Factura_{invoice_name}_{numero_documento}.pdf"
        
        save_file(
            fname=filename,
            content=pdf_bytes,
            dt=doctype,
            dn=invoice_name,
            is_private=1  # Guardado como privado por confidencialidad
        )
    except Exception as e:
        frappe.logger("l10n_ve").error(
            f"No se pudo adjuntar el PDF descargado a {invoice_name}: {str(e)}"
        )

    return {
        "base64": archivo_base64,
        "numero_documento": numero_documento,
        "numero_control": resultado.get("numeroControl", ""),
    }
