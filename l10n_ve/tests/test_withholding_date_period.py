# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests del candado de quincenas sobre ``withholding_date``
(``l10n_ve.overrides.sales_invoice`` + ``l10n_ve.permissions``).

Cubre:

- ``has_accounting_permission``: Administrator, roles contables, roles ajenos y
  usuario explícito vs. el de la sesión.
- ``validate_withholding_date_period``: la validación solo corre cuando la fecha
  *cambia*.

Esa última condición es el punto del test, no un detalle: ``is_period_open``
compara la fecha contra HOY, no contra el documento, así que toda quincena
termina cerrándose. Sin el filtro por cambio, una factura registrada de forma
legítima quedaba imposible de guardar unas semanas después — y por cualquier
edición ajena a la retención, porque ``validate()`` corre entera en cada save.
``test_existing_invoice_unchanged_date_in_closed_period_passes`` es la regresión
de eso.

Son tests unitarios: NO tocan la base de datos (se parchean ``frappe.get_roles``
y ``has_accounting_permission``, y el documento es un doble). Requieren sitio
solo porque ``FrappeTestCase`` abre una transacción.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from l10n_ve import permissions
from l10n_ve.overrides import sales_invoice as si


#: Fecha de una quincena cerrada hace años: `is_period_open` la rechaza siempre,
#: sin importar cuándo corra la suite.
CLOSED_DATE = "2020-01-10"


class _FakeInvoice:
    """Doble mínimo de Sales Invoice para ejercitar la validación sin BD."""

    def __init__(self, withholding_date=None, is_new=False, changed=False):
        self.withholding_date = withholding_date
        self._is_new = is_new
        self._changed = changed

    def is_new(self):
        return self._is_new

    def has_value_changed(self, fieldname):
        assert fieldname == "withholding_date"
        return self._changed


def _validate(invoice):
    """Invoca la validación real sobre el doble, sin instanciar el DocType."""
    return si.VESalesInvoice.validate_withholding_date_period(invoice)


# --------------------------------------------------------------------------- #
# has_accounting_permission
# --------------------------------------------------------------------------- #
class TestHasAccountingPermission(FrappeTestCase):
    def test_administrator_bypasses_without_hitting_roles(self):
        with patch.object(permissions.frappe, "get_roles") as get_roles:
            self.assertTrue(permissions.has_accounting_permission("Administrator"))
            get_roles.assert_not_called()

    def test_accounting_role_is_authorized(self):
        with patch.object(permissions.frappe, "get_roles", return_value=["All", "Accounts User"]):
            self.assertTrue(permissions.has_accounting_permission("contable@test.com"))

    def test_unrelated_roles_are_rejected(self):
        with patch.object(permissions.frappe, "get_roles", return_value=["All", "Sales User"]):
            self.assertFalse(permissions.has_accounting_permission("vendedor@test.com"))

    def test_falls_back_to_session_user(self):
        """Sin argumento resuelve contra la sesión.

        Se fija el usuario a mano en vez de con ``mock.patch``: ``frappe.session``
        cuelga de ``frappe.local`` (werkzeug Local, sin ``__dict__``), y mock lo
        trata como atributo no-local y hace ``delattr`` al salir — eso rompe la
        sesión real para el resto de la suite.
        """
        original_user = frappe.session.user
        frappe.session.user = "vendedor@test.com"
        try:
            with patch.object(permissions.frappe, "get_roles", return_value=["Sales User"]) as get_roles:
                self.assertFalse(permissions.has_accounting_permission())
                get_roles.assert_called_once_with("vendedor@test.com")
        finally:
            frappe.session.user = original_user

    def test_administrator_is_not_listed_as_a_role(self):
        """Es un usuario, no un rol: lo resuelve el early-return, no el conjunto."""
        self.assertNotIn("Administrator", permissions.ACCOUNTING_ROLES)


# --------------------------------------------------------------------------- #
# validate_withholding_date_period
# --------------------------------------------------------------------------- #
class TestValidateWithholdingDatePeriod(FrappeTestCase):
    def test_empty_date_passes(self):
        with patch.object(si, "has_accounting_permission", return_value=False) as perm:
            _validate(_FakeInvoice(withholding_date=None, changed=True))
            perm.assert_not_called()

    def test_existing_invoice_unchanged_date_in_closed_period_passes(self):
        """Regresión: guardar una factura vieja no debe exigir rol contable.

        La fecha no se está tocando; el período se cerró solo con el paso del
        tiempo. Bloquear aquí congelaba todo el histórico de facturas.
        """
        with patch.object(si, "has_accounting_permission", return_value=False) as perm:
            _validate(_FakeInvoice(withholding_date=CLOSED_DATE, changed=False))
            perm.assert_not_called()

    def test_changing_date_into_closed_period_without_role_throws(self):
        with patch.object(si, "has_accounting_permission", return_value=False):
            with self.assertRaises(frappe.ValidationError):
                _validate(_FakeInvoice(withholding_date=CLOSED_DATE, changed=True))

    def test_changing_date_into_closed_period_with_role_passes(self):
        with patch.object(si, "has_accounting_permission", return_value=True):
            _validate(_FakeInvoice(withholding_date=CLOSED_DATE, changed=True))

    def test_new_invoice_in_closed_period_without_role_throws(self):
        with patch.object(si, "has_accounting_permission", return_value=False):
            with self.assertRaises(frappe.ValidationError):
                _validate(_FakeInvoice(withholding_date=CLOSED_DATE, is_new=True))

    def test_open_period_never_consults_permissions(self):
        """Hoy siempre cae dentro de su propia quincena."""
        with patch.object(si, "has_accounting_permission", return_value=False) as perm:
            _validate(_FakeInvoice(withholding_date=nowdate(), is_new=True, changed=True))
            perm.assert_not_called()
