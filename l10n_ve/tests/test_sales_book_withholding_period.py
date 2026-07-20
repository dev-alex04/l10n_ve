# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Tests de atribución por período de la retención de IVA en el Libro de Ventas.

Cubre ``l10n_ve.l10n_ve.report.sales_book.sales_book`` en sus dos paths
(legacy: ``posting_date <= corte fiscal``; nuevo: ``posting_date > corte``).

Reglas verificadas:

1. Retención con ``withholding_date`` DENTRO del período → se muestra normal.
2. Retención con ``withholding_date`` POSTERIOR al período → en el período de
   emisión ``iva_retained = 0`` y el comprobante queda oculto; la retención
   aparece como ajuste ``04-Ajus`` en el período de la retención.
3. Retención con ``withholding_date`` NULL (fecha de comprobante desconocida)
   → se atribuye al período de emisión y NO se pierde (regresión: el gate por
   ``BETWEEN`` la botaba de todos los períodos).
4. Path nuevo: la condición de fecha va entre paréntesis, de modo que una fecha
   dentro de período NO puede sustituir al comprobante ausente (precedencia
   AND/OR): sin voucher → ``iva_retained = 0`` aunque la fecha caiga en rango.

Los registros se insertan con ``db_insert()`` para evitar los hooks de submit
(HKA / facturación digital) y se revierten al final.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from l10n_ve.l10n_ve.report.sales_book import sales_book

_COMPANY = "GS LATAM TELECOM, C.A"
_CUSTOMER = "TEST-SB-WH-CUST"

# Montos fijos (moneda de la compañía, conversion_rate = 1)
_BASE_NET_TOTAL = 1000.0
_IVA = 160.0            # 16% de 1000
_RET_AMOUNT = 120.0    # 75% del IVA (retención)
_RET_RATE = 75.0

# posting <= corte fiscal → path LEGACY ; posting > corte → path NUEVO
_LEGACY_POSTING = "2026-03-05"
_NEW_POSTING = "2026-05-05"


class _SalesBookWithholdingBase(FrappeTestCase):
    """Fixtures compartidos: una factura por escenario, aislada por bill_no."""

    # Cada entrada: (key, posting_date, withholding_date, voucher)
    _INVOICES: list[tuple] = []

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.company_currency = frappe.get_cached_value("Company", _COMPANY, "default_currency")
        cls._cleanup()
        cls._make_customer()
        for idx, (key, posting, wh_date, voucher) in enumerate(cls._INVOICES, start=1):
            cls._make_invoice(key, posting, wh_date, voucher, idx)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup()
        frappe.db.commit()
        super().tearDownClass()

    # --- helpers de construcción -------------------------------------------------

    @classmethod
    def _inv_name(cls, key: str) -> str:
        return f"TEST-SB-WH-{key}"

    @classmethod
    def _bill_no(cls, key: str) -> str:
        return f"TEST-WH-{key}"

    @classmethod
    def _cleanup(cls) -> None:
        for key, *_ in cls._INVOICES:
            name = cls._inv_name(key)
            frappe.db.delete("Sales Taxes and Charges", {"parent": name})
            frappe.db.delete("Sales Invoice", {"name": name})
        frappe.db.delete("Customer", {"name": _CUSTOMER})

    @classmethod
    def _make_customer(cls) -> None:
        cust = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": _CUSTOMER,
            "customer_type": "Company",
            "is_special_taxpayer": 0,
        })
        cust.name = _CUSTOMER
        cust.db_insert()

    @classmethod
    def _make_invoice(cls, key, posting_date, withholding_date, voucher, idx) -> None:
        name = cls._inv_name(key)
        inv = frappe.get_doc({
            "doctype": "Sales Invoice",
            "company": _COMPANY,
            "customer": _CUSTOMER,
            "posting_date": posting_date,
            "currency": cls.company_currency,
            "conversion_rate": 1,
            "bill_no": cls._bill_no(key),
            "bill_control": f"00-9999{idx:04d}",
            "base_net_total": _BASE_NET_TOTAL,
            "net_total": _BASE_NET_TOTAL,
            "base_total_exempt": 0,
            "total_exempt": 0,
            "base_amount_igtf": 0,
            "total_igtf": 0,
            "is_return": 0,
            "is_void": 0,
            "is_debit_note": 0,
            "withholding_date": withholding_date,
            "vat_withholding_voucher_number": voucher,
            "remarks": '{"numeroControl": "TEST", "resultado": {"serie": "T"}}',
            "docstatus": 1,
        })
        inv.name = name
        inv.db_insert()

        # Línea de IVA (16%)
        cls._make_tax(name, "VAT", 16, _IVA, idx * 10 + 1)
        # Línea de retención de IVA (75% del IVA)
        cls._make_tax(name, "VAT Withholding", _RET_RATE, _RET_AMOUNT, idx * 10 + 2)

    @classmethod
    def _make_tax(cls, parent, charge_type, rate, amount, idx) -> None:
        tax = frappe.get_doc({
            "doctype": "Sales Taxes and Charges",
            "parent": parent,
            "parenttype": "Sales Invoice",
            "parentfield": "taxes",
            "idx": idx,
            "charge_type": charge_type,
            "rate": rate,
            "base_tax_amount": amount,
            "tax_amount": amount,
            "description": f"{charge_type} {rate}%",
        })
        tax.name = f"TEST-SB-WH-TAX-{idx}"
        tax.db_insert()

    # --- helpers de ejecución ----------------------------------------------------

    def _rows(self, from_date, to_date, key) -> list[dict]:
        filters = {"company": _COMPANY, "from_date": from_date, "to_date": to_date}
        _columns, data, *_ = sales_book.execute(filters)
        return [r for r in data if r.get("bill_no") == self._bill_no(key)]

    def _one(self, from_date, to_date, key) -> dict:
        rows = self._rows(from_date, to_date, key)
        self.assertEqual(len(rows), 1, f"Se esperaba 1 fila para {key} en {from_date}..{to_date}")
        return rows[0]


