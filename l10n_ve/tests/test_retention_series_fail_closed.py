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
        with patch(_GET_SERIES, side_effect=_throw_no_series) as mock_series:
            errors = _validate_digital_series(self.doc)

        self.assertEqual(len(errors), 1)
        self.assertIn("no está configurada en ninguna", errors[0])
        # Pinnear que el mock interceptó de verdad (el patch depende del import
        # diferido dentro de _validate_digital_series; si alguien sube el import
        # al tope del módulo, esto lo detecta en vez de pasar en silencio).
        mock_series.assert_called_once_with(
            company="Galanet Solution C.A.", branch="HQ"
        )

    def test_missing_series_clears_zombie_message(self) -> None:
        """El msgprint encolado por el throw tragado se desencola."""
        with patch(_GET_SERIES, side_effect=_throw_no_series):
            _validate_digital_series(self.doc)

        self.assertEqual(len(frappe.local.message_log), 0)

    def test_resolved_series_returns_no_errors(self) -> None:
        """Serie resuelta → sin errores."""
        with patch(_GET_SERIES, side_effect=_resolve_series) as mock_series:
            errors = _validate_digital_series(self.doc)

        self.assertEqual(errors, [])
        mock_series.assert_called_once_with(
            company="Galanet Solution C.A.", branch="HQ"
        )

    def test_missing_branch_returns_error(self) -> None:
        """Sin sucursal → el guard REAL de get_active_billing_series lanza
        (sin mock: con branch vacío lanza antes de tocar la BD) y el error
        se reporta fail-closed."""
        doc = frappe._dict(empresa="Galanet Solution C.A.", branch="")

        errors = _validate_digital_series(doc)

        self.assertEqual(len(errors), 1)
        self.assertIn("sucursal", errors[0])
        self.assertEqual(len(frappe.local.message_log), 0)


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


