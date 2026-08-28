# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""E2E del pago de una Nota de Debito de compra.

Los tests unitarios de `test_purchase_debit_note_payment` cubren las piezas por
separado --lista blanca, sentido del pago, shim de `set_status`-- pero ninguna de
ellas EMITE un pago, y el bug que motivo esta feature solo aparece emitiendolo: al
aprobar el Payment Entry, el hook de GL Entry recalcula el outstanding y llama a
`set_status`, que reventaba con AttributeError por `is_return`. Un test con
`PurchaseInvoice.set_status` mockeado no lo habria atrapado nunca.

Dos detalles del entorno, iguales a los de `test_government_withholdings_e2e`:

- Se paga en EFECTIVO a proposito. El hook `before_submit_receive_payment` de mint
  exige un retiro bancario conciliado para los modos que no son cash-like, y esa
  guarda es de otro flujo: mezclarla aca haria fallar el test por un motivo ajeno.
- Los `on_submit` commitean, asi que el rollback de FrappeTestCase no alcanza:
  setUp/tearDown barren por `reference_no` los artefactos de la corrida.
"""

import frappe
from frappe.utils import flt
from frappe.tests.utils import FrappeTestCase

from l10n_ve.overrides.payment_entry import get_payment_entry

MARCA = "E2ENDCOMPRA"


class TestPurchaseDebitNotePaymentE2E(FrappeTestCase):
    def setUp(self) -> None:
        nd = frappe.db.sql("""
            SELECT name, company, supplier, credit_to, currency, outstanding_amount, grand_total
            FROM `tabVE Purchase Debit Note`
            WHERE docstatus = 1 AND outstanding_amount > 0
            ORDER BY outstanding_amount ASC LIMIT 1
        """, as_dict=True)
        if not nd:
            self.skipTest("no hay Nota de Debito de compra emitida con saldo en este site")
        self.nd = nd[0]

        # Modo de pago en efectivo EN LA MONEDA de la nota: `validate_payment_mode_currency`
        # corta si no coinciden, y ese seria un fallo ajeno a lo que se prueba aca.
        modo = frappe.db.sql("""
            SELECT mop.name, mopa.default_account
            FROM `tabMode of Payment` mop
            JOIN `tabMode of Payment Account` mopa ON mopa.parent = mop.name
            JOIN `tabAccount` a ON a.name = mopa.default_account
            WHERE mop.type = 'Cash' AND mopa.company = %s
              AND COALESCE(NULLIF(a.account_currency, ''), %s) = %s
            LIMIT 1
        """, (self.nd.company, self.nd.currency, self.nd.currency), as_dict=True)
        if not modo:
            self.skipTest(f"sin modo de pago en efectivo en {self.nd.currency} para {self.nd.company}")
        self.modo, self.caja = modo[0].name, modo[0].default_account
        self._cleanup()

    def tearDown(self) -> None:
        self._cleanup()
        frappe.db.commit()

    def _cleanup(self) -> None:
        for pe in frappe.get_all("Payment Entry",
                                 filters={"reference_no": ["like", f"{MARCA}%"]},
                                 fields=["name", "docstatus"]):
            if pe.docstatus == 1:
                frappe.get_doc("Payment Entry", pe.name).cancel()
            frappe.delete_doc("Payment Entry", pe.name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _saldo(self) -> float:
        """Saldo actual, leido de la BD.

        No se usa el valor que quedo en setUp: los `on_submit` commitean, asi que
        una prueba anterior pudo moverlo. Cada test parte de lo que hay.
        """
        return flt(frappe.db.get_value(
            "VE Purchase Debit Note", self.nd.name, "outstanding_amount"))

    def _pagar(self, monto=None, sufijo="01"):
        pe = get_payment_entry("VE Purchase Debit Note", self.nd.name)
        pe.mode_of_payment = self.modo
        pe.paid_from = self.caja
        pe.reference_no = f"{MARCA}{sufijo}"
        pe.reference_date = frappe.utils.nowdate()
        if monto is not None:
            pe.paid_amount = monto
            pe.received_amount = monto
            pe.references[0].allocated_amount = monto
        pe.insert(ignore_permissions=True)
        pe.submit()
        return pe

    # ── lo que arma get_payment_entry ────────────────────────────────────────

    def test_el_pago_sale_como_pago_a_proveedor(self) -> None:
        pe = get_payment_entry("VE Purchase Debit Note", self.nd.name)
        self.assertEqual(pe.payment_type, "Pay")
        self.assertEqual(pe.party_type, "Supplier")
        self.assertEqual(pe.party, self.nd.supplier)
        # en un pago la cuenta de la parte va en paid_to (no en paid_from)
        self.assertEqual(pe.paid_to, self.nd.credit_to)
        self.assertEqual(
            [(r.reference_doctype, r.reference_name) for r in pe.references],
            [("VE Purchase Debit Note", self.nd.name)],
        )

    # ── el pago de verdad: emitir y mirar el saldo ────────────────────────────

    def test_pago_total_deja_la_nota_en_cero(self) -> None:
        antes = self._saldo()
        self.assertGreater(antes, 0)

        self._pagar(sufijo="TOT")

        desp = frappe.db.get_value(
            "VE Purchase Debit Note", self.nd.name,
            ["outstanding_amount", "status"], as_dict=True)
        self.assertEqual(flt(desp.outstanding_amount), 0.0)
        self.assertEqual(desp.status, "Paid")

    def test_pago_parcial_baja_el_saldo_lo_justo(self) -> None:
        antes = self._saldo()
        parcial = flt(antes / 2, 2)
        if parcial <= 0:
            self.skipTest("la nota no tiene saldo suficiente para un pago parcial")

        self._pagar(monto=parcial, sufijo="PAR")

        desp = self._saldo()
        self.assertAlmostEqual(desp, antes - parcial, places=2)
        self.assertGreater(desp, 0, "un pago parcial no puede saldar la nota")

    def test_el_asiento_va_contra_la_nota_y_no_contra_la_factura(self) -> None:
        """El GL tiene que apuntar a la ND: es ella la que lleva el outstanding."""
        pe = self._pagar(sufijo="GL")

        gl = frappe.get_all("GL Entry",
                            filters={"voucher_no": pe.name, "is_cancelled": 0},
                            fields=["account", "debit", "credit",
                                    "against_voucher_type", "against_voucher"])
        cxp = [g for g in gl if g.account == self.nd.credit_to]
        self.assertTrue(cxp, "no hay asiento contra la cuenta por pagar de la nota")
        # una ND de compra es un pasivo: pagarla lo DEBITA
        self.assertGreater(flt(cxp[0].debit), 0)
        self.assertEqual(cxp[0].against_voucher_type, "VE Purchase Debit Note")
        self.assertEqual(cxp[0].against_voucher, self.nd.name)

        caja = [g for g in gl if g.account == self.caja]
        self.assertTrue(caja, "no hay contrapartida en la cuenta de efectivo")
        self.assertGreater(flt(caja[0].credit), 0)

    def test_set_status_no_revienta_al_pagar(self) -> None:
        """Guarda de regresion del bug que motivo la feature.

        `set_status` de ERPNext lee `is_return`, que la ND no tiene en su esquema.
        Se llega a el desde el hook de GL Entry al APROBAR el pago, no al emitir la
        nota. Sin mock de por medio: si el shim se cae, este submit vuelve a tirar
        AttributeError.
        """
        pe = self._pagar(sufijo="ST")
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(
            frappe.db.get_value("VE Purchase Debit Note", self.nd.name, "status"),
            "Paid",
        )


    def test_anular_el_pago_devuelve_el_saldo(self) -> None:
        """Segunda guarda de regresion, y la que encontro el bug del hook.

        `update_ve_outstanding_amount` cortaba con `if doc.is_cancelled: return`. Al
        anular un pago, ERPNext marca sus GL Entry como cancelados y dispara ese mismo
        on_update: con el corte, el outstanding se quedaba en el valor de cuando estaba
        pagada y la nota figuraba saldada PARA SIEMPRE. Sin este test no se ve, porque
        emitir el pago funciona igual.
        """
        antes = self._saldo()
        self.assertGreater(antes, 0)

        pe = self._pagar(sufijo="ANU")
        self.assertEqual(self._saldo(), 0.0, "el pago no salda la nota")

        frappe.get_doc("Payment Entry", pe.name).cancel()

        self.assertAlmostEqual(self._saldo(), antes, places=2,
                               msg="anular el pago tiene que devolver el saldo")
        self.assertNotEqual(
            frappe.db.get_value("VE Purchase Debit Note", self.nd.name, "status"),
            "Paid",
            "la nota no puede seguir figurando pagada tras anular el pago",
        )
