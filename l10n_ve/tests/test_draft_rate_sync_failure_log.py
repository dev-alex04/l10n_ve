# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests del registro agregado de fallos al alinear la tasa BCV de borradores.

Regresión de la firma "BCV: no se pudo alinear la tasa de ACC-SINV-*" (227
entradas entre el 4 y el 13 de agosto de 2026): **una sola** factura atascada
—ACC-SINV-2026-21533, cuyo cronograma de pago tiene el vencimiento antes de la
fecha de emisión, así que ERPNext nunca la deja guardar— escribía una entrada
de Error Log por cada corrida del job. La factura no se puede arreglar desde
acá (es dato), pero el job no debe reportarla una y otra vez ni ahogar al resto
del registro: se acumulan los fallos y se escribe UNO por corrida.
"""

import unittest
from unittest.mock import patch

import frappe

import l10n_ve.tasks as tasks


class _StubInvoice:
    """Borrador que acepta o rechaza el save según se pida."""

    def __init__(self, name, falla):
        self.name = name
        self.docstatus = 0
        self.conversion_rate = 0
        self.plc_conversion_rate = 0
        self._falla = falla

    def save(self, ignore_permissions=False):
        if self._falla:
            raise frappe.ValidationError(
                "Due Date cannot be before Posting / Supplier Invoice Date"
            )


class TestDraftRateSyncFailureLog(unittest.TestCase):
    def setUp(self):
        self.errores = []
        self.drafts = [
            {"name": f"ACC-SINV-2026-{i:05d}", "customer": f"CUST-{i}",
             "posting_date": "2026-08-03", "conversion_rate": 700.0, "currency": "USD"}
            for i in range(1, 6)
        ]
        self.fallan = set()

        def _log_error(title=None, message=None, **kwargs):
            # El job llama posicionalmente: log_error(title, message).
            self.errores.append({"title": title, "message": message})

        def _get_value(doctype, filters, fieldname=None, **kwargs):
            # La tasa oficial del mes: distinta de la del borrador para que entre
            # al camino de actualización.
            return 746.6297

        def _get_doc(doctype, name):
            return _StubInvoice(name, falla=name in self.fallan)

        def _get_single_value(doctype, fieldname):
            if fieldname == "default_currency":
                return "VEF"
            if fieldname == "cutoff_date":
                return "2026-01-01"
            return None

        db = frappe._dict(
            get_single_value=_get_single_value,
            get_value=_get_value,
            exists=lambda *a, **k: False,   # sin ISP Payment Entry en este site
            count=lambda *a, **k: 0,
            commit=lambda *a, **k: None,
        )

        parches = [
            patch.object(frappe, "log_error", side_effect=_log_error),
            patch.object(frappe, "get_doc", side_effect=_get_doc),
            patch.object(frappe, "get_all", side_effect=lambda *a, **k: [
                frappe._dict(d) for d in self.drafts]),
            patch.object(frappe, "db", db),
            # El job importa el helper adentro de la función: se parcha en origen.
            patch("l10n_ve.utils.utils.is_juridical_customer", return_value=False),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

    def _correr(self):
        return tasks.reconcile_draft_invoice_exchange_rates()

    @property
    def _logs_de_fallo(self):
        """Solo el agregado de fallos: el job también deja uno informativo con las
        facturas que SÍ alineó, y ese no cuenta acá."""
        return [e for e in self.errores if "no se pudo alinear" in (e["title"] or "")]

    def test_una_factura_atascada_deja_un_solo_error_log(self):
        """El caso real: 1 de 5 falla → 1 Error Log, no 1 por corrida y factura."""
        self.fallan = {self.drafts[2]["name"]}

        resultado = self._correr()

        self.assertEqual(len(self._logs_de_fallo), 1)
        self.assertEqual(resultado["failed"], 1)
        self.assertEqual(resultado["updated"], 4)

    def test_el_agregado_nombra_las_facturas_y_el_traceback(self):
        """El único log tiene que seguir sirviendo para diagnosticar."""
        self.fallan = {self.drafts[0]["name"], self.drafts[4]["name"]}

        self._correr()

        mensaje = self._logs_de_fallo[0]["message"]
        self.assertIn(self.drafts[0]["name"], mensaje)
        self.assertIn(self.drafts[4]["name"], mensaje)
        self.assertIn("Due Date cannot be before", mensaje)
        self.assertIn("Traceback del primer fallo", mensaje)

    def test_sin_fallos_no_hay_error_log_de_fallos(self):
        """Corrida limpia: solo el log informativo de las alineadas."""
        resultado = self._correr()

        self.assertEqual(self._logs_de_fallo, [])
        self.assertEqual(resultado["failed"], 0)
        self.assertEqual(resultado["updated"], 5)

    def test_el_detalle_se_topea_para_no_perder_el_traceback(self):
        """Con cientos de fallos se listan los primeros y se dice cuántos faltan."""
        self.drafts = [
            {"name": f"ACC-SINV-2026-{i:05d}", "customer": f"CUST-{i}",
             "posting_date": "2026-08-03", "conversion_rate": 700.0, "currency": "USD"}
            for i in range(1, 251)
        ]
        self.fallan = {d["name"] for d in self.drafts}

        self._correr()

        mensaje = self._logs_de_fallo[0]["message"]
        self.assertIn(f"… y {250 - tasks._RATE_SYNC_FAILURES_IN_LOG} más.", mensaje)
        self.assertIn("Traceback del primer fallo", mensaje)


if __name__ == "__main__":
    unittest.main()
