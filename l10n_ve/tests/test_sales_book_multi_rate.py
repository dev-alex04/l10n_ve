# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Test de regresión para el Reporte Libro de Ventas — base imponible por alícuota.

Cubre el path NUEVO (posting_date > corte fiscal) de
``l10n_ve.l10n_ve.report.sales_book.sales_book``.

Regresión: antes, la base por alícuota se calculaba como un indicador booleano
(SUM(CASE...THEN 1)) multiplicado por la base imponible TOTAL de la factura.
En facturas multi-alícuota (p. ej. 16% + 8%) cada columna recibía la base
completa → base inflada/duplicada → rechazo del Libro de Ventas por el SENIAT.

El fix deriva la base de cada alícuota del IVA por fila:
``base_tax_amount * (100 / rate)`` (base_tax_amount ya está en VEF), de modo que
cada columna recibe SOLO su porción y la suma de bases == base imponible total.

Los registros se insertan con ``db_insert()`` para evitar los hooks de submit
(HKA / facturación digital) y se revierten al final de cada test.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from l10n_ve.l10n_ve.report.sales_book import sales_book

# posting_date posterior al corte fiscal → activa el path NUEVO
_POSTING_DATE = "2026-05-01"
_COMPANY = "GS LATAM TELECOM, C.A"
_CUSTOMER = "TEST-SB-MULTIRATE-CUST"
_INVOICE = "TEST-SB-MULTIRATE-INV"
_BILL_NO = "TEST-MR-0001"

# Factura: base imponible total 10000 VEF (sin exento), repartida en dos alícuotas
#   16% → base 8000, IVA 1280
#    8% → base 2000, IVA 160
_BASE_GENERAL = 8000.0
_IVA_GENERAL = 1280.0
_BASE_REDUCED = 2000.0
_IVA_REDUCED = 160.0
_BASE_NET_TOTAL = _BASE_GENERAL + _BASE_REDUCED  # 10000


class TestSalesBookMultiRateBase(FrappeTestCase):
    """El path nuevo debe repartir la base imponible por alícuota."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.company_currency = frappe.get_cached_value("Company", _COMPANY, "default_currency")
        cls._cleanup()  # idempotencia ante corridas previas interrumpidas
        cls._make_customer()
        cls._make_invoice()
        cls._make_tax("VAT", 16, base_tax_amount=_IVA_GENERAL, tax_amount=_IVA_GENERAL, idx=1)
        cls._make_tax("VAT", 8, base_tax_amount=_IVA_REDUCED, tax_amount=_IVA_REDUCED, idx=2)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup()
        frappe.db.commit()
        super().tearDownClass()

    @classmethod
    def _cleanup(cls) -> None:
        frappe.db.delete("Sales Taxes and Charges", {"parent": _INVOICE})
        frappe.db.delete("Sales Invoice", {"name": _INVOICE})
        frappe.db.delete("Customer", {"name": _CUSTOMER})

    @classmethod
    def _make_customer(cls) -> None:
        cust = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": _CUSTOMER,
            "customer_type": "Company",
            "is_special_taxpayer": 0,  # contribuyente NO especial → columnas *_non_taxpayer
        })
        cust.name = _CUSTOMER
        cust.db_insert()

    @classmethod
    def _make_invoice(cls) -> None:
        inv = frappe.get_doc({
            "doctype": "Sales Invoice",
            "company": _COMPANY,
            "customer": _CUSTOMER,
            "posting_date": _POSTING_DATE,
            "currency": cls.company_currency,
            "conversion_rate": 1,
            "bill_no": _BILL_NO,
            "bill_control": "00-99990001",
            "base_net_total": _BASE_NET_TOTAL,
            "net_total": _BASE_NET_TOTAL,
            "base_total_exempt": 0,
            "total_exempt": 0,
            "base_amount_igtf": 0,
            "total_igtf": 0,
            "is_return": 0,
            "is_void": 0,
            "is_debit_note": 0,
            # remarks con "numeroControl" para pasar el filtro HKA si está activo
            "remarks": '{"numeroControl": "TEST", "resultado": {"serie": "T"}}',
            "docstatus": 1,
        })
        inv.name = _INVOICE
        inv.db_insert()

    @classmethod
    def _make_tax(cls, charge_type, rate, base_tax_amount, tax_amount, idx) -> None:
        tax = frappe.get_doc({
            "doctype": "Sales Taxes and Charges",
            "parent": _INVOICE,
            "parenttype": "Sales Invoice",
            "parentfield": "taxes",
            "idx": idx,
            "charge_type": charge_type,
            "rate": rate,
            "base_tax_amount": base_tax_amount,
            "tax_amount": tax_amount,
            "description": f"IVA {rate}%",
        })
        tax.name = f"TEST-SB-TAX-{idx}"
        tax.db_insert()

    def _run_report_row(self) -> dict:
        filters = {
            "company": _COMPANY,
            "from_date": "2026-04-16",
            "to_date": "2026-05-31",
        }
        _columns, data, *_ = sales_book.execute(filters)
        rows = [r for r in data if r.get("bill_no") == _BILL_NO]
        self.assertEqual(len(rows), 1, "Debe existir exactamente una fila para la factura de prueba")
        return rows[0]

    def test_base_split_por_alicuota(self) -> None:
        """Cada columna de base recibe SOLO su porción, no la base total."""
        row = self._run_report_row()

        self.assertAlmostEqual(flt(row.get("base_general_non_taxpayer")), _BASE_GENERAL, places=2)
        self.assertAlmostEqual(flt(row.get("base_reduced_non_taxpayer")), _BASE_REDUCED, places=2)
        self.assertAlmostEqual(flt(row.get("iva_general_non_taxpayer")), _IVA_GENERAL, places=2)
        self.assertAlmostEqual(flt(row.get("iva_reduced_non_taxpayer")), _IVA_REDUCED, places=2)

    def test_suma_de_bases_igual_base_imponible_total(self) -> None:
        """Σ bases por alícuota == base_net_total - exento (no se infla)."""
        row = self._run_report_row()

        suma_bases = flt(row.get("base_general_non_taxpayer")) + flt(row.get("base_reduced_non_taxpayer"))
        self.assertAlmostEqual(suma_bases, _BASE_NET_TOTAL, places=2)

    def test_alicuota_adicional_sin_movimiento_queda_en_cero(self) -> None:
        """La alícuota adicional (31%), ausente en la factura, no recibe base."""
        row = self._run_report_row()

        self.assertEqual(flt(row.get("base_additional_non_taxpayer")), 0.0)
        self.assertEqual(flt(row.get("iva_additional_non_taxpayer")), 0.0)
