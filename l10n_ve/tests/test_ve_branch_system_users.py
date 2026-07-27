# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Solo usuarios del sistema pueden asignarse a una sucursal (VE Branch).

Los usuarios de portal (clientes) no deben entrar a la tabla de accesos: `sync_user_permissions`
les crearía un User Permission sobre VE Branch y `propagate_users_to_children` los arrastraría a
las sucursales hijas. El selector del formulario ya los filtra; el guard cubre API/importación.

Regla clave: solo se validan los usuarios AGREGADOS en ese guardado. Lo ya asignado se respeta,
para no volver inguardable una sucursal que arrastra asignaciones previas (o cuyo usuario pasó a
ser de portal después de haberse asignado).

Sin tocar la base de datos: se simula el doc y se mockea frappe.get_all.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe import _dict

from l10n_ve.l10n_ve.doctype.ve_branch.ve_branch import VEBranch

MOD = "l10n_ve.l10n_ve.doctype.ve_branch.ve_branch.frappe.get_all"


class _FakeBranch:
    """`self` mínimo: el guard usa get(), get_doc_before_save() y frappe.throw."""

    def __init__(self, users, previous=None):
        self._users = [_dict(user=u) for u in users]
        self._previous = previous

    def get(self, fieldname, default=None):
        return self._users if fieldname == "users" else default

    def get_doc_before_save(self):
        if self._previous is None:
            return None
        return _FakeBranch(self._previous)


def _run(users, previous=None, non_system=()):
    doc = _FakeBranch(users, previous)
    with patch(MOD, return_value=list(non_system)):
        VEBranch.validate_system_users(doc)


class TestVEBranchSystemUsers(unittest.TestCase):
    def test_only_system_users_passes(self):
        _run(["ana@galanet.com.ve"], previous=[], non_system=[])

    def test_new_portal_user_is_blocked(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            _run(["cliente@gmail.com"], previous=[], non_system=["cliente@gmail.com"])
        self.assertIn("cliente@gmail.com", str(ctx.exception))

    def test_existing_portal_user_is_respected(self):
        """Ya estaba asignado: no se valida y la sucursal se puede seguir guardando."""
        with patch(MOD) as mock_get_all:
            _run(["cliente@gmail.com"], previous=["cliente@gmail.com"])
            mock_get_all.assert_not_called()  # ni siquiera consulta: no hay usuarios nuevos

    def test_only_the_added_user_is_reported(self):
        """Con uno viejo de portal y otro nuevo, el error nombra solo al nuevo."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            _run(
                ["viejo@gmail.com", "nuevo@gmail.com"],
                previous=["viejo@gmail.com"],
                non_system=["nuevo@gmail.com"],
            )
        msg = str(ctx.exception)
        self.assertIn("nuevo@gmail.com", msg)
        self.assertNotIn("viejo@gmail.com", msg)

    def test_new_doc_validates_all_users(self):
        """Sucursal nueva (sin versión previa): todos los usuarios son 'agregados'."""
        with self.assertRaises(frappe.ValidationError):
            _run(["cliente@gmail.com"], previous=None, non_system=["cliente@gmail.com"])

    def test_no_users_is_noop(self):
        with patch(MOD) as mock_get_all:
            _run([], previous=[])
            mock_get_all.assert_not_called()
