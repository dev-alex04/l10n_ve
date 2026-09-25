# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


def _series(uses_series: int, branch_code: str):
    return frappe.get_doc({
        "doctype": "VE Digital Billing Series",
        "uses_series": uses_series,
        "serie": "MAR-05" if uses_series else "",
        "branches": [{"branch": "Sucursal X", "branch_code": branch_code}],
    })


class TestVEDigitalBillingSeries(FrappeTestCase):
    """Código de sucursal: obligatorio sólo cuando la serie usa serie."""

    def test_uses_series_requires_branch_code(self):
        with self.assertRaises(frappe.ValidationError):
            _series(1, "")._validate_branch_codes()

    def test_uses_series_with_branch_code_passes(self):
        _series(1, "LAR-10")._validate_branch_codes()

    def test_without_series_branch_code_is_optional(self):
        _series(0, "")._validate_branch_codes()
