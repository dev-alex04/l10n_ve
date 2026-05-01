# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para BaseRetentionPayloadBuilder.

Valida los métodos utilitarios compartidos entre los builders
de retención IVA (tipo 05) e ISLR (tipo 06):
- Parsing de RIF/CI
- Sanitización de razón social
- Limpieza de número de comprobante
- Determinación de tipo de documento base
- Totales placeholder
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.digital_invoice.base_withholding_builder import BaseRetentionPayloadBuilder


class TestParseRIF(FrappeTestCase):
    """Tests para _parse_tax_id(): parsing de RIF venezolano."""

    def test_rif_with_dashes(self) -> None:
        """J-12345678-9 → tipo='J', num='123456789'."""
        tipo, num = BaseRetentionPayloadBuilder._parse_tax_id("J-12345678-9")

        self.assertEqual(tipo, "J")
        self.assertEqual(num, "123456789")

    def test_rif_without_dashes(self) -> None:
        """V12345678 → tipo='V', num='12345678'."""
        tipo, num = BaseRetentionPayloadBuilder._parse_tax_id("V12345678")

        self.assertEqual(tipo, "V")
        self.assertEqual(num, "12345678")

    def test_rif_empty(self) -> None:
        """RIF vacío → tipo='V', num='000000000'."""
        tipo, num = BaseRetentionPayloadBuilder._parse_tax_id("")

        self.assertEqual(tipo, "V")
        self.assertEqual(num, "000000000")

    def test_rif_gobierno(self) -> None:
        """G-20000001-0 → tipo='G', num='200000010'."""
        tipo, num = BaseRetentionPayloadBuilder._parse_tax_id("G-20000001-0")

        self.assertEqual(tipo, "G")
        self.assertEqual(num, "200000010")

    def test_rif_lowercase_normalized(self) -> None:
        """j-12345678-9 (lowercase) → tipo='J' (upper), num='123456789'."""
        tipo, num = BaseRetentionPayloadBuilder._parse_tax_id("j-12345678-9")

        self.assertEqual(tipo, "J")
        self.assertEqual(num, "123456789")

    def test_rif_extranjero(self) -> None:
        """E-80000001-5 → tipo='E', num='800000015'."""
        tipo, num = BaseRetentionPayloadBuilder._parse_tax_id("E-80000001-5")

        self.assertEqual(tipo, "E")
        self.assertEqual(num, "800000015")


class TestSanitizeLegalName(FrappeTestCase):
    """Tests para _sanitize_legal_name(): limpieza de razón social."""

    def test_normal_name(self) -> None:
        """Nombre sin caracteres especiales → se preserva."""
        result: str = BaseRetentionPayloadBuilder._sanitize_legal_name(
            "DESIGNET SERVICES 1815 C.A"
        )

        self.assertEqual(result, "DESIGNET SERVICES 1815 C.A")

    def test_accented_characters_removed(self) -> None:
        """Caracteres acentuados → se remueven los diacríticos."""
        result: str = BaseRetentionPayloadBuilder._sanitize_legal_name(
            "Compañía Solución Única S.A."
        )

        self.assertIn("Compania", result)
        self.assertNotIn("ñ", result)
        self.assertNotIn("ó", result)
        self.assertNotIn("ú", result)

    def test_extra_whitespace_collapsed(self) -> None:
        """Múltiples espacios → colapsados a uno solo."""
        result: str = BaseRetentionPayloadBuilder._sanitize_legal_name(
            "EMPRESA   DOBLE   ESPACIO   S.A."
        )

        self.assertEqual(result, "EMPRESA DOBLE ESPACIO S.A.")

    def test_empty_name(self) -> None:
        """Nombre vacío → retorna vacío."""
        result: str = BaseRetentionPayloadBuilder._sanitize_legal_name("")

        self.assertEqual(result, "")

    def test_truncates_at_300_chars(self) -> None:
        """Nombre > 300 caracteres → truncado."""
        long_name: str = "A" * 400
        result: str = BaseRetentionPayloadBuilder._sanitize_legal_name(long_name)

        self.assertEqual(len(result), 300)


