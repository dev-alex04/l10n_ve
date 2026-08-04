# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la fecha de la tasa BCV que se imprime en el documento HKA.

Bug origen (jul-2026): factura de cliente jurídico generada el 01/07
(tasa 633.3644) y re-tasada al primer pago días después (tasa 653.9726,
regla jurídico = tasa del día del comprobante). El string impreso decía
"de fecha valor 01/07/2026" (inferido del posting_date) con la tasa nueva:
par tasa/fecha inconsistente ante SENIAT.

Fix: la fecha se resuelve desde la tasa misma con lookup inverso en
Currency Exchange (resolve_exchange_rate_date), no desde el posting_date.
Además, _validate_tasa_coherencia aplica también a jurídicos (fail-closed):
una tasa que no exista en Currency Exchange bloquea la emisión en vez de
certificarse con una fecha inventada.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.utils.utils import resolve_exchange_rate_date
from l10n_ve.digital_invoice.tfhka_integration import (
    _compute_tasa_fecha,
    _fecha_de_la_regla,
    _validate_tasa_coherencia,
)


def _make_invoice(**overrides):
    base = {
        "posting_date": "2026-07-01",
        "customer": "CUST-TEST",
        "conversion_rate": 653.9726,
        "currency": "USD",
        "company": "COMPANY-TEST",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestResolveExchangeRateDate(unittest.TestCase):
    @patch("frappe.db.sql", return_value=[("2026-07-02",)])
    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    def test_returns_date_of_matching_rate(self, _defaults, mock_sql):
        """Devuelve la fecha de la fila cuya tasa coincide con la del documento."""
        result = resolve_exchange_rate_date(653.9726, "USD")

        self.assertEqual(result, "2026-07-02")
        params = mock_sql.call_args[0][1]
        self.assertAlmostEqual(params[0], 653.9725, places=6)  # rate - tolerancia
        self.assertAlmostEqual(params[1], 653.9727, places=6)  # rate + tolerancia
        self.assertEqual(params[2], "USD")

    @patch("frappe.db.sql", return_value=[])
    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    def test_returns_none_when_no_row_matches(self, _defaults, _sql):
        """Sin fila coincidente → None (el caller decide el fallback)."""
        self.assertIsNone(resolve_exchange_rate_date(999.9999, "USD"))

    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    def test_returns_none_for_trivial_rates(self, _defaults):
        """Tasa vacía o factura en la moneda de la empresa → None sin ir a la BDD."""
        self.assertIsNone(resolve_exchange_rate_date(0, "USD"))
        self.assertIsNone(resolve_exchange_rate_date(1.0, "VEF"))


@patch(
    "l10n_ve.digital_invoice.tfhka_integration._fecha_de_la_regla",
    return_value=None,
)
class TestComputeTasaFecha(unittest.TestCase):
    """El documento NO porta la tasa de la regla: manda el lookup inverso.

    `_fecha_de_la_regla` se mockea en None para aislar esta rama; su propio
    comportamiento se prueba en TestFechaDeLaRegla.
    """

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.resolve_exchange_rate_date",
        return_value="2026-07-02",
    )
    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=True,
    )
    def test_juridical_uses_real_rate_date_not_posting_date(self, _jur, mock_resolve, _regla):
        """Caso del bug: jurídico re-tasado al pagar → la fecha es la de la tasa."""
        doc = _make_invoice(posting_date="2026-07-01", conversion_rate=653.9726)

        self.assertEqual(_compute_tasa_fecha(doc), "2026-07-02")
        mock_resolve.assert_called_once_with(653.9726, "USD")

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.resolve_exchange_rate_date",
        return_value=None,
    )
    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=True,
    )
    def test_juridical_falls_back_to_posting_date(self, _jur, _resolve, _regla):
        """Tasa sin fila en Currency Exchange → conserva el comportamiento previo."""
        doc = _make_invoice(posting_date="2026-07-01")

        self.assertEqual(_compute_tasa_fecha(doc), "2026-07-01")

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.resolve_exchange_rate_date",
        return_value=None,
    )
    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=False,
    )
    def test_natural_falls_back_to_first_of_month(self, _jur, _resolve, _regla):
        """Natural sin fila coincidente: 1° del mes del posting_date.

        Antes este test exigía que el lookup inverso NI SIQUIERA se llamara para el
        natural, y quedó desactualizado con la regla nueva (l10n_ve#534): hoy la tasa
        del natural también se retasa, así que su fecha real puede no ser el 1° del
        posting_date y el lookup sí corresponde. Lo que se conserva es el fallback.
        """
        doc = _make_invoice(posting_date="2026-07-15")

        self.assertEqual(_compute_tasa_fecha(doc), "2026-07-01")


