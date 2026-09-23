# Copyright (c) 2026, Galanet Solution and contributors
# See license.txt
"""El envío automático a HKA toma toda factura aprobada sin número de control.

Antes tomaba sólo las «Pagadas» (diseño emitir-al-pagar), y una aprobada que no quedaba
pagada del todo nunca salía, aunque ya estuviera sumando en el mayor. Caso real (correo de
Lilibeth Marcano, 23-sep-2026): seis facturas de Chejende aprobadas en septiembre al
registrar pagos hechos en agosto; con la tasa del día de la aprobación el pago no alcanzó
en bolívares, quedaron «Parcialmente pagadas» y el Débito Fiscal de agosto las contaba sin
documento fiscal.

Las facturas se insertan con `db_insert`, sin validación: lo que se prueba es qué toma el
cron, no el alta de una factura. Así corre igual en el sitio base de la CI.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_first_day, now_datetime, today

from l10n_ve.digital_invoice import unsent_documents
from l10n_ve.digital_invoice.tfhka_integration import (
    _UNPAID_SEND_GRACE_MINUTES,
    _get_pending_hka_invoices,
)

BRANCH = "ZZTEST-SUCURSAL-HKA"
AFTER_GRACE = _UNPAID_SEND_GRACE_MINUTES + 5


def _invoice(
    status: str = "Partly Paid",
    docstatus: int = 1,
    minutes_ago: int = AFTER_GRACE,
    is_return: int = 0,
    bill_control: str | None = None,
) -> str:
    """Una factura de la sucursal de prueba, aprobada hace `minutes_ago` minutos."""
    doc = frappe.get_doc({
        "doctype": "Sales Invoice",
        "name": f"ZZTEST-HKA-{frappe.generate_hash(length=8)}",
        "docstatus": docstatus,
        "status": status,
        "branch": BRANCH,
        "posting_date": today(),
        "is_return": is_return,
        "is_debit_note": 0,
        "bill_control": bill_control,
        "customer_name": "Cliente de prueba",
        "grand_total": 25,
        "currency": "USD",
    })
    doc.db_insert()
    # El último cambio marca cuándo quedó aprobada: se fija a mano para simular la edad.
    frappe.db.sql(
        "UPDATE `tabSales Invoice` SET modified = %s WHERE name = %s",
        (add_to_date(now_datetime(), minutes=-minutes_ago), doc.name),
    )
    return doc.name


def _pending() -> list[str]:
    return _get_pending_hka_invoices([BRANCH], cutoff_date="2026-04-01")


class TestPendingHkaInvoices(FrappeTestCase):
    def setUp(self):
        self.addCleanup(frappe.db.rollback)

    def test_paid_goes_out_right_away(self):
        """Lo de siempre: la pagada sale en la vuelta siguiente, sin esperar."""
        invoice = _invoice(status="Paid", minutes_ago=1)
        self.assertIn(invoice, _pending())

    def test_partly_paid_goes_out_after_the_grace(self):
        """El caso de Chejende: aprobada, sin pagar del todo, y ya en el mayor."""
        invoice = _invoice(status="Partly Paid")
        self.assertIn(invoice, _pending())

    def test_unpaid_goes_out_after_the_grace(self):
        """La factura a crédito aprobada que nadie envió a mano."""
        invoice = _invoice(status="Unpaid")
        self.assertIn(invoice, _pending())

    def test_recently_approved_unpaid_waits_for_the_manual_send(self):
        """Recién aprobada: se le da tiempo a quien la aprobó de enviarla con el botón."""
        invoice = _invoice(status="Unpaid", minutes_ago=2)
        self.assertNotIn(invoice, _pending())

    def test_draft_never_goes_out(self):
        """Emitir al pagar sigue valiendo para los borradores: no tocan el mayor."""
        invoice = _invoice(status="Draft", docstatus=0, minutes_ago=600)
        self.assertNotIn(invoice, _pending())

    def test_return_never_goes_out(self):
        invoice = _invoice(status="Return", is_return=1)
        self.assertNotIn(invoice, _pending())

    def test_already_emitted_never_goes_out(self):
        invoice = _invoice(status="Partly Paid", bill_control="00-00123456")
        self.assertNotIn(invoice, _pending())

    def test_invoice_with_a_successful_send_never_goes_out(self):
        invoice = _invoice(status="Partly Paid")
        frappe.get_doc({
            "doctype": "VE Digital Invoice Log",
            "sales_invoice": invoice,
            "document_type": "Sales Invoice",
            "status": "Success",
            "endpoint": "Emision",
        }).db_insert()
        self.assertNotIn(invoice, _pending())


class TestUnsentNoticeSeesApprovedUnpaid(FrappeTestCase):
    """El aviso de documentos sin enviar tenía el mismo punto ciego que el cron."""

    def setUp(self):
        self.addCleanup(frappe.db.rollback)

    def test_partly_paid_that_did_not_go_out_is_reported(self):
        invoice = _invoice(status="Partly Paid", minutes_ago=120)
        deadline = add_to_date(now_datetime(), minutes=-unsent_documents.DEFAULT_GRACE_MINUTES)

        with (
            patch.object(unsent_documents, "_active_series_branches", return_value={BRANCH}),
            patch.object(unsent_documents, "_last_logs", return_value={}),
        ):
            rows = unsent_documents._collect_sales_invoices(
                get_first_day(today()), today(), deadline, "2026-04-01"
            )

        self.assertIn(invoice, [r["name"] for r in rows])