class TestGetActiveBillingSeries(FrappeTestCase):
    """El guard REAL de resolución de serie (la causa raíz del incidente:
    match por child.branch EXACTO — 'HQ' ≠ 'GALANET HQ')."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def tearDown(self) -> None:
        frappe.clear_messages()
        super().tearDown()

    def test_empty_branch_throws_without_touching_db(self) -> None:
        """Branch vacío → throw ANTES de consultar la BD."""
        from l10n_ve.digital_invoice.tfhka_integration import get_active_billing_series

        with patch.object(frappe.db, "sql") as mock_sql:
            with self.assertRaises(frappe.ValidationError):
                get_active_billing_series(company="Galanet Solution C.A.", branch="")
        mock_sql.assert_not_called()

    def test_unmatched_branch_throws_with_branch_in_message(self) -> None:
        """Escenario del incidente: la fila de la serie dice 'GALANET HQ' pero el
        comprobante trae 'HQ' → el match exacto no resuelve → throw con la
        sucursal en el mensaje (fail-closed, no serie vacía)."""
        from l10n_ve.digital_invoice.tfhka_integration import get_active_billing_series

        with patch.object(frappe.db, "sql", return_value=[]) as mock_sql:
            with self.assertRaises(frappe.ValidationError) as ctx:
                get_active_billing_series(
                    company="Galanet Solution C.A.", branch="HQ"
                )
        self.assertIn("'HQ'", str(ctx.exception))
        mock_sql.assert_called_once()

    def test_matched_row_returns_series_doc_and_branch_code(self) -> None:
        """Fila resuelta → (series_doc, branch_code de la tabla hija)."""
        from l10n_ve.digital_invoice.tfhka_integration import get_active_billing_series

        row = [{"series_name": "SFD-2026-0007", "branch_code": "HQ01"}]
        fake_series = MagicMock()
        with patch.object(frappe.db, "sql", return_value=row), \
             patch("frappe.get_doc", return_value=fake_series) as mock_get:
            series_doc, branch_code = get_active_billing_series(
                company="Galanet Solution C.A.", branch="GALANET HQ"
            )

        self.assertIs(series_doc, fake_series)
        self.assertEqual(branch_code, "HQ01")
        mock_get.assert_called_once_with("VE Digital Billing Series", "SFD-2026-0007")


class TestProcessRetentionVoucherGate(FrappeTestCase):
    """Enforcement e2e del carril IVA: process_retention_voucher NO emite si la
    validación pre-envío falla (espejo del test análogo de ISLR — revertir el
    gate reabre el incidente aunque _validate_digital_series siga existiendo)."""

    _MOD = "l10n_ve.digital_invoice.retention_integration"

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def tearDown(self) -> None:
        frappe.clear_messages()
        super().tearDown()

    def _run(self, raise_on_error: bool):
        fake_doc = MagicMock()
        # TFHKA prendido, explícito: apagado hay un early-return legítimo que marca
        # "Not Applicable" y ni llega a validar. Leerlo del sitio ata el test a la
        # configuración --en un sitio nuevo viene en 0 y el gate no se ejercita.
        with patch("frappe.get_doc", return_value=fake_doc), \
             patch.object(frappe.db, "get_single_value", return_value=1), \
             patch(f"{self._MOD}._validate_retention_integrity",
                   return_value=[_NO_SERIES_MSG]) as mock_validate, \
             patch(f"{self._MOD}._log_retention_request") as mock_log, \
             patch(f"{self._MOD}.TFHKAClient") as mock_client, \
             patch(f"{self._MOD}.TFHKARetentionPayloadBuilder") as mock_builder, \
             patch.object(frappe.db, "commit"):
            from l10n_ve.digital_invoice.retention_integration import (
                process_retention_voucher,
            )
            if raise_on_error:
                with self.assertRaises(frappe.ValidationError) as ctx:
                    process_retention_voucher("COMP-RET-IVA-TEST", raise_on_error=True)
                result = ctx
            else:
                result = process_retention_voucher("COMP-RET-IVA-TEST")
        return result, fake_doc, mock_validate, mock_log, mock_client, mock_builder

    def test_validation_error_blocks_emission(self) -> None:
        """Cron (raise_on_error=False): error de validación → False, estado
        Error, log registrado, y NI el builder NI el cliente HKA se tocan."""
        result, doc, mock_validate, mock_log, mock_client, mock_builder = self._run(
            raise_on_error=False
        )

        self.assertFalse(result)
        mock_validate.assert_called_once()
        doc.db_set.assert_called_once_with("digital_invoice_status", "Error")
        mock_log.assert_called_once()
        mock_builder.assert_not_called()
        mock_client.assert_not_called()

    def test_validation_error_raises_for_manual_button(self) -> None:
        """Botón manual (raise_on_error=True): error de validación → throw
        con el mensaje, sin tocar HKA."""
        ctx, doc, _, _, mock_client, mock_builder = self._run(raise_on_error=True)

        self.assertIn("no está configurada en ninguna", str(ctx.exception))
        doc.db_set.assert_called_once_with("digital_invoice_status", "Error")
        mock_builder.assert_not_called()
        mock_client.assert_not_called()

    def test_tfhka_disabled_is_the_only_not_applicable(self) -> None:
        """La única causa de "No aplica" es que la facturación digital esté
        apagada en el sitio. Antes también entraban acá el documento sin sucursal
        y la sucursal sin serie --configuración rota marcada como éxito."""
        fake_doc = MagicMock()
        with patch("frappe.get_doc", return_value=fake_doc), \
             patch.object(frappe.db, "get_single_value", return_value=0), \
             patch(f"{self._MOD}._validate_retention_integrity") as mock_validate, \
             patch(f"{self._MOD}.TFHKAClient") as mock_client:
            from l10n_ve.digital_invoice.retention_integration import (
                process_retention_voucher,
            )
            result = process_retention_voucher("COMP-RET-IVA-TEST")

        self.assertTrue(result)
        fake_doc.db_set.assert_called_once_with(
            "digital_invoice_status", "Not Applicable"
        )
        mock_validate.assert_not_called()
        mock_client.assert_not_called()


class TestBuildPayloadFailClosed(FrappeTestCase):
    """Defensa en profundidad: el builder NUNCA arma un payload con serie vacía,
    aunque un caller futuro se salte la validación pre-envío."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def tearDown(self) -> None:
        frappe.clear_messages()
        super().tearDown()

    def test_empty_serie_blocks_build_payload(self) -> None:
        """Serie vacía (el builder tragó el error) → build_payload lanza."""
        doc = frappe._dict(
            name="COMP-RET-IVA-TEST", empresa="Galanet Solution C.A.", branch="HQ"
        )
        with patch(_GET_SERIES, side_effect=_throw_no_series):
            builder = BaseRetentionPayloadBuilder(doc)

        self.assertEqual(builder._serie, "")
        with self.assertRaises(frappe.ValidationError) as ctx:
            builder.build_payload()
        self.assertIn("serie vacía", str(ctx.exception))
