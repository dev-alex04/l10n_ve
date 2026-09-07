# Copyright (c) 2026, Domina Software and Contributors
# For license information, please see license.txt

"""El registro compartido de una parte: lo que los dos lados de la integración esperan.

Se fija lo que se mudó desde `domina_isp_contractor` sin cambiar de conducta --el corte de
la dirección en dos líneas, los tipos de documento por letra, el texto de lo que falta-- y
lo que se agregó al compartirlo: que la dirección de una parte se actualice en vez de
duplicarse, y que funcione sobre un Lead, que es lo que tiene el ISP antes de convertir.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.party_registration import (
	ADDRESS_LINE_MAX_LENGTH,
	address_text,
	build_party_address,
	document_types_for,
	letter_choices,
	missing_contact_text,
	normalized_tax_id,
	party_address,
	split_address_line,
	split_document,
)

_MARCA = "ZZTEST-PARTYREG"


class TestIdentidad(FrappeTestCase):
	def test_el_documento_se_normaliza_con_la_letra_pegada(self):
		self.assertEqual(normalized_tax_id("v", "12.345.678"), "V12345678")
		self.assertEqual(split_document("J-40.123.456-7"), ("J", "401234567"))

	def test_una_empresa_solo_tiene_rif(self):
		self.assertEqual(document_types_for("J"), ["RIF"])
		self.assertEqual(document_types_for("V")[0], "Cedula", "la cédula va primero: es la que acierta casi siempre")
		self.assertEqual(document_types_for("?"), [])

	def test_la_tabla_de_letras_trae_los_rangos_para_el_navegador(self):
		por_letra = {c["letter"]: c for c in letter_choices()}

		self.assertIn("V", por_letra)
		self.assertIn("RIF", por_letra["V"]["document_ranges"])
		self.assertEqual(por_letra["J"]["customer_type"], "Company")

	def test_lo_que_falta_se_dice_con_los_nombres_de_aca(self):
		texto = missing_contact_text({"customer_name": "X", "email_id": "x@y.z"})

		self.assertIn("el RIF", texto)
		self.assertIn("el teléfono", texto)
		self.assertNotIn("correo", texto)
		self.assertEqual(missing_contact_text({"customer_name": "X", "tax_id": "V1", "mobile_no": "0", "email_id": "a@b.c"}), "")


class TestDireccion(FrappeTestCase):
	def setUp(self):
		self._borrar_residuos()
		self.addCleanup(self._borrar_residuos)

		self.lead = frappe.get_doc({"doctype": "Lead", "lead_name": f"{_MARCA} Prospecto"}).insert(ignore_permissions=True)

	def _borrar_residuos(self):
		for lead in frappe.get_all("Lead", filters={"lead_name": ["like", f"{_MARCA}%"]}, pluck="name"):
			for direccion in frappe.get_all(
				"Dynamic Link", filters={"parenttype": "Address", "link_doctype": "Lead", "link_name": lead}, pluck="parent"
			):
				frappe.delete_doc("Address", direccion, force=True, ignore_permissions=True)

			# ERPNext le crea un Contact al Lead, y en los sitios con el chat (ClefinCode) ese
			# Contact gana un perfil que impide borrarlo, y con él al Lead. Se limpia primero.
			for contacto in frappe.get_all(
				"Dynamic Link", filters={"parenttype": "Contact", "link_doctype": "Lead", "link_name": lead}, pluck="parent"
			):
				if frappe.db.exists("DocType", "ClefinCode Chat Profile"):
					for perfil in frappe.get_all("ClefinCode Chat Profile", filters={"name": ["like", f"{_MARCA}%"]}, pluck="name"):
						frappe.delete_doc("ClefinCode Chat Profile", perfil, force=True, ignore_permissions=True)

				frappe.delete_doc("Contact", contacto, force=True, ignore_permissions=True)

			frappe.delete_doc("Lead", lead, force=True, ignore_permissions=True)

	def _direccion(self, **extra):
		# Con `l10n_ve`, estado, ciudad y municipio son enlaces obligatorios: se toman del
		# catálogo del sitio, no se inventan.
		estado = frappe.get_all("VE State", pluck="name", limit=1)[0]
		valores = {
			"address_line1": "Calle 1, casa 2",
			"address_type": "Billing",
			"country": frappe.db.get_default("country"),
			"state": estado,
			"city": frappe.get_value("VE City", {"state": estado}, "name"),
			"county": frappe.get_value("VE Municipality", {"state": estado}, "name"),
		}
		valores.update(extra)

		return valores

	def test_la_direccion_larga_se_parte_por_palabras(self):
		texto = " ".join(["palabra"] * 40)
		primera, segunda = split_address_line(texto)

		self.assertLessEqual(len(primera), ADDRESS_LINE_MAX_LENGTH)
		self.assertTrue(segunda)
		self.assertFalse(primera.endswith("pal"), "no se corta una palabra por la mitad")

	def test_la_direccion_se_crea_y_se_enlaza_al_lead(self):
		nombre = build_party_address("Lead", self.lead.name, self.lead.lead_name, self._direccion())

		self.assertTrue(nombre)
		guardada = party_address("Lead", self.lead.name)
		self.assertEqual(guardada["name"], nombre)
		self.assertEqual(address_text(guardada), "Calle 1, casa 2")

	def test_la_segunda_vez_se_actualiza_en_vez_de_duplicar(self):
		primera = build_party_address("Lead", self.lead.name, self.lead.lead_name, self._direccion())
		segunda = build_party_address("Lead", self.lead.name, self.lead.lead_name, self._direccion(address_line1="Otra calle 9"))

		self.assertEqual(primera, segunda)
		self.assertEqual(frappe.db.get_value("Address", primera, "address_line1"), "Otra calle 9")
		self.assertEqual(
			frappe.db.count("Dynamic Link", {"parenttype": "Address", "link_doctype": "Lead", "link_name": self.lead.name}), 1
		)

	def test_sin_direccion_no_se_crea_nada(self):
		self.assertIsNone(build_party_address("Lead", self.lead.name, self.lead.lead_name, {"address_line1": "  "}))
		self.assertIsNone(party_address("Lead", self.lead.name))
