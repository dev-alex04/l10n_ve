# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TFHKANotificationRecipient(Document):
	"""Una dirección de correo del aviso diario de documentos no enviados a HKA.

	La validación de la tabla vive en el padre (TFHKA Settings): necesita ver
	todas las filas juntas para detectar duplicados.
	"""

	pass
