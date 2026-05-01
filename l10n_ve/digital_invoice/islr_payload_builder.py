"""Builder de payload HKA para Comprobantes de Retención de ISLR (Tipo 06).

Construye el JSON requerido por la API TFHKA para registrar comprobantes
de retención de ISLR sobre compras. Hereda de BaseRetentionPayloadBuilder
para reutilizar la lógica compartida con IVA.
"""
from frappe.utils import flt, getdate

from l10n_ve.digital_invoice.base_withholding_builder import BaseRetentionPayloadBuilder


class TFHKAISLRPayloadBuilder(BaseRetentionPayloadBuilder):
    """Construye el payload JSON para emisión de retención ISLR (tipo 06)."""

    TIPO_DOCUMENTO: str = "06"
    TRANSACTION_PREFIX: str = "RISLR"
    CHILD_TABLE_FIELD: str = "islr_withholding_voucher_item"

    # ─────────────────────────────────────────────────────────────
    # Implementación de métodos abstractos
    # ─────────────────────────────────────────────────────────────

    def _get_emission_date(self) -> str:
        return getdate(self.doc.posting_date).strftime("%d/%m/%Y")

    def _get_grand_total(self) -> float:
        return flt(self.doc.totals_grand_total)

    # ─────────────────────────────────────────────────────────────
    # TotalesRetencion (ISLR)
    # ─────────────────────────────────────────────────────────────

    def _build_retention_totals(self) -> dict:
        """Nodo de totales consolidados de la retención ISLR."""
        emission_date: str = self._get_emission_date()

        return {
            "TotalBaseImponible": "{:.2f}".format(flt(self.doc.totals_islr_base_amount)),
            "NumeroCompRetencion": self._clean_voucher_number(),
            "FechaEmisionCR": emission_date,
            "TotalIVA": None,
            "TotalRetenido": None,
            "TotalISRL": "{:.2f}".format(flt(self.doc.totals_islr_amount)),
            "TotalIGTF": None,
            "TipoComprobante": "1",
        }

    # ─────────────────────────────────────────────────────────────
    # DetallesRetencion (ISLR)
    # ─────────────────────────────────────────────────────────────

    def _build_retention_details(self, items: list) -> list[dict]:
        """Construye el array de detalles de retención ISLR."""
        details: list[dict] = []
        for idx, item in enumerate(items, start=1):
            details.append(self._build_islr_detail_item(item, idx))
        return details

    def _build_islr_detail_item(self, item, line_number: int) -> dict:
        """Construye un detalle individual de retención ISLR."""
        posting_date: str = getdate(item.posting_date).strftime("%d/%m/%Y")

        # Porcentaje ISLR: rate viene como 5 → HKA espera 0.05
        islr_percentage: str = "{:.2f}".format(flt(item.rate) / 100)

        return {
            "NumeroLinea": str(line_number),
            "FechaDocumento": posting_date,
            "TipoDocumento": "01",
            "SerieDocumento": None,
            "NumeroDocumento": item.doc_no or "",
            "NumeroControl": item.bill_control or "",
            "TipoTransaccion": None,
            "MontoTotal": None,
            "MontoExento": None,
            "BaseImponible": "{:.2f}".format(flt(item.islr_base_amount)),
            "Porcentaje": islr_percentage,
            "PorcentajeRetencion": islr_percentage,
            "Sustraendo": "{:.2f}".format(flt(item.subtracting)),
            "MontoIVA": None,
            "Retenido": "{:.2f}".format(flt(item.islr_amount)),
            "Percibido": None,
            "CodigoConcepto": item.code or "",
            "Moneda": self.company_currency,
            "InfoAdicionalItem": None,
        }
