# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Test de regresión del Libro de Compras — total de la compra.

El reporte reconstruía el total así: ``base_grand_total + TODAS las filas Deduct``.
Eso da el bruto solo si la retención se aplicó ANTES de validar la factura. Cuando se
aplica después, el ISLR se contabiliza en un asiento de diario aparte y nunca se resta
del total de la factura: devolvérselo lo sumaba dos veces. Pasó con
ACC-PINV-2026-00322 y metió Bs 581.893,55 de más en el panel de septiembre de 2026.

El fix trae el total del propio documento (``base_total_with_vat``), que no depende de
ninguna fila de retención.

Los registros se insertan con ``db_insert()`` para evitar los hooks de submit y se
revierten al final.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from l10n_ve.l10n_ve.report.purchase_book import purchase_book

_POSTING_DATE = "2026-05-01"
_COMPANY = "GS LATAM TELECOM, C.A"
_SUPPLIER = "TEST-PB-ISLR-SUPP"
_INVOICE = "TEST-PB-ISLR-INV"
_BILL_NO = "TEST-PB-0001"

# Factura de 10.000 + IVA 16 % = 11.600 de total de compra.
_BASE = 10000.0
_IVA = 1600.0
_BRUTO = _BASE + _IVA

# Retención de IVA del 75 %: esta SÍ se descontó al validar.
_RET_IVA = 1200.0
# Retención de ISLR aplicada DESPUÉS de validar: su asiento es aparte, así que el total
# de la factura nunca la restó.
_RET_ISLR = 500.0
_TOTAL_GUARDADO = _BASE + _IVA - _RET_IVA

# Lo que devolvía el reporte antes del fix: le sumaba también el ISLR.
_TOTAL_VIEJO = _TOTAL_GUARDADO + _RET_IVA + _RET_ISLR


class TestPurchaseBookTotalBruto(FrappeTestCase):

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.company_currency = frappe.get_cached_value("Company", _COMPANY, "default_currency")
        cls._cleanup()
        cls._make_supplier()
        cls._make_invoice()
        cls._make_tax("VAT", 16, _IVA, "Add", 1)
        cls._make_tax("VAT Withholding", 75, _RET_IVA, "Deduct", 2)
        cls._make_tax("ISLR", 5, _RET_ISLR, "Deduct", 3)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup()
        frappe.db.commit()
        super().tearDownClass()

    @classmethod
    def _cleanup(cls) -> None:
        frappe.db.delete("Purchase Taxes and Charges", {"parent": _INVOICE})
        frappe.db.delete("Purchase Invoice", {"name": _INVOICE})
        frappe.db.delete("Supplier", {"name": _SUPPLIER})

    @classmethod
    def _make_supplier(cls) -> None:
        sup = frappe.get_doc({
            "doctype": "Supplier",
            "supplier_name": _SUPPLIER,
            "supplier_type": "Company",
            "tax_id": "J123456789",
            "type_of_person": "Domiciled legal entity",
        })
        sup.name = _SUPPLIER
        sup.db_insert()

    @classmethod
    def _make_invoice(cls) -> None:
        inv = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "company": _COMPANY,
            "supplier": _SUPPLIER,
            "supplier_name": _SUPPLIER,
            "posting_date": _POSTING_DATE,
            "bill_date": _POSTING_DATE,
            "currency": cls.company_currency,
            "conversion_rate": 1,
            "bill_no": _BILL_NO,
            "bill_control": "00-99990002",
            "base_total": _BASE,
            "total_exempt": 0,
            "base_total_with_vat": _BRUTO,
            # Neto SOLO de la retención de IVA: el ISLR entró después de validar.
            "base_grand_total": _TOTAL_GUARDADO,
            "total_igtf": 0,
            "is_return": 0,
            "is_debit_note": 0,
            "docstatus": 1,
        })
        inv.name = _INVOICE
        inv.db_insert()

    @classmethod
    def _make_tax(cls, charge_type, rate, base_tax_amount, add_deduct, idx) -> None:
        tax = frappe.get_doc({
            "doctype": "Purchase Taxes and Charges",
            "parent": _INVOICE,
            "parenttype": "Purchase Invoice",
            "parentfield": "taxes",
            "idx": idx,
            "charge_type": charge_type,
            "add_deduct_tax": add_deduct,
            "category": "Total",
            "rate": rate,
            "base_tax_amount": base_tax_amount,
            "tax_amount": base_tax_amount,
            "description": f"{charge_type} {rate}%",
        })
        tax.name = f"TEST-PB-TAX-{idx}"
        tax.db_insert()

    def _fila(self) -> dict:
        filtros = {"company": _COMPANY, "from_date": "2026-04-16", "to_date": "2026-05-31"}
        _columnas, data, *_ = purchase_book.execute(filtros)
        filas = [r for r in data if r.get("bill_no") == _BILL_NO]
        self.assertEqual(len(filas), 1, "Debe haber exactamente una fila para la factura de prueba")
        return filas[0]

    def test_el_total_es_el_bruto_del_documento(self) -> None:
        """Base + IVA, sin devolverle retenciones que el total nunca restó."""
        fila = self._fila()

        self.assertAlmostEqual(flt(fila.get("grand_total")), _BRUTO, places=2)

    def test_el_islr_aplicado_despues_no_infla_el_total(self) -> None:
        """La regresión concreta: antes sumaba el ISLR de más."""
        fila = self._fila()

        self.assertNotAlmostEqual(flt(fila.get("grand_total")), _TOTAL_VIEJO, places=2)
        self.assertAlmostEqual(_TOTAL_VIEJO - flt(fila.get("grand_total")), _RET_ISLR, places=2)

    def test_el_total_cuadra_con_las_demas_casillas_del_panel(self) -> None:
        """Total Compras == exento + base + impuesto, que es lo que valida contabilidad."""
        fila = self._fila()

        suma = (flt(fila.get("total_exempt")) + flt(fila.get("base_general"))
                + flt(fila.get("impuesto_general")) + flt(fila.get("base_reducida"))
                + flt(fila.get("impuesto_reducida")) + flt(fila.get("base_adicional"))
                + flt(fila.get("impuesto_adicional")))

        self.assertAlmostEqual(flt(fila.get("grand_total")), suma, places=2)
