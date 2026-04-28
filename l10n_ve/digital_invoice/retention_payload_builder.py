"""Builder de payload HKA para Comprobantes de Retención de IVA (Tipo 05).

Construye el JSON requerido por la API TFHKA para registrar comprobantes
de retención de IVA sobre compras. La estructura difiere de facturas:
usa SujetoRetenido en vez de Comprador, y DetallesRetencion en vez de
DetallesItems.
"""
import re
import unicodedata
from typing import Optional

import frappe
from frappe.utils import flt, getdate

from l10n_ve.digital_invoice.payload_builder import clean_address, clean_payload


class TFHKARetentionPayloadBuilder:
    """Construye el payload JSON para emisión de retención IVA (tipo 05)."""

    def __init__(self, doc) -> None:
        """Inicializa el builder con el documento de retención.

        Args:
            doc: Documento VAT Withholding Voucher ya cargado.
        """
        self.doc = doc
        self.company_currency: str = "BSD"

    # ─────────────────────────────────────────────────────────────
    # Punto de entrada principal
    # ─────────────────────────────────────────────────────────────

    def build_payload(self) -> dict:
        """Construye el payload completo para la API de emisión TFHKA."""
        items: list[dict] = self.doc.get("vat_withholding_voucher_item", [])

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
    # Encabezado → IdentificacionDocumento
    # ─────────────────────────────────────────────────────────────

    def _build_identification(self) -> dict:
        """Nodo de identificación del documento de retención."""
        issue_date: str = getdate(self.doc.issue_date).strftime("%d/%m/%Y")
        clean_number: str = self._clean_voucher_number()

        return {
            "TipoDocumento": "05",
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
            "FechaEmision": issue_date,
            "FechaVencimiento": issue_date,
            "HoraEmision": self._format_current_time(),
            "Anulado": False,
            "TipoDePago": "Contado",
            "Serie": "",
            "Sucursal": None,
            "TipoDeVenta": "Interna",
            "Moneda": self.company_currency,
            "TransaccionId": f"RIVA{clean_number}",
        }

    @staticmethod
    def _format_current_time() -> str:
        """Formatea la hora actual al formato HH:MM:SS am/pm."""
        from frappe.utils import now_datetime
        return now_datetime().strftime("%I:%M:%S %p").lower()

    # ─────────────────────────────────────────────────────────────
    # Encabezado → SujetoRetenido
    # ─────────────────────────────────────────────────────────────

    def _build_retained_subject(self) -> dict:
        """Nodo del sujeto retenido (proveedor al que se le retiene IVA)."""
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
        """Obtiene teléfono y correo del proveedor desde Address/Contact.

        Args:
            supplier_name: Nombre del proveedor en ERPNext.

        Returns:
            Tupla (teléfono, correo). Cadena vacía si no existe.
        """
        phone: str = ""
        email: str = ""

        # Buscar dirección principal del proveedor
        address_name: Optional[str] = frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": "Supplier", "link_name": supplier_name, "parenttype": "Address"},
            "parent",
        )
        if address_name:
            addr = frappe.get_cached_doc("Address", address_name)
            phone = (addr.phone or addr.get("fax") or "").strip()

        # Buscar contacto principal del proveedor
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
    # Encabezado → Totales (placeholder para tipo 05)
    # ─────────────────────────────────────────────────────────────

    def _build_totals_placeholder(self, item_count: int) -> dict:
        """Nodo Totales: en retenciones va con valores en cero, excepto NroItems."""
        grand_total: str = "{:.2f}".format(flt(self.doc.totals_grand_total))

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
    # Encabezado → TotalesRetencion
    # ─────────────────────────────────────────────────────────────

    def _build_retention_totals(self) -> dict:
        """Nodo de totales consolidados de la retención."""
        issue_date: str = getdate(self.doc.issue_date).strftime("%d/%m/%Y")
        has_negative: bool = self._has_negative_retention()

        # Calcular total retenido real: suma de (IVA × % retención) por cada línea
        total_retenido: float = sum(
            flt(item.taxes_and_charges_added) * flt(item.withholding_rate) / 100
            for item in self.doc.get("vat_withholding_voucher_item", [])
        )

        return {
            "TotalBaseImponible": "{:.2f}".format(flt(self.doc.totals_total)),
            "NumeroCompRetencion": self._clean_voucher_number(),
            "FechaEmisionCR": issue_date,
            "TotalIVA": "{:.2f}".format(flt(self.doc.totals_taxes_and_charges_added)),
            "TotalRetenido": "{:.2f}".format(total_retenido),
            "TotalISRL": "",
            "TotalIGTF": "",
            "TipoComprobante": None,
            "EsNegativo": has_negative,
        }

    def _has_negative_retention(self) -> bool:
        """Determina si el comprobante contiene retenciones sobre notas de crédito."""
        for item in self.doc.get("vat_withholding_voucher_item", []):
            if item.get("credit_note_no") or item.get("is_return"):
                return True
        return False

    # ─────────────────────────────────────────────────────────────
    # DetallesRetencion — Array de facturas retenidas
    # ─────────────────────────────────────────────────────────────

    def _build_retention_details(self, items: list) -> list[dict]:
        """Construye el array de detalles de retención (una entrada por factura)."""
        details: list[dict] = []
        for idx, item in enumerate(items, start=1):
            details.append(self._build_retention_detail_item(item, idx))
        return details

    def _build_retention_detail_item(self, item, line_number: int) -> dict:
        """Construye un detalle individual de retención para una factura."""
        posting_date: str = getdate(item.posting_date).strftime("%d/%m/%Y")
        doc_type_code: str = self._get_document_type_code(item)

        # Porcentaje IVA: rate viene como 16 → HKA espera 0.16
        iva_percentage: str = "{:.2f}".format(flt(item.rate) / 100)

        # Porcentaje retención: withholding_rate viene como 75 → HKA espera 0.75
        withholding_percentage: str = "{:.2f}".format(flt(item.withholding_rate) / 100)

        # MontoTotal para HKA = BaseImponible + MontoExento + MontoIVA
        # (total original de la factura ANTES de descontar la retención)
        monto_total: float = flt(item.total) + flt(item.total_exempt) + flt(item.taxes_and_charges_added)

        # Retenido = MontoIVA × PorcentajeRetencion
        retenido: float = flt(item.taxes_and_charges_added) * flt(item.withholding_rate) / 100

        return {
            "NumeroLinea": str(line_number),
            "FechaDocumento": posting_date,
            "TipoDocumento": doc_type_code,
            "SerieDocumento": None,
            "NumeroDocumento": item.bill_no or "",
            "NumeroControl": item.bill_control or "",
            "TipoTransaccion": None,
            "MontoTotal": "{:.2f}".format(monto_total),
            "MontoExento": "{:.2f}".format(flt(item.total_exempt)),
            "BaseImponible": "{:.2f}".format(flt(item.total)),
            "Porcentaje": iva_percentage,
            "PorcentajeRetencion": withholding_percentage,
            "Sustraendo": None,
            "MontoIVA": "{:.2f}".format(flt(item.taxes_and_charges_added)),
            "Retenido": "{:.2f}".format(retenido),
            "Percibido": "0",
            "CodigoConcepto": None,
            "Moneda": self.company_currency,
            "InfoAdicionalItem": [],
        }

    @staticmethod
    def _get_document_type_code(item) -> str:
        """Determina el código de tipo de documento para DetallesRetencion.

        - '01': Factura normal
        - '02': Nota de Crédito
        - '03': Nota de Débito
        """
        if item.get("credit_note_no") or item.get("is_return"):
            return "02"
        if item.get("debit_note_no") or item.get("is_debit_note"):
            return "03"
        return "01"

    # ─────────────────────────────────────────────────────────────
    # Utilidades compartidas
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_tax_id(tax_id: str) -> tuple[str, str]:
        """Extrae tipo y número del RIF/CI del proveedor.

        Soporta formatos: J-12345678-9, V12345678, G-20000001-0, etc.

        Returns:
            Tupla (tipo_identificacion, numero_identificacion).
        """
        cleaned: str = (tax_id or "").strip().upper()
        if not cleaned:
            return "V", "000000000"

        tipo: str = cleaned[0] if cleaned[0] in ("V", "E", "J", "G", "P", "C") else "V"
        resto: str = cleaned[1:]
        numero: str = re.sub(r"[^0-9]", "", resto)

        return tipo, numero or "000000000"

    def _clean_voucher_number(self) -> str:
        """Retorna el número de comprobante sin sufijo de enmienda de Frappe.

        Frappe agrega '-1', '-2', etc. al enmendar documentos.
        HKA requiere solo el número base numérico.
        Ej: '20260400000001-4' → '20260400000001'
        """
        raw: str = self.doc.voucher_number or ""
        return re.sub(r"-\d+$", "", raw)

    @staticmethod
    def _sanitize_legal_name(name: str) -> str:
        """Limpia la razón social para cumplir con el formato HKA.

        Remueve acentos, caracteres especiales y limita a 300 caracteres.
        """
        cleaned: str = " ".join((name or "").split())
        nfkd: str = unicodedata.normalize("NFKD", cleaned)
        cleaned = "".join(c for c in nfkd if not unicodedata.combining(c))
        cleaned = re.sub(r"[^A-Za-z0-9 .,\-]", "", cleaned)
        return cleaned[:300].strip()
