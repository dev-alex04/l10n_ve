# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de la sucursal de gastos (`is_expenses_branch`) en VE Branch.

La sucursal marcada es la que emite la factura de compra y los comprobantes de
retención generados automáticamente desde un Gasto (domina_expense). Como la
serie de facturación digital se resuelve POR SUCURSAL (ver
_validate_digital_series), dejar dos sucursales marcadas —o marcar un nodo de
agrupación, que no tiene serie propia— rompe la emisión fiscal.

Cubre:
- validate_unique_expense_branch: la unicidad está acotada por compañía.
- validate_unique_expense_branch: rechaza nodos de agrupación.
- get_expenses_branch: accesor público y su filtro por compañía.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.l10n_ve.doctype.ve_branch.ve_branch import get_expenses_branch

_EXISTS = "frappe.db.exists"
_GET_VALUE = "frappe.db.get_value"
_HAS_PERMISSION = "frappe.has_permission"

_COMPANY_A = "Galanet Solution C.A."
_COMPANY_B = "Domina Software C.A."


def _branch(
    name: str = "Caracas",
    company: str | None = _COMPANY_A,
    is_expenses_branch: int = 1,
    is_group: int = 0,
):
    """VE Branch en memoria: validate_unique_expense_branch sólo lee campos."""
    doc = frappe.get_doc({
        "doctype": "VE Branch",
        "branch_name": name,
        "company": company,
        "is_expenses_branch": is_expenses_branch,
        "is_group": is_group,
    })
    doc.name = name
    return doc


class TestValidateUniqueExpenseBranch(FrappeTestCase):
    """validate_unique_expense_branch: una sucursal de gastos por compañía."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def test_unflagged_branch_skips_the_check(self) -> None:
        """Sin el check activo no se consulta la BD."""
        doc = _branch(is_expenses_branch=0)

        with patch(_EXISTS) as mock_exists:
            doc.validate_unique_expense_branch()

        mock_exists.assert_not_called()

    def test_group_branch_is_rejected(self) -> None:
        """Un nodo de agrupación no tiene serie de facturación propia."""
        doc = _branch(is_group=1)

        with patch(_EXISTS) as mock_exists:
            with self.assertRaises(frappe.ValidationError):
                doc.validate_unique_expense_branch()

        # Se rechaza antes de gastar una consulta de unicidad.
        mock_exists.assert_not_called()

    def test_duplicate_in_same_company_throws(self) -> None:
        """Ya hay otra sucursal marcada en la misma compañía."""
        doc = _branch(name="Valencia")

        with patch(_EXISTS, return_value="Caracas"):
            with self.assertRaises(frappe.ValidationError):
                doc.validate_unique_expense_branch()

    def test_unique_check_is_scoped_by_company(self) -> None:
        """El filtro incluye la compañía: multi-compañía debe poder configurarse."""
        doc = _branch(name="Valencia", company=_COMPANY_B)

        with patch(_EXISTS, return_value=None) as mock_exists:
            doc.validate_unique_expense_branch()

        filters = mock_exists.call_args[0][1]
        self.assertEqual(filters["company"], _COMPANY_B)
        self.assertEqual(filters["is_expenses_branch"], 1)
        self.assertEqual(filters["name"], ["!=", "Valencia"])

    def test_branch_without_company_falls_back_to_global_check(self) -> None:
        """Sin compañía no hay forma de acotar: se compara contra todas."""
        doc = _branch(company=None)

        with patch(_EXISTS, return_value=None) as mock_exists:
            doc.validate_unique_expense_branch()

        filters = mock_exists.call_args[0][1]
        self.assertNotIn("company", filters)


class TestGetExpensesBranch(FrappeTestCase):
    """get_expenses_branch: el accesor público que consumen otras apps."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def test_filters_by_company_when_given(self) -> None:
        """Con compañía, la búsqueda queda acotada a esa compañía."""
        with patch(_HAS_PERMISSION, return_value=True):
            with patch(_GET_VALUE, return_value="HQ") as mock_get_value:
                self.assertEqual(get_expenses_branch(_COMPANY_A), "HQ")

        doctype, filters, fieldname = mock_get_value.call_args[0]
        self.assertEqual(doctype, "VE Branch")
        self.assertEqual(filters, {"is_expenses_branch": 1, "company": _COMPANY_A})
        self.assertEqual(fieldname, "name")

    def test_without_company_searches_globally(self) -> None:
        """Sin compañía se busca cualquier sucursal marcada."""
        with patch(_HAS_PERMISSION, return_value=True):
            with patch(_GET_VALUE, return_value="HQ") as mock_get_value:
                self.assertEqual(get_expenses_branch(), "HQ")

        filters = mock_get_value.call_args[0][1]
        self.assertEqual(filters, {"is_expenses_branch": 1})

    def test_returns_none_when_not_configured(self) -> None:
        """Sin sucursal marcada devuelve None: el llamador decide si es error."""
        with patch(_HAS_PERMISSION, return_value=True):
            with patch(_GET_VALUE, return_value=None):
                self.assertIsNone(get_expenses_branch(_COMPANY_A))
