# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""La vista de lista tiene que mostrar lo mismo que el enlace directo deja abrir.

`has_ve_branch_permission` ya concede el documento sin sucursal: no es de otra sucursal,
es de ninguna (ver `test_ve_branch_empty_field`). Pero la consulta de lista armaba solo
`campo IN (sucursales)`, y en SQL un `IN` **nunca** casa contra NULL, así que ese mismo
documento desaparecía de toda vista de lista, buscador y reporte.

El resultado era un documento accesible por enlace directo e invisible en la lista. El
síntoma engaña: parece un filtro de la pantalla, y es la condición de permisos.

**Caso real (reportado el 05-09-2026).** Un usuario acotado por sucursal abría un anticipo
de Bancaribe por su URL y no lo encontraba en ninguna lista. Medido en producción ese día:
135 Payment Entry emitidos sin sucursal de 24.754, de los cuales **134 son anticipos SIN
asignar por Bs 6.962.044,19**, invisibles para los 80 usuarios con permiso por sucursal.
Un saldo a favor que nadie ve es un saldo que nadie aplica.

Lo que fijan estos tests:

1. La condición incluye el caso «todos los campos de sucursal vacíos».
2. Sigue excluyendo los de OTRA sucursal: la restricción real no se relaja.
3. Con varios campos, el vacío cuenta solo si están vacíos TODOS (si uno trae sucursal
   ajena, el documento es de esa otra sucursal y no debe verse).
4. `apply_strict_user_permissions` manda, igual que en el gancho de documento: con el
   ajuste activo el vacío vuelve a ocultarse y los dos ganchos siguen diciendo lo mismo.
5. Un usuario sin ninguna sucursal sigue sin ver nada, y VE Branch no cambia.

