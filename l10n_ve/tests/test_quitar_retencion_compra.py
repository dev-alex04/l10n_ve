# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de «Quitar Retención» en facturas de compra aprobadas.

Lo que se fija acá es la guarda que protege el documento fiscal: mientras un comprobante
de retención siga vivo (docstatus < 2), la retención que respalda no se toca. Si se
vaciara por debajo, el comprobante quedaría declarando ante el SENIAT un monto que la
factura ya no dice.

Caso que originó la función (16-sep-2026, ACC-PINV-2026-00369): el ISLR se cargó con el
concepto equivocado, su comprobante se anuló, y no había forma de corregirlo porque en la
factura aprobada solo existía el camino para AGREGAR retenciones.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.overrides.purchase_invoice import (
    _PURCHASE_WITHHOLDING_VOUCHER,
    _validate_no_live_withholding_voucher,
    remove_retroactive_purchase_withholding,
)

_FACTURA = "ACC-PINV-2026-99999"
_NRO_FACTURA = "000298"
_GET_ALL = "frappe.get_all"
_COMPROBANTE = "COMP-RET-IVA-2026-00380"
_NRO_COMPROBANTE = "20260900001368"


def _invoice() -> frappe._dict:
    return frappe._dict({"name": _FACTURA, "bill_no": _NRO_FACTURA})


def _vivo() -> list[dict]:
    return [{"name": _COMPROBANTE, "voucher_number": _NRO_COMPROBANTE}]


class TestGuardaComprobanteVivo(FrappeTestCase):
    """La guarda consulta dos veces: los comprobantes que citan la factura, y cuáles siguen vivos."""

    def test_corta_si_el_comprobante_sigue_vivo(self) -> None:
        with patch(_GET_ALL, side_effect=[[_COMPROBANTE], _vivo()]), \
                self.assertRaises(frappe.ValidationError) as ctx:
            _validate_no_live_withholding_voucher(_invoice(), "VAT")

        self.assertIn(_NRO_COMPROBANTE, str(ctx.exception))

    def test_el_mensaje_nombra_los_documentos_por_su_numero_fiscal(self) -> None:
        """El usuario tiene en la mano el número de la factura y el del comprobante, no el id."""
        with patch(_GET_ALL, side_effect=[[_COMPROBANTE], _vivo()]), \
                self.assertRaises(frappe.ValidationError) as ctx:
            _validate_no_live_withholding_voucher(_invoice(), "VAT")

        mensaje = str(ctx.exception)
        self.assertIn(f"<strong>{_NRO_FACTURA}</strong>", mensaje)
        self.assertIn(f"<strong>{_NRO_COMPROBANTE}</strong>", mensaje)
        # El identificador interno no se muestra, pero el enlace sí lleva al documento.
        self.assertNotIn(f">{_FACTURA}<", mensaje)
        self.assertIn(_COMPROBANTE, mensaje)

    def test_pasa_si_el_comprobante_esta_cancelado(self) -> None:
        """Lo cita un comprobante, pero está cancelado: la segunda consulta vuelve vacía."""
        with patch(_GET_ALL, side_effect=[[_COMPROBANTE], []]):
            _validate_no_live_withholding_voucher(_invoice(), "ISLR")

    def test_pasa_si_ningun_comprobante_la_cita(self) -> None:
        """Sin comprobantes no hay segunda consulta: sale de una."""
        with patch(_GET_ALL, side_effect=[[]]) as mock_get_all:
            _validate_no_live_withholding_voucher(_invoice(), "ISLR")

        self.assertEqual(mock_get_all.call_count, 1)

    def test_cada_retencion_mira_su_propio_comprobante(self) -> None:
        """El IVA no se bloquea por un comprobante de ISLR ni al revés."""
        self.assertEqual(_PURCHASE_WITHHOLDING_VOUCHER["VAT"], "VAT Withholding Voucher")
        self.assertEqual(_PURCHASE_WITHHOLDING_VOUCHER["ISLR"], "ISLR Withholding Voucher")

    def test_solo_cuentan_los_comprobantes_sin_cancelar(self) -> None:
        """El filtro docstatus < 2 es la guarda: si se cae, un comprobante vivo pasaría."""
        with patch(_GET_ALL, side_effect=[[_COMPROBANTE], []]) as mock_get_all:
            _validate_no_live_withholding_voucher(_invoice(), "ISLR")

        doctype = mock_get_all.call_args_list[1][0][0]
        filtros = mock_get_all.call_args_list[1][1]["filters"]
        self.assertEqual(doctype, "ISLR Withholding Voucher")
        self.assertEqual(filtros["docstatus"], ["<", 2])


class TestValidacionesDeEntrada(FrappeTestCase):

    def test_tipo_de_retencion_invalido(self) -> None:
        with self.assertRaises(frappe.ValidationError) as ctx:
            remove_retroactive_purchase_withholding(_FACTURA, "IGTF", "Galanet Solution C.A.")

        self.assertIn("IGTF", str(ctx.exception))

    def test_factura_inexistente_o_no_aprobada(self) -> None:
        with patch("frappe.db.exists", return_value=False), \
                self.assertRaises(frappe.ValidationError) as ctx:
            remove_retroactive_purchase_withholding(_FACTURA, "ISLR", "Galanet Solution C.A.")

        self.assertIn(_FACTURA, str(ctx.exception))


class TestFilaRetroactivaDeIslr(FrappeTestCase):
    """La fila que inserta el camino retroactivo tiene que servir para certificar.

    Sin el sustraendo, HKA rechaza el comprobante con «[1060] El monto retenido declarado no
    coincide con lo calculado en el item»: recalcula base x alícuota y no le da el monto, que
    lleva el sustraendo restado. Pasó el 16-sep-2026 con el comprobante 20260900000461.
    """

    def _construir_fila(self) -> dict:
        from l10n_ve.overrides.purchase_invoice import _create_purchase_taxes_row

        tabulador = frappe._dict({
            "name": "79",
            "codigo": "002",
            "descripcion": "HONORARIOS PROFESIONALES",
            "aliquot": [frappe._dict({
                "types_of_person": "Natural person domiciled",
                "aliquot": 3.0,
                "percentage_base": 100.0,
                "subtracting": 107.5,
            })],
        })
        factura = frappe._dict({
            "name": _FACTURA, "taxes": [], "cost_center": "DC-01",
            "company": "Galanet Solution C.A.", "supplier": "PROVEEDOR", "docstatus": 1,
        })

        insertada: dict = {}

        class _Fila(frappe._dict):
            def db_insert(self):
                insertada.update(self)

        with patch("frappe.new_doc", return_value=_Fila()), \
                patch("frappe.get_cached_doc", return_value=tabulador), \
                patch("frappe.db.get_value", return_value="Natural person domiciled"):
            _create_purchase_taxes_row(
                factura, "ISLR", "2105003 - Retenciones ISLR", "ISLR",
                4536.23, 4536.23, 3.0, "79",
            )
        return insertada

    def test_lleva_el_sustraendo_del_tabulador(self) -> None:
        self.assertEqual(self._construir_fila()["subtracting"], 107.5)

    def test_lleva_el_porcentaje_de_base(self) -> None:
        self.assertEqual(self._construir_fila()["percentage_base"], 100.0)

    def test_la_fila_queda_aprobada_como_su_factura(self) -> None:
        """Una fila en borrador dentro de una factura emitida es un estado que no existe."""
        self.assertEqual(self._construir_fila()["docstatus"], 1)
