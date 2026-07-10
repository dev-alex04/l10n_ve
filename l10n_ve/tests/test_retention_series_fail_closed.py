# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests del fail-closed de serie digital en la emisión de retenciones.

Contexto (incidente COMP-RET-IVA-2026-00003, 2026-07-10): el builder de
retenciones tragaba el throw de get_active_billing_series y emitía a HKA
con serie vacía, mostrando además el diálogo de error de un flujo que no
se detuvo (frappe.throw encola el msgprint antes de lanzar).

Cubre:
- _validate_digital_series: bloquea cuando la sucursal no resuelve serie.
- _validate_retention_integrity / _validate_islr_integrity la incluyen.
- El mensaje zombi del throw tragado se desencola (validador y builder).
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.digital_invoice.base_withholding_builder import BaseRetentionPayloadBuilder
from l10n_ve.digital_invoice.islr_withholding_integration import _validate_islr_integrity
from l10n_ve.digital_invoice.retention_integration import (
    _validate_digital_series,
    _validate_retention_integrity,
)

_GET_SERIES = "l10n_ve.digital_invoice.tfhka_integration.get_active_billing_series"

_NO_SERIES_MSG = (
    "La sucursal 'HQ' no está configurada en ninguna "
    "Serie de Facturación Digital activa para 'Galanet Solution C.A.'."
)


def _throw_no_series(**kwargs):
    """Side effect que replica el throw real de get_active_billing_series."""
    frappe.throw(_NO_SERIES_MSG, title="Serie de Facturación No Encontrada")


def _resolve_series(**kwargs):
    """Side effect que replica una serie resuelta."""
    series_doc = MagicMock()
    series_doc.serie = "HQ"
    return series_doc, "HQ"


class TestValidateDigitalSeries(FrappeTestCase):
    """_validate_digital_series: el chequeo fail-closed compartido IVA/ISLR."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()
        self.doc = frappe._dict(empresa="Galanet Solution C.A.", branch="HQ")

    def test_missing_series_returns_error(self) -> None:
        """Sucursal sin serie activa → lista con el mensaje del throw."""
        with patch(_GET_SERIES, side_effect=_throw_no_series):
            errors = _validate_digital_series(self.doc)

        self.assertEqual(len(errors), 1)
        self.assertIn("no está configurada en ninguna", errors[0])

    def test_missing_series_clears_zombie_message(self) -> None:
        """El msgprint encolado por el throw tragado se desencola."""
        with patch(_GET_SERIES, side_effect=_throw_no_series):
            _validate_digital_series(self.doc)

        self.assertEqual(len(frappe.local.message_log), 0)

    def test_resolved_series_returns_no_errors(self) -> None:
        """Serie resuelta → sin errores."""
        with patch(_GET_SERIES, side_effect=_resolve_series):
            errors = _validate_digital_series(self.doc)

        self.assertEqual(errors, [])

    def test_missing_branch_returns_error(self) -> None:
        """Sin sucursal → get_active_billing_series lanza y el error se reporta."""
        doc = frappe._dict(empresa="Galanet Solution C.A.", branch="")

        def _throw_no_branch(**kwargs):
            if not kwargs.get("branch"):
                frappe.throw("La factura no tiene una sucursal asignada.")
            return _resolve_series(**kwargs)

        with patch(_GET_SERIES, side_effect=_throw_no_branch):
            errors = _validate_digital_series(doc)

        self.assertEqual(len(errors), 1)


class TestIntegrityValidatorsIncludeSeries(FrappeTestCase):
    """Los validadores de integridad IVA e ISLR incluyen el chequeo de serie."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def test_vat_integrity_includes_series_error(self) -> None:
        """_validate_retention_integrity reporta la serie faltante."""
        doc = frappe._dict(
            empresa="Galanet Solution C.A.",
            branch="HQ",
            supplier="PROV-INEXISTENTE",
            totals_taxes_and_charges_added=100.0,
            vat_withholding_voucher_item=[],
        )

        with patch(_GET_SERIES, side_effect=_throw_no_series):
            errors = _validate_retention_integrity(doc)

        self.assertTrue(any("no está configurada en ninguna" in e for e in errors))

    def test_islr_integrity_includes_series_error(self) -> None:
        """_validate_islr_integrity reporta la serie faltante."""
        doc = frappe._dict(
            empresa="Galanet Solution C.A.",
            branch="HQ",
            supplier="PROV-INEXISTENTE",
            totals_islr_amount=100.0,
            islr_withholding_voucher_item=[],
        )

        with patch(_GET_SERIES, side_effect=_throw_no_series):
            errors = _validate_islr_integrity(doc)

        self.assertTrue(any("no está configurada en ninguna" in e for e in errors))

    def test_vat_integrity_no_series_error_when_resolved(self) -> None:
        """Con serie resuelta no se agrega error de serie."""
        doc = frappe._dict(
            empresa="Galanet Solution C.A.",
            branch="HQ",
            supplier="PROV-INEXISTENTE",
            totals_taxes_and_charges_added=100.0,
            vat_withholding_voucher_item=[],
        )

        with patch(_GET_SERIES, side_effect=_resolve_series):
            errors = _validate_retention_integrity(doc)

        self.assertFalse(any("Serie de Facturación" in e for e in errors))


class TestLoadSeriesZombieMessage(FrappeTestCase):
    """_load_series del builder: la red de seguridad no muestra el diálogo mentiroso."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def test_swallowed_throw_clears_message(self) -> None:
        """Si el builder traga el throw de serie, desencola el msgprint."""
        doc = frappe._dict(empresa="Galanet Solution C.A.", branch="HQ")

        with patch(_GET_SERIES, side_effect=_throw_no_series):
            builder = BaseRetentionPayloadBuilder(doc)

        self.assertEqual(builder._serie, "")
        self.assertEqual(len(frappe.local.message_log), 0)

    def test_resolved_series_sets_serie(self) -> None:
        """Serie resuelta → el builder la carga."""
        doc = frappe._dict(empresa="Galanet Solution C.A.", branch="HQ")

        with patch(_GET_SERIES, side_effect=_resolve_series):
            builder = BaseRetentionPayloadBuilder(doc)

        self.assertEqual(builder._serie, "HQ")
        self.assertEqual(builder._branch_code, "HQ")
