"""Base builder para payloads de retención HKA (IVA tipo 05, ISLR tipo 06).

Encapsula la lógica compartida entre los builders de retención IVA e ISLR:
- Identificación del documento
- Datos del sujeto retenido
- Totales placeholder
- Utilidades de parsing y sanitización
"""
import re
import unicodedata
from typing import Optional

import frappe
from frappe.utils import flt, getdate

from l10n_ve.digital_invoice.payload_builder import clean_address, clean_payload


class BaseRetentionPayloadBuilder:
    """Base para builders de payloads de retención HKA."""

    # Subclases DEBEN sobreescribir estas constantes
    TIPO_DOCUMENTO: str = ""
    TRANSACTION_PREFIX: str = ""
    CHILD_TABLE_FIELD: str = ""

    def __init__(self, doc) -> None:
        self.doc = doc
        self.company_currency: str = "BSD"
        self._serie: str = ""
        self._branch_code: str = ""
        self._load_series()

    def _load_series(self) -> None:
        """Carga la serie y branch_code resolviéndolas desde la sucursal del comprobante."""
        branch = getattr(self.doc, "branch", "") or ""
        company = getattr(self.doc, "empresa", "") or ""
        if not branch or not company:
            return
        try:
            from l10n_ve.digital_invoice.tfhka_integration import get_active_billing_series
            series_doc, branch_code = get_active_billing_series(company=company, branch=branch)
            self._serie = getattr(series_doc, "serie", "") or ""
            self._branch_code = branch_code or ""
        except Exception as e:
            # Registrar advertencia en logs de Frappe pero no abortar la ejecución del comprobante
            frappe.log_error(
                title=f"Error al obtener serie HKA para la sucursal {branch}",
                message=str(e)
            )

    # ─────────────────────────────────────────────────────────────
    # Punto de entrada (Template Method)
    # ─────────────────────────────────────────────────────────────

    def build_payload(self) -> dict:
        """Construye el payload completo para la API de emisión TFHKA."""
        items: list = self.doc.get(self.CHILD_TABLE_FIELD, [])

        payload: dict = {
            "documentoElectronico": {
                "Encabezado": {
                    "IdentificacionDocumento": self._build_identification(),
                    "Vendedor": None,
                    "Comprador": None,
                    "SujetoRetenido": self._build_retained_subject(),
                    "Tercero": None,
                    "Totales": self._build_totals_placeholder(len(items)),
                    "TotalesRetencion": self._build_retention_totals(),
                    "TotalesOtraMoneda": None,
                    "Orden": None,
                },
                "DetallesItems": None,
                "DetallesRetencion": self._build_retention_details(items),
                "Viajes": None,
                "InfoAdicional": [],
                "GuiaDespacho": None,
                "Transporte": None,
                "EsLote": False,
                "EsMinimo": False,
            }
        }
        return clean_payload(payload)

    # ─────────────────────────────────────────────────────────────
    # Métodos abstractos — subclases DEBEN implementar
    # ─────────────────────────────────────────────────────────────

    def _build_retention_totals(self) -> dict:
        raise NotImplementedError

    def _build_retention_details(self, items: list) -> list[dict]:
        raise NotImplementedError

    def _get_emission_date(self) -> str:
        """Retorna la fecha de emisión formateada DD/MM/YYYY."""
        raise NotImplementedError

    def _get_grand_total(self) -> float:
        """Retorna el grand total del comprobante."""
        raise NotImplementedError

    # ─────────────────────────────────────────────────────────────
    # Encabezado → IdentificacionDocumento (compartido)
    # ─────────────────────────────────────────────────────────────

    def _build_identification(self) -> dict:
        """Nodo de identificación del documento de retención."""
        emission_date: str = self._get_emission_date()
        clean_number: str = self._clean_voucher_number()

        return {
            "TipoDocumento": self.TIPO_DOCUMENTO,
            "NumeroDocumento": clean_number,
            "TipoProveedor": None,
            "TipoTransaccion": None,
            "NumeroPlanillaImportacion": None,
            "NumeroExpedienteImportacion": None,
            "SerieFacturaAfectada": None,
            "NumeroFacturaAfectada": None,
            "FechaFacturaAfectada": None,
            "MontoFacturaAfectada": None,
            "ComentarioFacturaAfectada": None,
            "RegimenEspTributacion": None,
            "FechaEmision": emission_date,
            "FechaVencimiento": emission_date,
            "HoraEmision": self._format_current_time(),
            "Anulado": False,
            "TipoDePago": "Contado",
            "Serie": self._serie,
            "Sucursal": self._branch_code or None,
            "TipoDeVenta": "Interna",
            "Moneda": self.company_currency,
            "TransaccionId": f"{self.TRANSACTION_PREFIX}{clean_number}",
        }

    # ─────────────────────────────────────────────────────────────
    # Encabezado → SujetoRetenido (100% compartido)
    # ─────────────────────────────────────────────────────────────

    def _build_retained_subject(self) -> dict:
        """Nodo del sujeto retenido (proveedor)."""
        supplier = frappe.get_cached_doc("Supplier", self.doc.supplier)

        tipo_id, num_id = self._parse_tax_id(supplier.tax_id)
        direccion: str = clean_address(self.doc.supplier_address or "")
        phone, email = self._get_supplier_contact_info(supplier.name)

        return {
            "TipoIdentificacion": tipo_id,
            "NumeroIdentificacion": num_id,
            "RazonSocial": self._sanitize_legal_name(supplier.supplier_name),
            "Direccion": direccion or "Sin dirección fiscal",
            "Ubigeo": None,
            "Pais": "VE",
            "Notificar": "Si" if email else None,
            "Telefono": [phone] if phone else [],
            "Correo": [email] if email else [],
            "OtrosEnvios": None,
        }

    def _get_supplier_contact_info(self, supplier_name: str) -> tuple[str, str]:
        """Obtiene teléfono y correo del proveedor."""
        phone: str = ""
        email: str = ""

        address_name: Optional[str] = frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": "Supplier", "link_name": supplier_name, "parenttype": "Address"},
            "parent",
        )
        if address_name:
            addr = frappe.get_cached_doc("Address", address_name)
            phone = (addr.phone or addr.get("fax") or "").strip()

        contact_name: Optional[str] = frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": "Supplier", "link_name": supplier_name, "parenttype": "Contact"},
            "parent",
        )
        if contact_name:
            contact = frappe.get_cached_doc("Contact", contact_name)
            email = (contact.email_id or "").strip()
            if not phone:
                phone = (contact.mobile_no or contact.phone or "").strip()

        return phone, email

    # ─────────────────────────────────────────────────────────────
    # Encabezado → Totales placeholder (95% compartido)
    # ─────────────────────────────────────────────────────────────

    def _build_totals_placeholder(self, item_count: int) -> dict:
        """Nodo Totales: en retenciones va con valores en cero, excepto NroItems."""
        grand_total: str = "{:.2f}".format(flt(self._get_grand_total()))

        return {
            "NroItems": str(item_count),
            "MontoGravadoTotal": "0",
            "MontoExentoTotal": "0",
            "Subtotal": "0.00",
            "TotalIVA": "0.00",
            "MontoTotalConIVA": grand_total,
            "TotalAPagar": "0.00",
            "TotalDescuentos": None,
            "TotalCargos": None,
            "RoundingAmount": None,
            "MontoEnLetras": "N/A",
            "Comision": None,
            "TipoCambio": None,
            "IGTF": None,
            "MontoGravadoIGTF": None,
        }

    # ─────────────────────────────────────────────────────────────
    # Utilidades compartidas
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _format_current_time() -> str:
        """Formatea la hora actual al formato HH:MM:SS am/pm."""
        from frappe.utils import now_datetime
        return now_datetime().strftime("%I:%M:%S %p").lower()

    @staticmethod
    def _parse_tax_id(tax_id: str) -> tuple[str, str]:
        """Extrae tipo y número del RIF/CI."""
        cleaned: str = (tax_id or "").strip().upper()
        if not cleaned:
            return "V", "000000000"

        tipo: str = cleaned[0] if cleaned[0] in ("V", "E", "J", "G", "P", "C") else "V"
        resto: str = cleaned[1:]
        numero: str = re.sub(r"[^0-9]", "", resto)

        return tipo, numero or "000000000"

    def _clean_voucher_number(self) -> str:
        """Retorna el número de comprobante sin sufijo de enmienda."""
        raw: str = self.doc.voucher_number or ""
        return re.sub(r"-\d+$", "", raw)

    @staticmethod
    def _sanitize_legal_name(name: str) -> str:
        """Limpia la razón social para cumplir con el formato HKA."""
        cleaned: str = " ".join((name or "").split())
        nfkd: str = unicodedata.normalize("NFKD", cleaned)
        cleaned = "".join(c for c in nfkd if not unicodedata.combining(c))
        cleaned = re.sub(r"[^A-Za-z0-9 .,\-]", "", cleaned)
        return cleaned[:300].strip()

    @staticmethod
    def _get_document_type_code_base(item) -> str:
        """Determina el código de tipo de documento base.

        - '01': Factura normal
        - '02': Nota de Crédito
        - '03': Nota de Débito
        """
        if item.get("credit_note_no") or item.get("is_return"):
            return "02"
        if item.get("debit_note_no") or item.get("is_debit_note"):
            return "03"
        return "01"