class TestCleanVoucherNumber(FrappeTestCase):
    """Tests para _clean_voucher_number(): limpieza de sufijo de enmienda."""

    def _make_builder(self, voucher_number: str) -> BaseRetentionPayloadBuilder:
        """Crea builder con voucher_number específico."""
        doc = frappe._dict({"voucher_number": voucher_number})
        builder = BaseRetentionPayloadBuilder.__new__(BaseRetentionPayloadBuilder)
        builder.doc = doc
        return builder

    def test_number_without_suffix(self) -> None:
        """20260400000001 → sin cambio."""
        builder = self._make_builder("20260400000001")

        self.assertEqual(builder._clean_voucher_number(), "20260400000001")

    def test_number_with_amendment_suffix(self) -> None:
        """20260400000001-1 → remueve '-1'."""
        builder = self._make_builder("20260400000001-1")

        self.assertEqual(builder._clean_voucher_number(), "20260400000001")

    def test_number_with_multi_digit_suffix(self) -> None:
        """20260400000001-12 → remueve '-12'."""
        builder = self._make_builder("20260400000001-12")

        self.assertEqual(builder._clean_voucher_number(), "20260400000001")

    def test_empty_number(self) -> None:
        """Número vacío → retorna vacío."""
        builder = self._make_builder("")

        self.assertEqual(builder._clean_voucher_number(), "")


class TestDocumentTypeCode(FrappeTestCase):
    """Tests para _get_document_type_code_base(): clasificación de documentos."""

    def test_factura_normal(self) -> None:
        """Factura regular → '01'."""
        item = frappe._dict({})

        self.assertEqual(
            BaseRetentionPayloadBuilder._get_document_type_code_base(item), "01"
        )

    def test_nota_credito(self) -> None:
        """Con credit_note_no → '02'."""
        item = frappe._dict({"credit_note_no": "NC-001"})

        self.assertEqual(
            BaseRetentionPayloadBuilder._get_document_type_code_base(item), "02"
        )

    def test_nota_debito(self) -> None:
        """Con debit_note_no → '03'."""
        item = frappe._dict({"debit_note_no": "ND-001"})

        self.assertEqual(
            BaseRetentionPayloadBuilder._get_document_type_code_base(item), "03"
        )

    def test_nota_credito_por_is_return(self) -> None:
        """Con is_return=1 → '02'."""
        item = frappe._dict({"is_return": 1})

        self.assertEqual(
            BaseRetentionPayloadBuilder._get_document_type_code_base(item), "02"
        )


class TestTotalsPlaceholder(FrappeTestCase):
    """Tests para _build_totals_placeholder(): totales del encabezado."""

    def _make_builder(self, grand_total: float = 100.0) -> BaseRetentionPayloadBuilder:
        """Crea builder con grand_total específico para el placeholder."""
        doc = frappe._dict({"voucher_number": "20260400000001"})
        builder = BaseRetentionPayloadBuilder.__new__(BaseRetentionPayloadBuilder)
        builder.doc = doc
        builder._get_grand_total = lambda: grand_total
        return builder

    def test_nro_items(self) -> None:
        """NroItems refleja el conteo pasado como argumento."""
        builder = self._make_builder()
        totals: dict = builder._build_totals_placeholder(3)

        self.assertEqual(totals["NroItems"], "3")

    def test_grand_total_in_monto_total_con_iva(self) -> None:
        """MontoTotalConIVA usa el grand_total formateado."""
        builder = self._make_builder(grand_total=177947.55)
        totals: dict = builder._build_totals_placeholder(1)

        self.assertEqual(totals["MontoTotalConIVA"], "177947.55")

    def test_subtotal_is_zero(self) -> None:
        """En retenciones, Subtotal siempre es '0.00'."""
        builder = self._make_builder()
        totals: dict = builder._build_totals_placeholder(1)

        self.assertEqual(totals["Subtotal"], "0.00")
