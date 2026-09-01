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

    # Mapeo doc_type → TipoDocumento HKA (Catálogo 1)
    _DOC_TYPE_MAP: dict[str, str] = {
        "FACT": "01",
        "N/CR": "02",
        "N/DB": "03",
    }

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
        """Nodo de totales consolidados de la retención ISLR.

        Según ejemplo oficial HKA ('COMPROBANTE DE ISLR EN NEGATIVO.json'):
        - TotalBaseImponible y TotalISRL van en abs()
        - EsNegativo: true si el neto es negativo (NC > facturas)
        - TipoComprobante: "2" si es negativo, "1" si es positivo
        """
        emission_date: str = self._get_emission_date()
        is_negative: bool = self._is_net_negative()

        return {
            "TotalBaseImponible": "{:.2f}".format(abs(flt(self.doc.totals_islr_base_amount))),
            "NumeroCompRetencion": self._clean_voucher_number(),
            "FechaEmisionCR": emission_date,
            "TotalIVA": None,
            "TotalRetenido": None,
            "TotalISRL": "{:.2f}".format(abs(flt(self.doc.totals_islr_amount))),
            "TotalIGTF": "",
            "TipoComprobante": "2" if is_negative else "1",
            "EsNegativo": is_negative,
        }

    def _is_net_negative(self) -> bool:
        """Determina si el comprobante tiene resultado neto negativo.

        Ocurre cuando las NCs superan el monto de las facturas.
        """
        return flt(self.doc.totals_islr_base_amount) < 0

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
        """Construye un detalle individual de retención ISLR.

        Según patrón oficial HKA: montos siempre en positivo (abs).
        La diferenciación NC/Factura se hace con TipoDocumento.
        """
        posting_date: str = getdate(item.posting_date).strftime("%d/%m/%Y")

        # Porcentaje ISLR: rate viene como 5 → HKA espera 0.05
        islr_percentage: str = "{:.2f}".format(flt(item.rate) / 100)

        tipo_documento: str = self._DOC_TYPE_MAP.get(item.doc_type or "", "01")

        doc_no: str = (item.doc_no or "").strip()
        serie_doc, num_doc = self._extract_series_and_number(doc_no)
        affected_invoice: str = (item.get("affected_invoice_number") or "").strip()

        return {
            "NumeroLinea": str(line_number),
            "FechaDocumento": posting_date,
            "TipoDocumento": tipo_documento,
            "SerieDocumento": serie_doc,
            "NumeroDocumento": num_doc,
            "NumeroControl": item.bill_control or "",
            "TipoTransaccion": "",
            "NumeroDocumentoAfectado": affected_invoice if tipo_documento in ("02", "03") else "",
            "MontoTotal": "{:.2f}".format(abs(flt(item.grand_total))),
            "MontoExento": "",
            "BaseImponible": "{:.2f}".format(abs(flt(item.islr_base_amount))),
            "Porcentaje": islr_percentage,
            "PorcentajeRetencion": islr_percentage,
            "Sustraendo": "{:.2f}".format(abs(flt(item.subtracting))),
            "MontoIVA": "",
            "Retenido": "{:.2f}".format(abs(flt(item.islr_amount))),
            "Percibido": "0",
            "CodigoConcepto": item.code or "",
            "Moneda": self.company_currency,
            "InfoAdicionalItem": [],
        }
