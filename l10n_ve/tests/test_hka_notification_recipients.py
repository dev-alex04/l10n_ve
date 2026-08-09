# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de la tabla de destinatarios del aviso diario de documentos no enviados a HKA
(TFHKA Settings → notification_recipients).

Lo que se protege es una trampa concreta: ``frappe.sendmail`` **no separa las comas**
dentro de un elemento de la lista de destinatarios. Una fila con ``a@x.com, b@y.com``
se toma como UNA dirección inválida y el correo rebota en silencio — el peor final
posible para un aviso de alerta, porque nadie se entera de que dejó de llegar.

No se toca la base: se muta el Single en memoria y se llama a validate().
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestHkaNotificationRecipients(FrappeTestCase):
	def setUp(self) -> None:
		self.settings = frappe.get_doc("TFHKA Settings")
		self.settings.notification_recipients = []

	def _set(self, emails: list[str]) -> None:
		self.settings.notification_recipients = []
		for email in emails:
			self.settings.append("notification_recipients", {"email": email})

	def test_single_address_is_accepted(self):
		self._set(["conta@galanet.com.ve"])
		self.settings.validate()
		self.assertEqual(
			self.settings.get_notification_recipients(), ["conta@galanet.com.ve"]
		)

	def test_surrounding_whitespace_is_trimmed(self):
		self._set(["  conta@galanet.com.ve  "])
		self.settings.validate()
		self.assertEqual(
			self.settings.get_notification_recipients(), ["conta@galanet.com.ve"]
		)

	def test_several_rows_are_accepted(self):
		self._set(["a@x.com", "b@y.com"])
		self.settings.validate()
		self.assertEqual(self.settings.get_notification_recipients(), ["a@x.com", "b@y.com"])

	def test_comma_in_one_row_is_rejected(self):
		"""sendmail no partiría esa fila: sería un destinatario inválido."""
		self._set(["a@x.com, b@y.com"])
		with self.assertRaises(frappe.ValidationError):
			self.settings.validate()

	def test_semicolon_in_one_row_is_rejected(self):
		self._set(["a@x.com; b@y.com"])
		with self.assertRaises(frappe.ValidationError):
			self.settings.validate()

	def test_duplicate_is_rejected_ignoring_case(self):
		"""Se rechaza en vez de deduplicar: en configuración el error debe verse."""
		self._set(["a@x.com", "A@X.com"])
		with self.assertRaises(frappe.ValidationError):
			self.settings.validate()

	def test_empty_table_yields_no_recipients(self):
		"""Sin destinatarios la tarea no debe enviar nada; acá se garantiza la lista vacía."""
		self._set([])
		self.settings.validate()
		self.assertEqual(self.settings.get_notification_recipients(), [])

	def test_blank_rows_are_ignored(self):
		self._set(["   ", "a@x.com"])
		self.settings.validate()
		self.assertEqual(self.settings.get_notification_recipients(), ["a@x.com"])
