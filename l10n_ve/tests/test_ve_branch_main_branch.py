# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de la sucursal principal (`is_main`) de VE Branch.

La principal es la que el formulario propone en un documento nuevo cuando quien lo crea no
tiene sucursal asignada, y la que recibe una compañía nueva para que la serie de facturación
digital, que se mapea por sucursal, tenga a qué asociarse.

Cubre:
- validate_main_branch: operativa, con compañía y única por compañía.
- get_main_branches_for_user: solo para quien no tiene sucursal asignada.
- ensure_main_branch: crea la raíz y la principal solo si la compañía no tiene sucursales y
  tiene lo que VE Branch exige, y no deja nada a medias si falla.
- _company_payment_modes: todos los modos de la compañía, con Efectivo como predeterminado.
- CustomCompany.on_update: la llama solo al crear la compañía.
"""

from typing import ClassVar
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.l10n_ve.doctype.ve_branch.ve_branch import (
    _company_payment_modes,
    ensure_main_branch,
    get_main_branches_for_user,
)

MOD = "l10n_ve.l10n_ve.doctype.ve_branch.ve_branch"
_COMPANY_A = "Galanet Solution C.A."
_COMPANY_B = "Domina Software C.A."


def _branch(
    name: str = "Principal - GS",
    company: str | None = _COMPANY_A,
    is_main: int = 1,
    is_group: int = 0,
):
    """VE Branch en memoria: validate_main_branch sólo lee campos."""
    doc = frappe.get_doc({
        "doctype": "VE Branch",
        "branch_name": name,
        "company": company,
        "is_main": is_main,
        "is_group": is_group,
    })
    doc.name = name
    return doc


class TestValidateMainBranch(FrappeTestCase):
    """validate_main_branch: una principal por compañía, operativa y con compañía."""

    def setUp(self) -> None:
        super().setUp()
        frappe.clear_messages()

    def test_unflagged_branch_skips_the_check(self) -> None:
        with patch("frappe.db.exists") as mock_exists:
            _branch(is_main=0).validate_main_branch()

        mock_exists.assert_not_called()

    def test_group_branch_is_rejected(self) -> None:
        """La principal es la que llevan los documentos: un nodo de agrupación no sirve."""
        with patch("frappe.db.exists") as mock_exists, self.assertRaises(frappe.ValidationError):
            _branch(is_group=1).validate_main_branch()

        mock_exists.assert_not_called()

    def test_branch_without_company_is_rejected(self) -> None:
        """Sin compañía no hay contra qué medir la unicidad."""
        with self.assertRaises(frappe.ValidationError):
            _branch(company=None).validate_main_branch()

    def test_second_main_branch_in_same_company_throws(self) -> None:
        with patch("frappe.db.exists", return_value="Principal - GS"), \
                self.assertRaises(frappe.ValidationError):
            _branch(name="Valencia").validate_main_branch()

    def test_uniqueness_is_scoped_by_company(self) -> None:
        """Cada compañía de un sitio multiempresa tiene su propia principal."""
        with patch("frappe.db.exists", return_value=None) as mock_exists:
            _branch(name="Principal - DS", company=_COMPANY_B).validate_main_branch()

        doctype, filters = mock_exists.call_args[0]
        self.assertEqual(doctype, "VE Branch")
        self.assertEqual(
            filters, {"is_main": 1, "company": _COMPANY_B, "name": ["!=", "Principal - DS"]}
        )


class TestMainBranchesForUser(FrappeTestCase):
    """get_main_branches_for_user: el mapa que el boot le pasa al formulario."""

    def test_user_with_an_assigned_branch_gets_nothing(self) -> None:
        """A quien tiene sucursal se la pone set_ve_branch; el formulario no propone nada."""
        with patch("frappe.db.exists", return_value="fila"), patch("frappe.get_all") as mock_get_all:
            self.assertEqual(get_main_branches_for_user("cajero@galanet.com.ve"), {})

        mock_get_all.assert_not_called()

    def test_user_without_branch_gets_the_main_branch_of_each_company(self) -> None:
        rows = [
            frappe._dict(name="Principal - GS", company=_COMPANY_A),
            frappe._dict(name="Suelta", company=None),
        ]
        with patch("frappe.db.exists", return_value=None), \
                patch("frappe.get_all", return_value=rows) as mock_get_all:
            result = get_main_branches_for_user("Administrator")

        self.assertEqual(result, {_COMPANY_A: "Principal - GS"})
        self.assertEqual(mock_get_all.call_args.kwargs["filters"], {"is_main": 1, "is_group": 0})


class TestEnsureMainBranch(FrappeTestCase):
    """ensure_main_branch: la sucursal con la que nace una compañía."""

    MODES: ClassVar[list[dict]] = [
        {"mode_of_payment": "Efectivo", "account": "Caja - GS", "is_default": 1},
        {"mode_of_payment": "Pagomóvil", "account": "Banco - GS", "is_default": 0},
    ]

    def _run(self, existing=(), company_has_branches=False, cost_center="Principal - GS",
             modes=None, dry_run=False, insert_error=None):
        inserted: list[dict] = []

        def fake_exists(doctype, filters):
            if isinstance(filters, dict):
                return "otra" if company_has_branches else None
            return filters if filters in existing else None

        def fake_get_doc(values):
            doc = MagicMock()
            doc.insert.side_effect = insert_error or (lambda **kwargs: inserted.append(values))
            return doc

        company = frappe._dict(cost_center=cost_center, abbr="GS")
        payment_modes = self.MODES if modes is None else modes
        with patch("frappe.db.exists", side_effect=fake_exists), \
                patch("frappe.db.get_value", return_value=company), \
                patch(f"{MOD}._company_payment_modes", return_value=payment_modes), \
                patch("frappe.get_doc", side_effect=fake_get_doc), \
                patch("frappe.db.savepoint") as savepoint, \
                patch("frappe.db.rollback") as rollback, \
                patch("frappe.log_error") as log_error:
            result = ensure_main_branch(_COMPANY_A, dry_run=dry_run)

        return result, inserted, savepoint, rollback, log_error

    def test_company_with_branches_is_left_alone(self) -> None:
        """Galanet ya tiene su árbol: no recibe nada nuevo."""
        (created, detail), inserted, *_ = self._run(company_has_branches=True)

        self.assertFalse(created)
        self.assertEqual(detail, "ya tiene sucursales")
        self.assertEqual(inserted, [])

    def test_missing_cost_center_skips_the_creation(self) -> None:
        (created, _detail), inserted, *_ = self._run(cost_center=None)

        self.assertFalse(created)
        self.assertEqual(inserted, [])

    def test_missing_payment_modes_skips_the_creation(self) -> None:
        """Con un plan de cuentas aliado puede no haber modos de pago con cuenta."""
        (created, _detail), inserted, *_ = self._run(modes=[])

        self.assertFalse(created)
        self.assertEqual(inserted, [])

    def test_a_taken_name_skips_the_creation(self) -> None:
        """El nombre de VE Branch es único en todo el sitio, no por compañía."""
        (created, detail), inserted, *_ = self._run(existing={_COMPANY_A})

        self.assertFalse(created)
        self.assertIn(_COMPANY_A, detail)
        self.assertEqual(inserted, [])

    def test_dry_run_creates_nothing(self) -> None:
        (created, detail), inserted, *_ = self._run(dry_run=True)

        self.assertFalse(created)
        self.assertIn("Principal - GS", detail)
        self.assertEqual(inserted, [])

    def test_creates_the_root_group_and_the_main_leaf(self) -> None:
        """La raíz evita que is_root_branch_user se quede sin raíces; la hoja va en los documentos."""
        (created, branch), inserted, savepoint, rollback, _log = self._run()

        self.assertTrue(created)
        self.assertEqual(branch, "Principal - GS")
        root, main = inserted
        self.assertEqual(
            (root["branch_name"], root["is_group"], root["is_main"], root["parent_ve_branch"]),
            (_COMPANY_A, 1, 0, None),
        )
        self.assertEqual(
            (main["branch_name"], main["is_group"], main["is_main"], main["parent_ve_branch"]),
            ("Principal - GS", 0, 1, _COMPANY_A),
        )
        for node in inserted:
            self.assertEqual(node["company"], _COMPANY_A)
            self.assertEqual(node["cost_center"], "Principal - GS")
            self.assertEqual(node["mode_of_payments"], self.MODES)
        # Cada nodo recibe sus propias filas: frappe.get_doc modifica los dicts que recibe.
        self.assertIsNot(root["mode_of_payments"][0], main["mode_of_payments"][0])
        savepoint.assert_called_once()
        rollback.assert_not_called()

    def test_a_failure_rolls_back_to_the_savepoint(self) -> None:
        """Si falla la hoja, la raíz no queda suelta ni se cae la creación de la compañía."""
        (created, detail), _inserted, savepoint, rollback, log_error = self._run(
            insert_error=frappe.ValidationError("sin permiso")
        )

        self.assertFalse(created)
        self.assertIn("sin permiso", detail)
        rollback.assert_called_once_with(save_point=savepoint.call_args[0][0])
        log_error.assert_called_once()


class TestCompanyPaymentModes(FrappeTestCase):
    """_company_payment_modes: en una empresa de una sola sucursal, esa sucursal es la empresa."""

    def test_all_modes_with_cash_as_default(self) -> None:
        rows = [
            frappe._dict(mode_of_payment="Biopago", account="Banco - GS"),
            frappe._dict(mode_of_payment="Efectivo", account="Caja - GS"),
        ]
        with patch("frappe.db.sql", return_value=rows):
            result = _company_payment_modes(_COMPANY_A)

        self.assertEqual(result, [
            {"mode_of_payment": "Biopago", "account": "Banco - GS", "is_default": 0},
            {"mode_of_payment": "Efectivo", "account": "Caja - GS", "is_default": 1},
        ])

    def test_without_cash_the_first_mode_is_the_default(self) -> None:
        rows = [
            frappe._dict(mode_of_payment="Biopago", account="Banco - GS"),
            frappe._dict(mode_of_payment="Pagomóvil", account="Banco - GS"),
        ]
        with patch("frappe.db.sql", return_value=rows):
            result = _company_payment_modes(_COMPANY_A)

        self.assertEqual([row["is_default"] for row in result], [1, 0])

    def test_no_modes_returns_an_empty_list(self) -> None:
        with patch("frappe.db.sql", return_value=[]):
            self.assertEqual(_company_payment_modes(_COMPANY_A), [])


class TestCompanyCreatesMainBranch(FrappeTestCase):
    """CustomCompany.on_update: la sucursal principal nace con la compañía, no en cada guardado."""

    def _company(self, new: bool):
        doc = frappe.get_doc({
            "doctype": "Company",
            "company_name": "Nueva C.A.",
            "abbr": "NC",
            "default_currency": "VES",
            "country": "Venezuela",
        })
        doc.name = "Nueva C.A."
        if new:
            doc.flags.is_new_company = True
        return doc

    def _on_update(self, doc, ensure_result=(True, "Principal - NC")):
        with patch("erpnext.setup.doctype.company.company.Company.on_update"), \
                patch("l10n_ve.overrides.company.is_allied_chart", return_value=True), \
                patch("l10n_ve.overrides.company.ensure_main_branch",
                      return_value=ensure_result) as ensure, \
                patch("frappe.msgprint") as msgprint:
            doc.on_update()
        return ensure, msgprint

    def test_new_company_gets_its_main_branch(self) -> None:
        ensure, msgprint = self._on_update(self._company(new=True))

        ensure.assert_called_once_with("Nueva C.A.")
        self.assertIn("Principal - NC", msgprint.call_args_list[-1][0][0])

    def test_existing_company_is_not_touched(self) -> None:
        ensure, _msgprint = self._on_update(self._company(new=False))

        ensure.assert_not_called()
