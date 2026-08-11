# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TFHKASettings(Document):
	def validate(self) -> None:
		self._validate_notification_recipients()

	def _validate_notification_recipients(self) -> None:
		"""Una dirección por fila, sin repetir.

		Lo de "una por fila" no es prolijidad: ``frappe.sendmail`` NO parte las comas
		dentro de un elemento de la lista de destinatarios, así que una fila con
		``a@x.com, b@y.com`` se trata como UNA dirección inválida y el correo rebota
		en silencio — justo lo contrario de lo que se busca con un aviso de alerta.

		Los duplicados se rechazan en vez de deduplicarse: en una tabla de
		configuración conviene que el error se vea, no que el sistema lo tape.
		"""
		vistos: dict[str, int] = {}

		for row in self.notification_recipients or []:
			email: str = (row.email or "").strip()
			row.email = email

			if not email:
				continue

			if "," in email or ";" in email:
				frappe.throw(
					f"Fila {row.idx}: coloque una sola dirección por fila. "
					f"El envío no separa direcciones dentro de una misma casilla, "
					f"así que «{email}» se tomaría como un destinatario inválido.",
					title="Destinatarios del aviso HKA",
				)

			clave: str = email.lower()
			if clave in vistos:
				frappe.throw(
					f"Fila {row.idx}: «{email}» ya está en la fila {vistos[clave]}.",
					title="Destinatarios del aviso HKA",
				)
			vistos[clave] = row.idx

	def get_notification_recipients(self) -> list[str]:
		"""Direcciones a las que enviar el aviso diario. Lista vacía si no hay ninguna."""
		return [
			(row.email or "").strip()
			for row in (self.notification_recipients or [])
			if (row.email or "").strip()
		]
