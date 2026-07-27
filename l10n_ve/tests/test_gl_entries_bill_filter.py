import unittest
from unittest.mock import patch, MagicMock

import logging
import frappe
import frappe.utils.logger

def dummy_get_logger(*args, **kwargs):
    return logging.getLogger('dummy')

frappe.utils.logger.get_logger = dummy_get_logger
frappe.logger = dummy_get_logger

from l10n_ve.patches.reports import general_ledger as gl_patch

_PATCH_PATH = "l10n_ve.patches.reports.general_ledger"


class TestGlEntriesBillFilter(unittest.TestCase):
    """Pruebas del filtro opt-in de facturas sin número de control/factura en Libro Mayor."""

    def setUp(self):
        frappe.init(site='PRUEBAS', sites_path='/home/usuario2/frappe-bench/sites')
        frappe.connect()
        frappe.set_user("Administrator")
        self.filters = frappe._dict({
            "company": "Galanet Solution C.A.",
            "from_date": "2026-07-01",
            "to_date": "2026-07-31",
            "only_invoices_with_bill_no_control": 1,
        })

    def tearDown(self):
        try:
            frappe.destroy()
        except Exception:
            pass

    def test_filter_off_returns_all_entries_by_default(self):
        """Si el filtro opt-in está apagado (default 0), no se descarta ningún asiento."""
        filters = frappe._dict({"company": "Galanet", "only_invoices_with_bill_no_control": 0})
        entries = [
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "ACC-SINV-001",
                "bill_no": "",
                "bill_control": "",
                "debit": 100,
                "credit": 0,
            },
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "ACC-SINV-001",
                "bill_no": "",
                "bill_control": "",
                "debit": 0,
                "credit": 100,
            },
        ]
        with patch("erpnext.accounts.report.general_ledger.general_ledger.get_conditions", return_value=""), \
             patch.object(frappe.db, "sql", return_value=entries), \
             patch(f"{_PATCH_PATH}.get_currency", return_value={}):
            res = gl_patch.custom_get_gl_entries(filters, [])
        self.assertEqual(len(res), 2)

    def test_voucher_atomic_filtering_preserves_double_entry(self):
        """Si un comprobante está incompleto, se descartan TODAS sus líneas (partida doble)."""
        entries = [
            # Comprobante 1 completo
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "SI-OK",
                "bill_no": "00100",
                "bill_control": "00100",
                "posting_date": "2026-07-15",
                "debit": 100,
                "credit": 0,
            },
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "SI-OK",
                "bill_no": "00100",
                "bill_control": "00100",
                "posting_date": "2026-07-15",
                "debit": 0,
                "credit": 100,
            },
            # Comprobante 2 incompleto (una fila tiene bill_no, otra no)
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "SI-INC",
                "bill_no": "00101",
                "bill_control": "00101",
                "posting_date": "2026-07-15",
                "debit": 50,
                "credit": 0,
            },
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "SI-INC",
                "bill_no": "",
                "bill_control": "",
                "posting_date": "2026-07-15",
                "debit": 0,
                "credit": 50,
            },
        ]

        with patch("erpnext.accounts.report.general_ledger.general_ledger.get_conditions", return_value=""), \
             patch.object(frappe.db, "sql", return_value=entries), \
             patch(f"{_PATCH_PATH}.get_currency", return_value={}), \
             patch("frappe.get_meta") as mock_meta, \
             patch("frappe.get_all", return_value=[]):
            mock_meta.return_value.has_field.return_value = True
            res = gl_patch.custom_get_gl_entries(self.filters, [])

        # SI-OK debe sobrevivir completo (2 líneas)
        # SI-INC debe descartarse COMPLETO (0 líneas), evitando partir el comprobante
        self.assertEqual(len(res), 2)
        vouchers = [r["voucher_no"] for r in res]
        self.assertEqual(set(vouchers), {"SI-OK"})

    def test_opening_entries_and_prior_dates_never_dropped(self):
        """Entradas de apertura (is_opening=Yes o posting_date < from_date) no se descartan."""
        entries = [
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "SI-OPENING",
                "bill_no": "",
                "bill_control": "",
                "is_opening": "Yes",
                "posting_date": "2026-07-01",
                "debit": 500,
                "credit": 0,
            },
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "SI-PRIOR",
                "bill_no": "",
                "bill_control": "",
                "is_opening": "No",
                "posting_date": "2026-06-15",  # Anterior a from_date 2026-07-01
                "debit": 300,
                "credit": 0,
            },
        ]

        with patch("erpnext.accounts.report.general_ledger.general_ledger.get_conditions", return_value=""), \
             patch.object(frappe.db, "sql", return_value=entries), \
             patch(f"{_PATCH_PATH}.get_currency", return_value={}), \
             patch("frappe.get_meta") as mock_meta, \
             patch("frappe.get_all", return_value=[]):
            mock_meta.return_value.has_field.return_value = True
            res = gl_patch.custom_get_gl_entries(self.filters, [])

        # Ambas entradas deben preservarse para proteger los saldos iniciales de apertura
        self.assertEqual(len(res), 2)

    def test_fail_open_on_exception(self):
        """Si ocurre un error consultando metadata/BD, debe fallar abierto (no borrar datos)."""
        entries = [
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": "SI-ERR",
                "bill_no": "",
                "bill_control": "",
                "posting_date": "2026-07-15",
                "debit": 100,
                "credit": 100,
            }
        ]

        with patch("erpnext.accounts.report.general_ledger.general_ledger.get_conditions", return_value=""), \
             patch.object(frappe.db, "sql", return_value=entries), \
             patch(f"{_PATCH_PATH}.get_currency", return_value={}), \
             patch("frappe.get_meta", side_effect=RuntimeError("DB Timeout")), \
             patch("frappe.log_error") as mock_log_error:
            res = gl_patch.custom_get_gl_entries(self.filters, [])

        self.assertEqual(len(res), 1)
        mock_log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
