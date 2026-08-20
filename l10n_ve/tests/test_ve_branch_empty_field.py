# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Un documento SIN sucursal no es un documento de otra sucursal.

`has_ve_branch_permission` recorría los campos Link a VE Branch y solo devolvía True cuando
alguno traía un valor permitido; con todos vacíos caía en `return False`. Eso dejaba al
documento fuera del alcance de cualquier usuario restringido por sucursal --o sea, de todos
menos los admin-- aunque no perteneciera a ninguna sucursal ajena.

Es además más estricto que el propio Frappe: `check_user_permission_on_link_fields` saltea el
campo vacío salvo que `apply_strict_user_permissions` esté activo. El fix sigue ese criterio,
así que el ajuste del sitio manda en los dos lados.

Caso real: los anticipos del conector de Bancaribe nacen sin sucursal, y al cruzarlos contra
una factura desde el panel ISP el usuario recibía "No permitido mediante el controlador de
comprobación de permisos".

Sin tocar la base de datos: se simula el doc y se mockean los ayudantes del módulo.
"""

import unittest
from unittest.mock import patch

from l10n_ve import permissions

MOD = "l10n_ve.permissions"


class _FakeMeta:
    def __init__(self, issingle=False):
        self.issingle = issingle


class _FakeDoc:
    """`self` mínimo: el guard usa doctype, get(), is_new() y la meta."""

    def __init__(self, doctype="Payment Entry", values=None, is_new=False):
        self.doctype = doctype
        self._values = values or {}
        self._is_new = is_new

    def get(self, fieldname, default=None):
        return self._values.get(fieldname, default)

    def is_new(self):
        return self._is_new


def _run(values, allowed=("LAR-01", "LAR-04"), strict=0, branch_fields=("branch",)):
    doc = _FakeDoc(values=values)
    with patch(f"{MOD}.is_admin_user", return_value=False), \
         patch(f"{MOD}.get_allowed_branches", return_value=list(allowed)), \
         patch(f"{MOD}._get_branch_fields_for_doctype", return_value=list(branch_fields)), \
         patch(f"{MOD}.frappe.get_meta", return_value=_FakeMeta()), \
         patch(f"{MOD}.frappe.get_system_settings", return_value=strict):
        return permissions.has_ve_branch_permission(doc, ptype="write", user="u@x.com")


class TestVeBranchEmptyField(unittest.TestCase):

    def test_documento_sin_sucursal_es_accesible(self):
        """El caso del anticipo de Bancaribe: branch vacío no debe bloquear."""
        self.assertTrue(_run({"branch": None}))
        self.assertTrue(_run({"branch": ""}))

    def test_documento_de_sucursal_permitida_sigue_accesible(self):
        self.assertTrue(_run({"branch": "LAR-04"}))

    def test_documento_de_otra_sucursal_sigue_bloqueado(self):
        """La restricción real no se relaja: esto es lo que el guard debe seguir cortando."""
        self.assertFalse(_run({"branch": "MIR-01"}))

    def test_modo_estricto_respeta_el_ajuste_del_sitio(self):
        """Con apply_strict_user_permissions activo, el vacío vuelve a bloquear."""
        self.assertFalse(_run({"branch": None}, strict=1))
        self.assertTrue(_run({"branch": "LAR-04"}, strict=1))

    def test_varios_campos_de_sucursal(self):
        """Basta que UNO traiga sucursal permitida; todos vacíos entra por la rama nueva."""
        campos = ("branch", "target_branch")
        self.assertTrue(_run({"branch": None, "target_branch": "LAR-01"}, branch_fields=campos))
        self.assertFalse(_run({"branch": "MIR-01", "target_branch": None}, branch_fields=campos))
        self.assertTrue(_run({"branch": None, "target_branch": None}, branch_fields=campos))

    def test_usuario_sin_sucursales_sigue_sin_acceso(self):
        """Quien no tiene ninguna sucursal asignada no gana acceso por el campo vacío."""
        self.assertFalse(_run({"branch": None}, allowed=()))


if __name__ == "__main__":
    unittest.main()