Corren sin sitio: se mockean los ayudantes del módulo y `frappe.db.escape`.
"""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve import permissions

MOD = "l10n_ve.permissions"


@contextmanager
def _db_ligada():
    """`frappe.db` es un LocalProxy de werkzeug: sin sitio no se puede parchear.

    Se BINDEA `frappe.local.db` y se restaura el original al salir; nunca se borra el
    atributo, que bajo `bench run-tests` es la conexión real y romperla se lleva por
    delante el resto de la suite.
    """
    original = getattr(frappe.local, "db", None)
    fake = MagicMock()
    fake.escape.side_effect = lambda v: f"'{v}'"
    frappe.local.db = fake
    try:
        yield
    finally:
        frappe.local.db = original


def _query(doctype="Payment Entry", allowed=("LAR-01", "LAR-04"), branch_fields=("branch",), strict=0):
    """La condición SQL que Frappe le pega a la consulta de lista."""
    with _db_ligada(), \
         patch(f"{MOD}.is_admin_user", return_value=False), \
         patch(f"{MOD}.get_allowed_branches", return_value=list(allowed)), \
         patch(f"{MOD}._get_branch_fields_for_doctype", return_value=list(branch_fields)), \
         patch(f"{MOD}.frappe.get_system_settings", return_value=strict), \
         patch(f"{MOD}._is_ve_branch_tree_context", return_value=False):
        return permissions.get_ve_branch_permission_query(user="u@x.com", doctype=doctype)


class TestEmptyBranchIsVisibleInList(unittest.TestCase):
    def test_the_condition_covers_the_document_without_branch(self):
        sql = _query()
        self.assertIn("`tabPayment Entry`.branch IN ('LAR-01', 'LAR-04')", sql)
        self.assertIn("IFNULL(`tabPayment Entry`.branch, '') = ''", sql)
        # Las dos alternativas van en OR: o es de una sucursal mía, o no es de ninguna.
        self.assertIn(" OR ", sql)

    def test_another_branch_is_still_excluded(self):
        """Lo que NO se relaja: un documento de otra sucursal no aparece."""
        sql = _query()
        self.assertNotIn("MIR-01", sql)
        # La condición sigue nombrando solo las sucursales permitidas.
        self.assertEqual(sql.count("IN ('LAR-01', 'LAR-04')"), 1)

    def test_with_several_branch_fields_they_must_ALL_be_empty(self):
        """Si un campo trae sucursal ajena, el documento es de esa otra: no debe verse.

        De ahí que los vacíos vayan en AND entre sí, y en OR contra las sucursales.
        """
        sql = _query(branch_fields=("branch", "target_branch"))
        self.assertIn(
            "(IFNULL(`tabPayment Entry`.branch, '') = '' "
            "AND IFNULL(`tabPayment Entry`.target_branch, '') = '')",
            sql,
        )

    def test_strict_mode_hides_the_empty_one_again(self):
        """El ajuste del sitio manda, y los dos ganchos tienen que coincidir."""
        sql = _query(strict=1)
        self.assertNotIn("IFNULL", sql)
        self.assertIn("`tabPayment Entry`.branch IN ('LAR-01', 'LAR-04')", sql)

    def test_the_condition_comes_parenthesized(self):
        """Sin el paréntesis externo, el OR deja pasar documentos SIN User Permissions.

        Frappe pega la condición del gancho con `and` pelado (`build_match_conditions`),
        y en SQL el AND liga más fuerte que el OR: `((User Permissions)) and A OR B` se
        lee `((User Permissions) AND A) OR B`. Todo lo que case con B —el documento sin
        sucursal— entra saltándose las User Permissions.

        Medido sobre la copia de producción con un permiso acotado a una sola cuenta
        bancaria: 36 filas con paréntesis, 130 sin él; 94 de cuentas ajenas.
        """
        for kw in ({}, {"branch_fields": ("branch", "target_branch")}, {"strict": 1}):
            with self.subTest(**kw):
                sql = _query(**kw)
                self.assertTrue(sql.startswith("("), sql)
                self.assertTrue(sql.endswith(")"), sql)
                # Y el paréntesis tiene que ENVOLVER todo, no ser el de un miembro suelto.
                profundidad = 0
                for i, ch in enumerate(sql):
                    profundidad += (ch == "(") - (ch == ")")
                    if profundidad == 0 and i < len(sql) - 1:
                        self.fail(f"el parentesis se cierra antes del final: {sql}")

    def test_a_user_without_branches_still_sees_nothing(self):
        """El campo vacío no es una puerta trasera para quien no tiene ninguna sucursal."""
        self.assertEqual(_query(allowed=()), "1 = 0")

    def test_ve_branch_itself_is_unchanged(self):
        """Una sucursal siempre tiene nombre: ahí no hay vacío que contemplar."""
        sql = _query(doctype="VE Branch")
        self.assertEqual(sql, "`tabVE Branch`.name IN ('LAR-01', 'LAR-04')")
        self.assertNotIn("IFNULL", sql)

    def test_a_doctype_without_branch_fields_is_not_restricted(self):
        self.assertEqual(_query(branch_fields=()), "")

    def test_an_admin_sees_everything(self):
        with patch(f"{MOD}.is_admin_user", return_value=True):
            self.assertEqual(permissions.get_ve_branch_permission_query(user="a@x.com", doctype="Payment Entry"), "")


class TestBothHooksAgree(unittest.TestCase):
    """La propiedad que se rompió: lo que se puede abrir tiene que poder listarse."""

    def _can_open(self, values, allowed=("LAR-01", "LAR-04"), branch_fields=("branch",), strict=0):
        class _Meta:
            issingle = False

        class _Doc:
            doctype = "Payment Entry"

            def __init__(self, values):
                self._v = values

            def get(self, f, default=None):
                return self._v.get(f, default)

            def is_new(self):
                return False

        with patch(f"{MOD}.is_admin_user", return_value=False), \
             patch(f"{MOD}.get_allowed_branches", return_value=list(allowed)), \
             patch(f"{MOD}._get_branch_fields_for_doctype", return_value=list(branch_fields)), \
             patch(f"{MOD}.frappe.get_meta", return_value=_Meta()), \
             patch(f"{MOD}.frappe.get_system_settings", return_value=strict):
            return permissions.has_ve_branch_permission(_Doc(values), ptype="read", user="u@x.com")

    def test_what_can_be_opened_can_also_be_listed(self):
        for strict in (0, 1):
            with self.subTest(strict=strict):
                abre = self._can_open({"branch": None}, strict=strict)
                lista = "IFNULL" in _query(strict=strict)
                self.assertEqual(
                    abre,
                    lista,
                    "Los dos ganchos tienen que decir lo mismo del documento sin sucursal: "
                    f"abrir={abre}, aparece en la lista={lista}",
                )


if __name__ == "__main__":
    unittest.main()
