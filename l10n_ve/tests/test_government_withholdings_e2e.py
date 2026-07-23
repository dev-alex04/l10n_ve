# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
E2E de las retenciones gubernamentales: cobro real de un ente Government con timbre (Miranda 0,2%)
+ Responsabilidad Social (3%). Valida, sobre datos reales del clon Galanet:

- El hook puebla PE.deductions con las 2 retenciones (contra la cuenta única de gasto).
- El pago BALANCEA (depósito corto + deducciones = asignado); difference_amount ≈ 0.
- Al emitir (submit) el GL cuadra: Debe gasto (retenciones) + Debe banco (depósito) = Haber CxC (bruto).
- La factura queda saldada (outstanding = 0).
- El objetivo del guard de mint (base_paid_amount) = depósito neto, no el bruto → el "pago corto" se resuelve.

FrappeTestCase envuelve cada test en transacción y hace rollback: NO persiste nada.
"""

import frappe
from frappe.utils import flt
from frappe.tests.utils import FrappeTestCase

from l10n_ve.overrides.payment_entry import CustomPaymentEntry

COMPANY = "Galanet Solution C.A."
CXC = "1105001 - Cuentas por Cobrar Clientes - Galanet"
# Cobro en efectivo (modo Cash) para AISLAR el GL de la retención del gate bancario de mint
# (before_submit_receive_payment exige un depósito conciliado; ese flujo se valida aparte por el
# código de deposit_covers_payment + la aserción base_paid_amount==depósito neto de este mismo test).
CASH = "1101002 - Caja Tesorería Bolívares - Galanet"
MODE_OF_PAYMENT = "Efectivo"
GOV_ACCT = "6203009 - Retenciones Gubernamentales - Galanet"
COST_CENTER = "Principal - Galanet"
INCOME = "4101001 - Ingresos Servicios de Internet - Galanet"


def setUpModule() -> None:
    """Aprovisiona el esquema (doctypes + custom fields) para no depender de un `bench migrate`
    previo del site: sincroniza los 3 doctypes de la feature y crea los custom fields de
    Company/Customer/Payment Entry que enganchan las tablas hijas."""
    from l10n_ve.setup import (
        create_government_withholding_custom_fields,
        create_stamp_tax_rates,
        link_government_withholding_account,
    )

    for dt in ("ve_stamp_tax_rate", "ve_government_withholding", "ve_payment_government_withholding",
               "venezuela_account_settings"):
        frappe.reload_doc("l10n_ve", "doctype", dt)
    create_government_withholding_custom_fields()
    link_government_withholding_account()  # enlaza Company.government_withholding_account por nombre
    create_stamp_tax_rates()  # siembra las tarifas por estado (incl. Miranda) de forma idempotente
    frappe.clear_cache()


class TestGovernmentWithholdingsE2E(FrappeTestCase):
    def setUp(self) -> None:
        # El E2E está atado al plan de cuentas de Galanet. En un site sin él (o sin el estado
        # Miranda) se SALTA limpio en vez de ERROR. La master-data (territorio/grupo/ítem) se
        # RESUELVE de lo existente en el site en vez de hardcodear nombres que pueden no existir.
        if not frappe.db.exists("Company", COMPANY):
            self.skipTest(f"compañía {COMPANY} ausente en este site")
        for acct in (CXC, CASH, GOV_ACCT, INCOME):
            if not frappe.db.exists("Account", acct):
                self.skipTest(f"cuenta {acct} ausente: el E2E requiere el plan de cuentas de {COMPANY}")
        self.miranda_state = frappe.db.get_value("VE State", {"state": "Miranda"}, "name")
        if not self.miranda_state:
            self.skipTest("VE State 'Miranda' ausente en este site")
        self.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
        self.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        if not self.territory or not self.customer_group:
            self.skipTest("faltan Territory / Customer Group hoja en este site")
        self.item = frappe.db.get_value("Item", {"is_sales_item": 1, "is_stock_item": 0}, "name")
        if not self.item:
            item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
            self.item = frappe.get_doc({
                "doctype": "Item", "item_code": "E2E-GOV-ITEM", "item_name": "E2E-GOV-ITEM",
                "item_group": item_group, "stock_uom": "Nos.", "is_stock_item": 0, "is_sales_item": 1,
            }).insert(ignore_permissions=True).name

    def test_full_flow_timbre_and_social(self) -> None:
        # Resp. Social a 3% (config flat)
        settings = frappe.get_single("Venezuela Account Settings")
        settings.responsibility_social_rate = 3
        settings.save(ignore_permissions=True)

        # Ente Government con opt-in: Timbre (Miranda) + Responsabilidad Social
        cust = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "E2E ENTE GUBERNAMENTAL",
            "customer_group": self.customer_group,
            "territory": self.territory,
            "nature_of_the_taxpayer": "Government",
            "tax_id": "G200000001",
            "mobile_no": "04120000000",
            "email_id": "e2e-ente@example.com",
            "government_withholdings": [
                {"withholding_type": "Timbre Fiscal", "state": self.miranda_state, "enabled": 1},
                {"withholding_type": "Responsabilidad Social", "enabled": 1},
            ],
        }).insert(ignore_permissions=True)

        # Factura de venta emitida
        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": cust.name,
            "company": COMPANY,
            "currency": "VEF",
            "conversion_rate": 1,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "cost_center": COST_CENTER,
            "update_stock": 0,
            "items": [{
                "item_code": self.item,
                "qty": 1,
                "rate": 100000,
                "income_account": INCOME,
                "cost_center": COST_CENTER,
            }],
        })
        si.insert(ignore_permissions=True)
        si.submit()
        base = flt(si.outstanding_amount, 2)
        self.assertGreater(base, 0, "la factura debe tener outstanding")

        # Retenciones esperadas (mismo redondeo que el hook)
        timbre = flt(base * 0.2 / 100, 2)
        social = flt(base * 3 / 100, 2)
        total_ret = flt(timbre + social, 2)
        deposit = flt(base - total_ret, 2)

        # Cobro: depósito corto (el ente retuvo timbre + social) asignado a la factura
        pe = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "company": COMPANY,
            "party_type": "Customer",
            "party": cust.name,
            "paid_from": CXC,
            "paid_to": CASH,
            "mode_of_payment": MODE_OF_PAYMENT,
            "paid_from_account_currency": "VEF",
            "paid_to_account_currency": "VEF",
            "paid_on_currency": "VEF",
            "source_exchange_rate": 1,
            "target_exchange_rate": 1,
            "paid_amount": deposit,
            "received_amount": deposit,
            "reference_no": "E2EGOV001",
            "reference_date": frappe.utils.today(),
            "cost_center": COST_CENTER,
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": si.name,
                "total_amount": base,
                "outstanding_amount": base,
                "allocated_amount": base,
            }],
        })
        pe.insert(ignore_permissions=True)  # dispara validate -> calculate_government_withholdings

        # (1) El hook creó las 2 deducciones contra la cuenta de gasto
        gov = [d for d in pe.deductions if (d.description or "").startswith(CustomPaymentEntry.GOV_WITHHOLDING_MARKER)]
        self.assertEqual(len(gov), 2, "deben registrarse timbre + responsabilidad social")
        self.assertTrue(all(d.account == GOV_ACCT for d in gov), "todas a la cuenta única de gasto")
        self.assertAlmostEqual(sum(flt(d.amount) for d in gov), total_ret, places=2)

        # (2) El pago balancea (depósito corto + deducciones = asignado)
        self.assertAlmostEqual(flt(pe.difference_amount), 0.0, places=2, msg="el pago debe cuadrar")

        # (3) Emitir -> GL cuadra y la CxC se salda por el bruto
        pe.submit()
        gl = frappe.get_all("GL Entry", filters={"voucher_no": pe.name}, fields=["account", "debit", "credit"])
        self.assertAlmostEqual(sum(flt(g.debit) for g in gl if g.account == GOV_ACCT), total_ret, places=2,
                               msg="el gasto de retenciones debe ir a 6203009")
        self.assertAlmostEqual(sum(flt(g.debit) for g in gl), sum(flt(g.credit) for g in gl), places=2,
                               msg="el asiento debe cuadrar")
        self.assertAlmostEqual(sum(flt(g.credit) for g in gl if g.account == CXC), base, places=2,
                               msg="la CxC se salda por el monto bruto de la factura")

        # (4) Factura saldada
        si.reload()
        self.assertAlmostEqual(flt(si.outstanding_amount), 0.0, places=2, msg="la factura debe quedar en 0")

        # (5) Es un pago corto REAL (el banco recibió MENOS que la factura) y aun así se saldó,
        # porque el faltante lo cubren EXACTAMENTE las deducciones de retención que creó el hook
        # (no la aritmética del test): esa es la esencia del "pago corto" que la feature resuelve.
        self.assertLess(flt(pe.base_paid_amount), base, "el depósito debe ser corto vs la factura")
        self.assertAlmostEqual(flt(base) - flt(pe.base_paid_amount),
                               sum(flt(d.amount) for d in gov), places=2,
                               msg="el faltante del depósito = suma de las retenciones registradas")
