# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""La tasa BCV en el chat, con la regla de a quién le toca cada una.

Un usuario preguntó por la tasa y el asistente no supo contestar: no había ninguna
herramienta ni reporte que la diera, aunque el Panel de Control la muestra arriba de
todo —«Tasa de hoy (30-08-2026): Bs. 794,99 / USD»— y `l10n_ve` ya tiene la lógica.

La herramienta la ENVUELVE, no la rehace. Y devuelve las DOS tasas porque en Venezuela
la que lleva un documento depende de quién lo recibe:

    Jurídico (y gobierno, comunal, educativo) -> la de HOY
    Natural  (y extranjero, pasaporte)        -> la del 1° del mes en curso

Corren sin site.
"""

import unittest
from unittest.mock import MagicMock, patch

from l10n_ve.smart.tools import get_exchange_rate

MODULE = "l10n_ve.smart.tools"


class TestTasaDeCambio(unittest.TestCase):
	def _run(self, tasas, fila_real="2026-08-30", **kwargs):
		"""`frappe.db` se parchea en el módulo: sin site es un LocalProxy sin bindear."""
		db = MagicMock()
		db.get_value.return_value = fila_real
		# Dos parches de contexto, ninguno de lo que se mide: sin site, `flt` va a buscar
		# la precisión a System Settings y `nowdate` la zona horaria, y las dos mueren con
		# «NoneType has no get_value». `nowdate` se parchea en `frappe.utils` porque la
		# función la importa ahí adentro, no en el módulo.
		with patch(f"{MODULE}.frappe.db", db), \
			 patch("frappe.get_system_settings", return_value=2), \
			 patch("l10n_ve.utils.utils.get_exchange_rate", side_effect=lambda d, c: tasas.get(str(d), 0.0)), \
			 patch(f"{MODULE}.frappe.defaults.get_defaults", return_value={"currency": "VEF"}), \
			 patch("frappe.utils.nowdate", return_value="2026-08-30"):
			return get_exchange_rate(**kwargs)

	def test_devuelve_las_dos_tasas_porque_dependen_del_cliente(self):
		r = self._run({"2026-08-30": 794.9917, "2026-08-01": 748.7864})
		self.assertEqual(r["por_tipo_de_cliente"]["juridico"], 794.9917)
		self.assertEqual(r["por_tipo_de_cliente"]["natural"], 748.7864)

	def test_la_nota_dice_a_quien_le_toca_cada_una(self):
		"""«La tasa es X» sin decir a quién aplica es media respuesta."""
		r = self._run({"2026-08-30": 794.9917, "2026-08-01": 748.7864})
		self.assertIn("JURÍDICO", r["nota"])
		self.assertIn("NATURAL", r["nota"])
		self.assertIn("MES EN CURSO", r["nota"])

	def test_avisa_que_no_sirve_para_reexpresar_saldos(self):
		"""Cada documento guarda la tasa con la que salió."""
		r = self._run({"2026-08-30": 794.9917, "2026-08-01": 748.7864})
		self.assertIn("NO sirve para reexpresar", r["nota"])

	def test_una_fecha_sin_tasa_propia_se_declara(self):
		"""El lookup es permisivo y devuelve la vigente; presentarla como la del día
		pedido es el modo de fallar callado."""
		r = self._run({"2030-01-01": 794.9917}, fila_real="2026-08-31", date="2030-01-01")
		self.assertTrue(r["es_de_otro_dia"])
		self.assertEqual(r["fecha_real_de_la_tasa"], "2026-08-31")
		self.assertIn("es_de_otro_dia", r["nota"])

	def test_una_fecha_con_su_propia_tasa_no_se_marca(self):
		r = self._run({"2026-08-30": 794.9917, "2026-08-01": 748.7864})
		self.assertFalse(r["es_de_otro_dia"])

	def test_sin_ninguna_tasa_no_inventa_una(self):
		"""Una tasa inventada sale impresa en un documento fiscal."""
		r = self._run({}, date="2026-08-30")
		self.assertIsNone(r["tasa"])
		self.assertIn("NO la estimes", r["nota"])


if __name__ == "__main__":
	unittest.main()