class TestSalesBookWithholdingLegacy(_SalesBookWithholdingBase):
    """Path legacy (posting_date <= corte fiscal)."""

    _INVOICES = [
        ("L-WITHIN", _LEGACY_POSTING, "2026-03-10", "RET-L-WITHIN"),
        ("L-AFTER", _LEGACY_POSTING, "2026-03-20", "RET-L-AFTER"),
        ("L-NULL", _LEGACY_POSTING, None, "RET-L-NULL"),
    ]

    def test_withholding_within_period_shown(self) -> None:
        row = self._one("2026-03-01", "2026-03-15", "L-WITHIN")
        self.assertAlmostEqual(flt(row.get("iva_retained")), _RET_AMOUNT, places=2)
        self.assertAlmostEqual(flt(row.get("vat_withholding_rate")), _RET_RATE, places=2)
        self.assertEqual(row.get("vat_withholding_voucher_number"), "RET-L-WITHIN")

    def test_withholding_after_period_hidden_in_emission(self) -> None:
        row = self._one("2026-03-01", "2026-03-15", "L-AFTER")
        self.assertEqual(flt(row.get("iva_retained")), 0.0)
        self.assertEqual(flt(row.get("vat_withholding_rate")), 0.0)
        self.assertFalse(row.get("vat_withholding_voucher_number"))
        self.assertFalse(row.get("withholding_date"))

    def test_withholding_after_period_shown_as_adjustment(self) -> None:
        row = self._one("2026-03-16", "2026-03-31", "L-AFTER")
        self.assertEqual(row.get("transaction_type"), "04-Ajus")
        self.assertAlmostEqual(flt(row.get("iva_retained")), _RET_AMOUNT, places=2)

    def test_withholding_date_null_attributed_to_emission(self) -> None:
        row = self._one("2026-03-01", "2026-03-15", "L-NULL")
        self.assertAlmostEqual(flt(row.get("iva_retained")), _RET_AMOUNT, places=2)
        self.assertAlmostEqual(flt(row.get("vat_withholding_rate")), _RET_RATE, places=2)
        self.assertEqual(row.get("vat_withholding_voucher_number"), "RET-L-NULL")


class TestSalesBookWithholdingNew(_SalesBookWithholdingBase):
    """Path nuevo (posting_date > corte fiscal)."""

    _INVOICES = [
        ("N-WITHIN", _NEW_POSTING, "2026-05-10", "RET-N-WITHIN"),
        ("N-AFTER", _NEW_POSTING, "2026-05-20", "RET-N-AFTER"),
        ("N-NULL", _NEW_POSTING, None, "RET-N-NULL"),
        ("N-NOVOUCHER", _NEW_POSTING, "2026-05-10", ""),
    ]

    def test_withholding_within_period_shown(self) -> None:
        row = self._one("2026-05-01", "2026-05-15", "N-WITHIN")
        self.assertAlmostEqual(flt(row.get("iva_retained")), _RET_AMOUNT, places=2)
        self.assertEqual(row.get("vat_withholding_voucher_number"), "RET-N-WITHIN")

    def test_withholding_after_period_hidden_in_emission(self) -> None:
        row = self._one("2026-05-01", "2026-05-15", "N-AFTER")
        self.assertEqual(flt(row.get("iva_retained")), 0.0)
        self.assertFalse(row.get("vat_withholding_voucher_number"))

    def test_withholding_after_period_shown_as_adjustment(self) -> None:
        row = self._one("2026-05-16", "2026-05-31", "N-AFTER")
        self.assertEqual(row.get("transaction_type"), "04-Ajus")
        self.assertAlmostEqual(flt(row.get("iva_retained")), _RET_AMOUNT, places=2)

    def test_withholding_date_null_attributed_to_emission(self) -> None:
        row = self._one("2026-05-01", "2026-05-15", "N-NULL")
        self.assertAlmostEqual(flt(row.get("iva_retained")), _RET_AMOUNT, places=2)
        self.assertEqual(row.get("vat_withholding_voucher_number"), "RET-N-NULL")

    def test_in_period_date_does_not_bypass_missing_voucher(self) -> None:
        """Precedencia AND/OR: fecha en período sin comprobante NO muestra retención."""
        row = self._one("2026-05-01", "2026-05-15", "N-NOVOUCHER")
        self.assertEqual(flt(row.get("iva_retained")), 0.0)
        self.assertEqual(flt(row.get("vat_withholding_rate")), 0.0)
