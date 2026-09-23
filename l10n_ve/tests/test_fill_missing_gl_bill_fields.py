# Copyright (c) 2026, Galanet Solution and contributors
# See license.txt
"""La red nocturna que copia al mayor el número fiscal que le falte.

Caso que la motivó: ACC-SINV-2026-21357 (factura 12258, control 00-00195285), emitida el
4-ago. El documento tenía número y control, pero sus siete líneas del mayor no, y el Libro
Mayor la mostraba vacía en el análisis del Débito Fiscal. La copia al emitir había fallado
sin dejar rastro: una entre más de 17 mil.

Los documentos y las líneas del mayor se insertan con `db_insert`, sin validación: lo que
se prueba es la copia, no el alta de una factura. Así corre igual en el sitio base de la
CI, que no tiene empresas.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.digital_invoice import reconciliation
from l10n_ve.digital_invoice.reconciliation import fill_missing_gl_bill_fields

BILL_NO = "12258"
BILL_CONTROL = "00-00195285"


def _document(
    doctype: str = "Sales Invoice",
    bill_no: str | None = BILL_NO,
    bill_control: str | None = BILL_CONTROL,
    docstatus: int = 1,
) -> str:
    """Un documento con su número fiscal, sin nada más."""
    doc = frappe.get_doc({
        "doctype": doctype,
        "name": f"ZZTEST-GLFILL-{frappe.generate_hash(length=8)}",
        "docstatus": docstatus,
        "bill_no": bill_no,
        "bill_control": bill_control,
    })
    doc.db_insert()
    return doc.name


def _gl_line(
    voucher_no: str,
    voucher_type: str = "Sales Invoice",
    bill_no: str | None = None,
    bill_control: str | None = None,
    is_cancelled: int = 0,
) -> str:
    """Una línea del mayor del comprobante, por defecto sin número."""
    gle = frappe.get_doc({
        "doctype": "GL Entry",
        "voucher_type": voucher_type,
        "voucher_no": voucher_no,
        "account": "ZZTEST cuenta",
        "posting_date": "2026-08-04",
        "debit": 100,
        "credit": 0,
        "is_cancelled": is_cancelled,
        "bill_no": bill_no,
        "bill_control": bill_control,
    })
    gle.db_insert()
    return gle.name


def _fields(gl_name: str) -> tuple[str | None, str | None]:
    row = frappe.db.get_value("GL Entry", gl_name, ["bill_no", "bill_control"], as_dict=True)
    return row.bill_no, row.bill_control


class TestFillMissingGlBillFields(FrappeTestCase):
    def setUp(self):
        self.addCleanup(frappe.db.rollback)
        patcher = patch.object(reconciliation.frappe, "log_error")
        self.log_error = patcher.start()
        self.addCleanup(patcher.stop)

    def test_fills_empty_gl_lines_from_the_document(self):
        invoice = _document()
        lines = [_gl_line(invoice), _gl_line(invoice)]

        filled = fill_missing_gl_bill_fields()

        self.assertIn(f"Sales Invoice {invoice}", filled)
        for line in lines:
            self.assertEqual(_fields(line), (BILL_NO, BILL_CONTROL))

    def test_never_overwrites_a_number_already_in_the_ledger(self):
        """Un número distinto en el mayor es una divergencia: tiene que verse, no taparse."""
        invoice = _document()
        line = _gl_line(invoice, bill_no="999")

        fill_missing_gl_bill_fields()

        # El control faltaba y se rellena; el número estaba y se respeta.
        self.assertEqual(_fields(line), ("999", BILL_CONTROL))

    def test_ignores_cancelled_gl_lines(self):
        invoice = _document()
        line = _gl_line(invoice, is_cancelled=1)

        fill_missing_gl_bill_fields()

        self.assertEqual(_fields(line), (None, None))

    def test_ignores_documents_that_are_not_submitted(self):
        for docstatus in (0, 2):
            with self.subTest(docstatus=docstatus):
                document = _document(docstatus=docstatus)
                line = _gl_line(document)

                filled = fill_missing_gl_bill_fields()

                self.assertNotIn(f"Sales Invoice {document}", filled)
                self.assertEqual(_fields(line), (None, None))

    def test_a_document_without_number_leaves_the_line_as_it_is(self):
        document = _document(bill_no=None, bill_control=None)
        line = _gl_line(document)

        filled = fill_missing_gl_bill_fields()

        self.assertNotIn(f"Sales Invoice {document}", filled)
        self.assertEqual(_fields(line), (None, None))

    def test_covers_purchase_invoices_too(self):
        """El parche de junio cubría seis tipos; la red cubre los mismos."""
        purchase = _document(doctype="Purchase Invoice", bill_no="A-77", bill_control="00-555")
        line = _gl_line(purchase, voucher_type="Purchase Invoice")

        filled = fill_missing_gl_bill_fields()

        self.assertIn(f"Purchase Invoice {purchase}", filled)
        self.assertEqual(_fields(line), ("A-77", "00-555"))

    def test_logs_the_vouchers_it_had_to_fill(self):
        """Si la red tuvo que actuar, la copia al emitir falló: eso tiene que quedar a la vista."""
        invoice = _document()
        _gl_line(invoice)

        fill_missing_gl_bill_fields()

        self.log_error.assert_called_once()
        self.assertIn(f"Sales Invoice {invoice}", self.log_error.call_args.kwargs["message"])

    def test_second_run_finds_nothing_and_logs_nothing(self):
        invoice = _document()
        _gl_line(invoice)
        fill_missing_gl_bill_fields()
        self.log_error.reset_mock()

        self.assertEqual(fill_missing_gl_bill_fields(), [])
        self.log_error.assert_not_called()
