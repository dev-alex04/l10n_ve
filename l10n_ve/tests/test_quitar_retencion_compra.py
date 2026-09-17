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
_MOD = "l10n_ve.overrides.purchase_invoice"
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


class TestRecalculoDeTotales(FrappeTestCase):
    """Los totales guardados quedan de acuerdo con las filas de impuesto que sobrevivieron.

    Es la parte más delicada del camino: escribe `grand_total`, `base_grand_total`, el monto
    en letras y el redondeo DIRECTO sobre una factura ya sometida, sin pasar por el calculador
    del documento. Si la suma se desvía, la factura se contradice a sí misma y el número sale
    impreso.

    Los importes salen del caso real que cita el docstring de la función (ACC-PINV-2026-00369):
    neto 154.791,10, IVA 24.766,58, retención de IVA 24.766,58 y retención de ISLR 1.512,08,
    que dan el total de 153.279,02 que tenía la factura.
    """

    _MONEDA = "VEF"
    _NETO = 154_791.10
    _IVA = 24_766.58
    _ISLR = 1_512.08

    def _filas(self, con_islr: bool = True) -> list[dict]:
        filas: list[dict] = [
            {"charge_type": "VAT", "add_deduct_tax": "Add", "tax_amount": self._IVA,
             "base_tax_amount": self._IVA, "is_tax_withholding_account": 0},
            {"charge_type": "VAT", "add_deduct_tax": "Deduct", "tax_amount": self._IVA,
             "base_tax_amount": self._IVA, "is_tax_withholding_account": 1},
        ]
        if con_islr:
            filas.append(
                {"charge_type": "ISLR", "add_deduct_tax": "Deduct", "tax_amount": self._ISLR,
                 "base_tax_amount": self._ISLR, "is_tax_withholding_account": 1}
            )
        return filas

    def _refrescar(self, filas: list[dict], sin_redondeo: int = 1) -> dict:
        from l10n_ve.overrides import purchase_invoice as mod

        doc = frappe._dict({
            "name": _FACTURA,
            "net_total": self._NETO,
            "base_net_total": self._NETO,
            "currency": self._MONEDA,
            "company": "Galanet Solution C.A.",
            "disable_rounded_total": sin_redondeo,
            "taxes": [frappe._dict(f) for f in filas],
        })
        doc.precision = lambda campo: 2

        guardado: dict = {}

        def _set_value(doctype, name, valores, **kwargs):
            guardado.update(valores)

        with patch("frappe.clear_document_cache") as limpiar, \
                patch("frappe.get_doc", return_value=doc), \
                patch("frappe.get_cached_value", return_value=self._MONEDA), \
                patch("frappe.db.set_value", _set_value), \
                patch(f"{_MOD}.money_in_words", lambda monto, moneda: f"{monto} {moneda}"), \
                patch(f"{_MOD}.round_based_on_smallest_currency_fraction",
                      lambda monto, moneda, precision: round(monto)):
            mod._refresh_purchase_totals_after_withholding_change(_FACTURA)

        guardado["_limpio_la_cache"] = limpiar.called
        return guardado

    def test_suma_las_filas_con_signo(self) -> None:
        """Add suma y Deduct resta. Invertirlo descuadra la factura en silencio."""
        guardado: dict = self._refrescar(self._filas())

        self.assertAlmostEqual(guardado["grand_total"], 153_279.02, places=2)
        self.assertAlmostEqual(guardado["base_grand_total"], 153_279.02, places=2)

    def test_al_quitar_el_islr_el_total_sube_lo_que_valia_esa_fila(self) -> None:
        """Es la razón de existir de la función: 153.279,02 pasa a 154.791,10."""
        guardado: dict = self._refrescar(self._filas(con_islr=False))

        self.assertAlmostEqual(guardado["grand_total"], 154_791.10, places=2)

    def test_los_acumulados_van_en_absoluto_y_el_total_con_signo(self) -> None:
        """`taxes_and_charges_deducted` es positivo aunque reste; el total no."""
        guardado: dict = self._refrescar(self._filas())

        self.assertAlmostEqual(guardado["taxes_and_charges_added"], self._IVA, places=2)
        self.assertAlmostEqual(
            guardado["taxes_and_charges_deducted"], self._IVA + self._ISLR, places=2
        )
        self.assertAlmostEqual(guardado["total_taxes_and_charges"], -self._ISLR, places=2)

    def test_el_total_retenido_solo_cuenta_las_filas_de_retencion(self) -> None:
        """El IVA no es una retención: sumarlo inflaría el «Total Retenido» del documento."""
        guardado: dict = self._refrescar(self._filas())

        self.assertAlmostEqual(
            guardado["total_withholding"], self._IVA + self._ISLR, places=2
        )

    def test_no_escribe_el_redondeo_si_la_factura_lo_tiene_deshabilitado(self) -> None:
        """Escribirlo igual le inventaría un redondeo a una factura que no lo usa."""
        guardado: dict = self._refrescar(self._filas(), sin_redondeo=1)

        self.assertNotIn("rounded_total", guardado)
        self.assertNotIn("base_rounded_total", guardado)

    def test_escribe_el_redondeo_si_la_factura_lo_usa(self) -> None:
        """18 de las 424 facturas emitidas lo tienen activo; ahí sí hay que actualizarlo."""
        guardado: dict = self._refrescar(self._filas(), sin_redondeo=0)

        self.assertIn("rounded_total", guardado)
        self.assertIn("base_rounded_total", guardado)

    def test_limpia_la_cache_antes_de_leer_las_filas(self) -> None:
        """Sin esto se suman las filas viejas: db_insert/db_delete no invalidan la caché."""
        self.assertTrue(self._refrescar(self._filas())["_limpio_la_cache"])
