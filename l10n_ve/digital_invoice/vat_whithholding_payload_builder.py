"""Builder de payload HKA para Comprobantes de Retención de IVA (Tipo 05).

Construye el JSON requerido por la API TFHKA para registrar comprobantes
de retención de IVA sobre compras. Hereda de BaseRetentionPayloadBuilder
para reutilizar la lógica compartida con ISLR.
"""
from frappe.utils import flt, getdate

from l10n_ve.digital_invoice.base_whithholding_builder import BaseRetentionPayloadBuilder


class TFHKARetentionPayloadBuilder(BaseRetentionPayloadBuilder):
    """Construye el payload JSON para emisión de retención IVA (tipo 05)."""

    TIPO_DOCUMENTO: str = "05"
    TRANSACTION_PREFIX: str = "RIVA"
    CHILD_TABLE_FIELD: str = "vat_withholding_voucher_item"

    # ─────────────────────────────────────────────────────────────
    # Implementación de métodos abstractos
    # ─────────────────────────────────────────────────────────────

    def _get_emission_date(self) -> str:
        return getdate(self.doc.issue_date).strftime("%d/%m/%Y")

    def _get_grand_total(self) -> float:
        return flt(self.doc.totals_grand_total)

    # ─────────────────────────────────────────────────────────────
    # TotalesRetencion (IVA)
    # ─────────────────────────────────────────────────────────────

    def _build_retention_totals(self) -> dict:
        """Nodo de totales consolidados de la retención IVA."""
        emission_date: str = self._get_emission_date()
        has_negative: bool = self._has_negative_retention()

        total_retenido: float = sum(
            flt(item.taxes_and_charges_added) * flt(item.withholding_rate) / 100
            for item in self.doc.get(self.CHILD_TABLE_FIELD, [])
        )

        return {
            "TotalBaseImponible": "{:.2f}".format(flt(self.doc.totals_total)),
            "NumeroCompRetencion": self._clean_voucher_number(),
            "FechaEmisionCR": emission_date,
            "TotalIVA": "{:.2f}".format(flt(self.doc.totals_taxes_and_charges_added)),
            "TotalRetenido": "{:.2f}".format(total_retenido),
            "TotalISRL": "",
            "TotalIGTF": "",
            "TipoComprobante": None,
            "EsNegativo": has_negative,
        }

    def _has_negative_retention(self) -> bool:
        """Determina si el comprobante contiene retenciones sobre notas de crédito."""
        for item in self.doc.get(self.CHILD_TABLE_FIELD, []):
            if item.get("credit_note_no") or item.get("is_return"):
                return True
        return False

    # ─────────────────────────────────────────────────────────────
    # DetallesRetencion (IVA)
    # ─────────────────────────────────────────────────────────────

    def _build_retention_details(self, items: list) -> list[dict]:
        """Construye el array de detalles de retención IVA."""
        details: list[dict] = []
        for idx, item in enumerate(items, start=1):
            details.append(self._build_vat_detail_item(item, idx))
        return details

    def _build_vat_detail_item(self, item, line_number: int) -> dict:
        """Construye un detalle individual de retención IVA."""
        posting_date: str = getdate(item.posting_date).strftime("%d/%m/%Y")
        doc_type_code: str = self._get_document_type_code_base(item)

        iva_percentage: str = "{:.2f}".format(flt(item.rate) / 100)
        withholding_percentage: str = "{:.2f}".format(flt(item.withholding_rate) / 100)

        monto_total: float = flt(item.total) + flt(item.total_exempt) + flt(item.taxes_and_charges_added)
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
