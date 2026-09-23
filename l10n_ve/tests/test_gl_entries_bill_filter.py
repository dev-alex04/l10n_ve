# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Tests del filtro "Solo facturas con N° de control y factura" del Libro Mayor.

En la pantalla viene desmarcado: es la vista fiscal y se marca a mano. El servidor, si la
petición no lo trae, devuelve todo (así lo llaman otros reportes, exportaciones y los botones
«Libro mayor» de la factura y del cliente).

Suite 100% unittest + mocks (sin BD ni FrappeTestCase): `frappe.db` se sustituye por
un MagicMock durante cada caso, así que la suite corre con
`python -m unittest l10n_ve.tests.test_gl_entries_bill_filter` sin site levantado.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.patches.reports import general_ledger as gl_patch

_PATCH_PATH = "l10n_ve.patches.reports.general_ledger"
_ERPNEXT_GL = "erpnext.accounts.report.general_ledger.general_ledger"

_FILTERS_ON = {
    "company": "Galanet Solution C.A.",
    "from_date": "2026-07-01",
    "to_date": "2026-07-31",
    "only_invoices_with_bill_no_control": 1,
}


def _entry(voucher_no, bill_no="", bill_control="", debit=0, credit=0,
           voucher_type="Sales Invoice", posting_date="2026-07-15", is_opening="No"):
    """Fila estilo as_dict=True de las que devuelve el SELECT sobre tabGL Entry."""
    return {
        "voucher_type": voucher_type,
        "voucher_no": voucher_no,
        "bill_no": bill_no,
        "bill_control": bill_control,
        "posting_date": posting_date,
        "is_opening": is_opening,
        "debit": debit,
        "credit": credit,
    }


class TestGlEntriesBillFilter(unittest.TestCase):
    """custom_get_gl_entries: filtrado atómico por comprobante y fail-open."""

    def _run(self, entries, filters=None, docs=None, get_meta_error=None):
        """Ejecuta custom_get_gl_entries con la BD y los metadatos mockeados.

        `docs` son las filas que devolvería frappe.get_all sobre el documento cabecera.
        `get_meta_error` fuerza la excepción que dispara el camino de fail-open.
        """
        meta_kwargs = (
            {"side_effect": get_meta_error} if get_meta_error else {"return_value": MagicMock()}
        )

        with patch.object(frappe, "db", MagicMock(sql=MagicMock(return_value=entries))), \
             patch(f"{_ERPNEXT_GL}.get_conditions", return_value=""), \
             patch(f"{_PATCH_PATH}.get_currency", return_value={}), \
             patch.object(frappe, "get_meta", **meta_kwargs) as mock_meta, \
             patch.object(frappe, "get_all", return_value=docs or []), \
             patch.object(frappe, "log_error") as mock_log_error:
            if not get_meta_error:
                mock_meta.return_value.has_field.return_value = True
            result = gl_patch.custom_get_gl_entries(frappe._dict(filters or _FILTERS_ON), [])

        return result, mock_log_error

    def assertBalanced(self, entries):
        """El conjunto devuelto debe seguir cuadrando debe = haber."""
        debit = sum(e["debit"] for e in entries)
        credit = sum(e["credit"] for e in entries)
        self.assertEqual(debit, credit, "el filtro dejó el Mayor descuadrado")

    def test_report_screen_leaves_the_box_unchecked_by_default(self):
        """Marcada por defecto oculta la factura ENTERA en todo lo que abre el mayor sin mandar
        la casilla: el botón «Libro mayor» de una factura sin emitir abría el reporte vacío y el
        del cliente la sacaba de su estado de cuenta (medido el 23-sep-2026 sobre
        ACC-SINV-2026-22532: 3 filas → 0, y 4 → 3). Va desmarcada; la vista fiscal se pide."""
        import pathlib
        import re

        js = (pathlib.Path(gl_patch.__file__).parents[2] / "public" / "js" / "report"
              / "general_ledger.js").read_text(encoding="utf-8")
        bloque = re.search(
            r'fieldname:\s*"only_invoices_with_bill_no_control".*?\}', js, re.DOTALL
        )
        self.assertIsNotNone(bloque, "la casilla no está definida en general_ledger.js")
        self.assertRegex(bloque.group(0), r"default:\s*0\b")

    def test_filter_off_returns_all_entries_by_default(self):
        """Con la casilla apagada (default 0) no se descarta ningún asiento."""
        entries = [
            _entry("ACC-SINV-001", debit=100),
            _entry("ACC-SINV-001", credit=100),
        ]
        filters = {"company": "Galanet", "only_invoices_with_bill_no_control": 0}

        result, _ = self._run(entries, filters=filters)

        self.assertEqual(len(result), 2)

    def test_incomplete_voucher_is_dropped_whole(self):
        """Regresión ACC-SINV-2026-00233: si falta el dato en una línea, cae el comprobante entero.

        Reproduce la forma real que descuadraba el Mayor: el documento cabecera no tiene
        los números, 3 de 4 líneas del GL sí los traen y la de redondeo no. Antes se
        borraba solo esa línea y el comprobante quedaba partido.
        """
        entries = [
            _entry("SI-OK", bill_no="00100", bill_control="00100", debit=100),
            _entry("SI-OK", bill_no="00100", bill_control="00100", credit=100),
            _entry("SI-SPLIT", bill_no="00061", bill_control="00061", debit=8399.75),
            _entry("SI-SPLIT", bill_no="00061", bill_control="00061", credit=8399.74),
            _entry("SI-SPLIT", credit=0.01),
        ]

        result, _ = self._run(entries)

        self.assertEqual({e["voucher_no"] for e in result}, {"SI-OK"})
        self.assertEqual(len(result), 2)
        self.assertBalanced(result)

    def test_source_doc_fills_missing_numbers_and_keeps_voucher(self):
        """Si el documento cabecera tiene los números, se rellenan y el comprobante se conserva."""
        entries = [
            _entry("SI-FILL", debit=100),
            _entry("SI-FILL", credit=100),
        ]
        docs = [frappe._dict({"name": "SI-FILL", "bill_no": "00200", "bill_control": "00300"})]

        result, _ = self._run(entries, docs=docs)

        self.assertEqual(len(result), 2)
        self.assertBalanced(result)
        for entry in result:
            self.assertEqual(entry["bill_no"], "00200")
            self.assertEqual(entry["bill_control"], "00300")

    def test_opening_entries_and_prior_dates_never_dropped(self):
        """Apertura (is_opening=Yes) y asientos anteriores a from_date quedan exentos."""
        entries = [
            _entry("SI-OPENING", debit=500, is_opening="Yes"),
            _entry("SI-PRIOR", debit=300, posting_date="2026-06-15"),
        ]

        result, _ = self._run(entries)

        self.assertEqual(len(result), 2)

    def test_fail_open_on_exception(self):
        """Ante un error de metadatos/BD no se oculta nada y queda registrado en el log."""
        entries = [_entry("SI-ERR", debit=100, credit=100)]

        result, mock_log_error = self._run(entries, get_meta_error=RuntimeError("DB Timeout"))

        self.assertEqual(len(result), 1)
        mock_log_error.assert_called_once()

    def test_non_invoice_vouchers_are_never_evaluated(self):
        """Payment Entry / Journal Entry pasan intactos aunque no tengan números fiscales."""
        entries = [
            _entry("PE-001", voucher_type="Payment Entry", debit=100),
            _entry("JV-001", voucher_type="Journal Entry", credit=100),
        ]

        result, _ = self._run(entries)

        self.assertEqual(len(result), 2)
        self.assertBalanced(result)


if __name__ == "__main__":
    unittest.main()
