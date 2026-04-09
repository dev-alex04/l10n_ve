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

    def authenticate(self) -> str:
        """Obtiene el token JWT. LoginResponse.codigo es int (200 = éxito)."""
        self._load_settings()
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

