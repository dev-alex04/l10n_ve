# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de los avisos de retenciones pendientes.

Requerimiento (Aurelys Torres / Galanet, correo "Requerimiento- avisos
Retenciones Caracas" del 29-07-2026; tarea P101 del control de peticiones): el
aviso sale en 3 momentos — el mismo día en que se emite la factura fiscal, al
tercer día de emitida, y en una fecha tope única que es el 22 de cada mes.

Cubre:
- _fetch_customer_emails_bulk: separa el email_id multi-dirección y deduplica
  sin distinguir mayúsculas. Frappe no parte por coma dentro de un elemento de
  la lista de recipients, así que una dirección compuesta rebota en el RCPT TO.
- trigger_retention_reminder_on_invoice_emission: filtros previos al encolado y
  enqueue_after_commit (el job no puede correr antes del commit del submit).
- Los dos cron: la fecha tope es el 22, la corrida diaria no pisa al
  consolidado, y el barrido pesado no se queda en la cola default.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve import tasks


def _invoice(name: str = "ACC-SINV-2026-00001"):
    """Stub mínimo del doc que reciben el hook y _handle_hka_response."""
    return frappe._dict(doctype="Sales Invoice", name=name)


class TestFetchCustomerEmailsBulk(FrappeTestCase):
    """El prefetch en lote debe conservar la semántica de get_email_list."""

    def test_empty_input_skips_query(self) -> None:
        """Lista vacía → sin query (un IN () es un 1064 en PyMySQL)."""
        with patch("frappe.db.sql") as mock_sql:
            self.assertEqual(tasks._fetch_customer_emails_bulk([]), {})
            mock_sql.assert_not_called()

    def test_splits_comma_separated_email_id(self) -> None:
        """email_id con varias direcciones → un destinatario por dirección."""
        rows = [frappe._dict(name="DATINVOZ", email_id="uno@x.com , dos@y.com")]

        with patch("frappe.db.sql", return_value=rows):
            result = tasks._fetch_customer_emails_bulk(["DATINVOZ"])

        self.assertEqual(result, {"DATINVOZ": ["uno@x.com", "dos@y.com"]})

    def test_dedupes_case_insensitively(self) -> None:
        """La misma casilla en distinta caja no se manda dos veces."""
        rows = [frappe._dict(name="C1", email_id="Correo@X.com, correo@x.com")]

        with patch("frappe.db.sql", return_value=rows):
            result = tasks._fetch_customer_emails_bulk(["C1"])

        self.assertEqual(result, {"C1": ["Correo@X.com"]})

    def test_customer_without_usable_email_is_omitted(self) -> None:
        """email_id con solo separadores → el cliente no queda en el mapa."""
        rows = [frappe._dict(name="C1", email_id="  ,  ")]

        with patch("frappe.db.sql", return_value=rows):
            result = tasks._fetch_customer_emails_bulk(["C1"])

        self.assertEqual(result, {})


class TestTriggerRetentionReminder(FrappeTestCase):
    """Primer aviso: qué se encola al emitir y con qué garantías."""

    def setUp(self) -> None:
        super().setUp()
        settings = patch(
            "l10n_ve.tasks.get_l10n_ve_settings", return_value={"is_production_mode": 1}
        )
        settings.start()
        self.addCleanup(settings.stop)

        self.fiscal = frappe._dict(
            bill_no="00012345", bill_control="00-6789", customer="CLIENTE-001"
        )

    def test_enqueues_after_commit(self) -> None:
        """El job espera al commit: antes, la factura no está ni en docstatus=1."""
        with (
            patch("frappe.db.get_value", return_value=self.fiscal),
            patch("l10n_ve.tasks._customer_needs_retention_vouchers", return_value=True),
            patch("l10n_ve.tasks._invoice_has_retention_lines", return_value=True),
            patch("frappe.enqueue") as mock_enqueue,
        ):
            tasks.trigger_retention_reminder_on_invoice_emission(_invoice())

        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertTrue(kwargs["enqueue_after_commit"])
        self.assertEqual(kwargs["sales_invoice"], "ACC-SINV-2026-00001")

    def test_skips_without_fiscal_numbers(self) -> None:
        """Sin bill_no/bill_control todavía no hay factura fiscal que avisar."""
        sin_fiscal = frappe._dict(bill_no=None, bill_control=None, customer="CLIENTE-001")

        with (
            patch("frappe.db.get_value", return_value=sin_fiscal),
            patch("frappe.enqueue") as mock_enqueue,
        ):
            tasks.trigger_retention_reminder_on_invoice_emission(_invoice())

        mock_enqueue.assert_not_called()

    def test_skips_when_customer_has_no_retentions(self) -> None:
        """Cliente que no retiene → no se encola nada."""
        with (
            patch("frappe.db.get_value", return_value=self.fiscal),
            patch("l10n_ve.tasks._customer_needs_retention_vouchers", return_value=False),
            patch("frappe.enqueue") as mock_enqueue,
        ):
            tasks.trigger_retention_reminder_on_invoice_emission(_invoice())

        mock_enqueue.assert_not_called()

    def test_skips_when_invoice_has_no_retention_lines(self) -> None:
        """Factura sin líneas de IVA/ISLR → no aplica el aviso."""
        with (
            patch("frappe.db.get_value", return_value=self.fiscal),
            patch("l10n_ve.tasks._customer_needs_retention_vouchers", return_value=True),
            patch("l10n_ve.tasks._invoice_has_retention_lines", return_value=False),
            patch("frappe.enqueue") as mock_enqueue,
        ):
            tasks.trigger_retention_reminder_on_invoice_emission(_invoice())

        mock_enqueue.assert_not_called()

    def test_skips_before_touching_db_when_settings_missing(self) -> None:
        """Sitio sin l10n_ve_settings: ni consulta la factura."""
        with (
            patch("l10n_ve.tasks.get_l10n_ve_settings", return_value=None),
            patch("frappe.db.get_value") as mock_get_value,
            patch("frappe.enqueue") as mock_enqueue,
        ):
            tasks.trigger_retention_reminder_on_invoice_emission(_invoice())

        mock_get_value.assert_not_called()
        mock_enqueue.assert_not_called()

    def test_ignores_other_doctypes(self) -> None:
        """_handle_hka_response también emite NC/ND; solo aplica a facturas."""
        nota = frappe._dict(doctype="VE Sales Credit Note", name="VE-NC-2026-00001")

        with patch("frappe.enqueue") as mock_enqueue:
            tasks.trigger_retention_reminder_on_invoice_emission(nota)

        mock_enqueue.assert_not_called()


class TestRetentionReminderSchedule(FrappeTestCase):
    """Segundo y tercer aviso: los dos cron."""

    def test_deadline_day_matches_requirement(self) -> None:
        """El requerimiento fija el 22 como fecha tope única."""
        self.assertEqual(tasks.RETENTION_REMINDER_DEADLINE_DAY, 22)

    def test_daily_cron_looks_back_three_days(self) -> None:
        with (
            patch("l10n_ve.tasks.nowdate", return_value="2026-08-10"),
            patch("l10n_ve.tasks.send_missing_retentions_reminders") as mock_send,
        ):
            tasks.send_3_days_retention_reminders()

        mock_send.assert_called_once_with(days_old=3)

    def test_daily_cron_skips_on_deadline_day(self) -> None:
        """El 22 sale el consolidado; no se manda además el individual."""
        with (
            patch("l10n_ve.tasks.nowdate", return_value="2026-08-22"),
            patch("l10n_ve.tasks.send_missing_retentions_reminders") as mock_send,
        ):
            tasks.send_3_days_retention_reminders()

        mock_send.assert_not_called()

    def test_monthly_pass_leaves_the_default_queue(self) -> None:
        """El barrido completo no cabe en los 300 s del cron del scheduler."""
        with patch("frappe.enqueue") as mock_enqueue:
            tasks.send_monthly_deadline_retention_reminders()

        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs["queue"], "long")
        self.assertGreater(kwargs["timeout"], 300)


class TestRetentionReminderHooks(FrappeTestCase):
    """El cableado del scheduler debe reflejar las 3 fechas pedidas."""

    def test_cron_entries_match_requirement(self) -> None:
        from l10n_ve import hooks

        cron = hooks.scheduler_events["cron"]
        self.assertIn("l10n_ve.tasks.send_3_days_retention_reminders", cron["0 8 * * *"])
        self.assertIn(
            "l10n_ve.tasks.send_monthly_deadline_retention_reminders", cron["0 8 22 * *"]
        )

    def test_submit_hook_is_registered(self) -> None:
        from l10n_ve import hooks

        self.assertEqual(
            hooks.doc_events["Sales Invoice"]["on_submit"],
            "l10n_ve.tasks.on_sales_invoice_submit",
        )
