"""Builder de payload HKA para Comprobantes de Retención de IVA (Tipo 05).

Construye el JSON requerido por la API TFHKA para registrar comprobantes
de retención de IVA sobre compras. Hereda de BaseRetentionPayloadBuilder
para reutilizar la lógica compartida con ISLR.
"""
from frappe.utils import flt, getdate

from l10n_ve.digital_invoice.base_withholding_builder import BaseRetentionPayloadBuilder


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
        """Nodo de totales consolidados de la retención IVA.

        Todos los montos se envían en valor absoluto: TFHKA rechaza (203/0102)
        montos con signo negativo.
        EsNegativo: true solo si el neto consolidado es negativo (NCs dominan el comprobante).
        """
        emission_date: str = self._get_emission_date()
        is_negative: bool = self._is_net_negative()

        total_retenido: float = self._calculate_total_retenido()

        return {
            "TotalBaseImponible": "{:.2f}".format(abs(flt(self.doc.totals_total))),
            "NumeroCompRetencion": self._clean_voucher_number(),
            "FechaEmisionCR": emission_date,
            "TotalIVA": "{:.2f}".format(abs(flt(self.doc.totals_taxes_and_charges_added))),
            "TotalRetenido": "{:.2f}".format(abs(total_retenido)),
            "TotalISRL": "",
            "TotalIGTF": "",
            "TipoComprobante": None,
            "EsNegativo": is_negative,
        }

    def _calculate_total_retenido(self) -> float:
        """Calcula el total retenido sumando cada línea con su signo según tipo de documento.

        Garantiza consistencia matemática exacta con los montos 'Retenido' del detalle.
        """
        return sum(
            (abs(flt(item.taxes_and_charges_added)) * flt(item.withholding_rate) / 100)
            * (-1 if self._get_document_type_code_base(item) in ("02", "03") else 1)
            for item in self.doc.get(self.CHILD_TABLE_FIELD, [])
        )

    def _is_net_negative(self) -> bool:
        """Determina si el comprobante tiene resultado neto consolidado negativo."""
        return self._calculate_total_retenido() < 0 or flt(self.doc.totals_tax_amount_vat) < 0

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
        """Construye un detalle individual de retención IVA.

        Montos siempre en positivo (abs): TFHKA rechaza valores negativos en
        las líneas del comprobante. La diferenciación NC/Factura se indica con
        TipoDocumento='02' (mismo patrón que el ISLR builder).
        """
        posting_date: str = getdate(item.posting_date).strftime("%d/%m/%Y")
        doc_type_code: str = self._get_document_type_code_base(item)

        iva_percentage: str = "{:.2f}".format(flt(item.rate) / 100)
        withholding_percentage: str = "{:.2f}".format(flt(item.withholding_rate) / 100)

        monto_total: float = abs(flt(item.total)) + abs(flt(item.total_exempt)) + abs(flt(item.taxes_and_charges_added))
        retenido: float = abs(flt(item.taxes_and_charges_added)) * flt(item.withholding_rate) / 100

        bill_no: str = (item.bill_no or "").strip()
        serie_doc, num_doc = self._extract_series_and_number(bill_no)
        affected_invoice: str = (item.get("affected_invoice_number") or "").strip()

        return {
            "NumeroLinea": str(line_number),
            "FechaDocumento": posting_date,
            "TipoDocumento": doc_type_code,
            "SerieDocumento": serie_doc,
            "NumeroDocumento": num_doc,
            "NumeroControl": item.bill_control or "",
            "TipoTransaccion": None,
            "NumeroDocumentoAfectado": affected_invoice if doc_type_code in ("02", "03") else "",
            "MontoTotal": "{:.2f}".format(monto_total),
            "MontoExento": "{:.2f}".format(abs(flt(item.total_exempt))),
            "BaseImponible": "{:.2f}".format(abs(flt(item.total))),
            "Porcentaje": iva_percentage,
            "PorcentajeRetencion": withholding_percentage,
            "Sustraendo": None,
            "MontoIVA": "{:.2f}".format(abs(flt(item.taxes_and_charges_added))),
            "Retenido": "{:.2f}".format(retenido),
            "Percibido": "0",
            "CodigoConcepto": None,
            "Moneda": self.company_currency,
            "InfoAdicionalItem": [],
        }