@patch("frappe.get_cached_value", return_value="VEF")
@patch("l10n_ve.digital_invoice.tfhka_integration.nowdate", return_value="2026-08-04")
class TestFechaDeLaRegla(unittest.TestCase):
    """La fecha sale de la REGLA cuando el documento porta exactamente esa tasa.

    Nace de `ACC-SINV-2026-15614` (2026-08-04), cliente natural: portaba 748,7864,
    que es la tasa del 1° de agosto y la correcta para un natural, pero el 01, el 02
    y el 03 tenían todos ese mismo valor y `resolve_exchange_rate_date` --que ordena
    `date DESC`-- imprimía "de fecha valor 03/08/2026".

    `frappe.local.db` se bindea a un mock: sin site, `frappe.db` es un proxy de
    werkzeug que no se puede parchear ("object is not bound").
    """

    def setUp(self):
        self._db_original = getattr(frappe.local, "db", None)
        self.mock_db = MagicMock()
        frappe.local.db = self.mock_db

    def tearDown(self):
        # Restaurar SIEMPRE, incluso cuando no había `db` previa: sin site no la hay, y
        # dejar el mock puesto se lo filtra a las clases que corren después --que pasan
        # a "ver" una BDD que responde a todo--.
        if self._db_original is not None:
            frappe.local.db = self._db_original
        else:
            try:
                del frappe.local.db
            except AttributeError:
                pass

    def _publicada(self, valor):
        """Lo que Currency Exchange publica para la fecha de la regla."""
        self.mock_db.get_value.return_value = valor

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=False,
    )
    def test_natural_uses_first_of_current_month(self, _jur, _hoy, _cached):
        """El natural declara el 1° del mes EN CURSO, no el último día que repite la tasa."""
        self._publicada(748.7864)
        doc = _make_invoice(posting_date="2026-08-01", conversion_rate=748.7864)

        self.assertEqual(_fecha_de_la_regla(doc), "2026-08-01")
        self.assertEqual(self.mock_db.get_value.call_args[0][1]["date"], "2026-08-01")

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=True,
    )
    def test_juridical_uses_today(self, _jur, _hoy, _cached):
        """El jurídico declara HOY, aunque el documento sea de otro mes."""
        self._publicada(752.0943)
        doc = _make_invoice(posting_date="2026-07-15", conversion_rate=752.0943)

        self.assertEqual(_fecha_de_la_regla(doc), "2026-08-04")

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=False,
    )
    def test_none_when_document_carries_another_rate(self, _jur, _hoy, _cached):
        """Porta una tasa distinta a la publicada ese día → que decida el lookup inverso.

        Es el caso del documento viejo o con retasado pendiente. Devolver igual la
        fecha de la regla imprimiría un par tasa/fecha que `_validate_tasa_coherencia`
        --que valida contra la fila del día EXACTO-- bloquearía.
        """
        self._publicada(752.0943)
        doc = _make_invoice(posting_date="2026-08-01", conversion_rate=746.6297)

        self.assertIsNone(_fecha_de_la_regla(doc))

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=False,
    )
    def test_none_when_no_row_for_that_date(self, _jur, _hoy, _cached):
        """Sin fila publicada para la fecha de la regla → None, nunca una fecha inventada."""
        self._publicada(None)
        doc = _make_invoice(conversion_rate=748.7864)

        self.assertIsNone(_fecha_de_la_regla(doc))

    def test_none_for_company_currency_document(self, _hoy, _cached):
        """Documento en la moneda de la empresa: no hay cruce de moneda que fechar."""
        doc = _make_invoice(currency="VEF", conversion_rate=1.0)

        self.assertIsNone(_fecha_de_la_regla(doc))
        self.mock_db.get_value.assert_not_called()

    def test_none_without_rate(self, _hoy, _cached):
        """Sin tasa no hay nada que fechar, y no se consulta la BDD."""
        doc = _make_invoice(conversion_rate=0)

        self.assertIsNone(_fecha_de_la_regla(doc))
        self.mock_db.get_value.assert_not_called()


@patch("frappe.get_cached_value", return_value="VEF")
class TestValidateTasaCoherencia(unittest.TestCase):
    """La validación aplica ahora también a jurídicos (fail-closed)."""

    @patch("frappe.db.get_value", return_value=653.9726)
    def test_passes_when_rate_matches_printed_date(self, _rate, _company):
        """Flujo sano: la tasa del documento es la BCV de la fecha a imprimir."""
        doc = _make_invoice(conversion_rate=653.9726)

        _validate_tasa_coherencia(doc, "2026-07-02")  # no lanza

    @patch("frappe.db.get_value", return_value=633.3644)
    def test_blocks_when_rate_differs(self, _rate, _company):
        """Tasa del documento ≠ BCV de la fecha a imprimir → bloquea el envío."""
        doc = _make_invoice(conversion_rate=653.9726)

        with self.assertRaises(frappe.ValidationError):
            _validate_tasa_coherencia(doc, "2026-07-01")

    @patch("frappe.db.get_value", return_value=None)
    def test_blocks_when_no_rate_registered(self, _rate, _company):
        """Sin fila en Currency Exchange para la fecha → bloquea el envío."""
        doc = _make_invoice(conversion_rate=111.11)

        with self.assertRaises(frappe.ValidationError):
            _validate_tasa_coherencia(doc, "2026-07-01")

    @patch("frappe.db.get_value")
    def test_company_currency_document_skips_validation(self, mock_rate, _company):
        """Documento en la moneda de la empresa (tasa 1.0): nada que validar."""
        doc = _make_invoice(currency="VEF", conversion_rate=1.0)

        _validate_tasa_coherencia(doc, "2026-07-01")  # no lanza
        mock_rate.assert_not_called()
