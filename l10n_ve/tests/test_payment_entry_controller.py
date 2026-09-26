# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""La clase de Payment Entry lleva la lógica de l10n_ve, también en un sitio con hrms.

Pasó en domina.designet (26-sep-2026): hrms se instaló después de l10n_ve, Frappe resolvió
`override_doctype_class` con la clase de hrms y no corría nada de `CustomPaymentEntry`.
"""

import pickle
import unittest
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from frappe.model.base_document import import_controller

from l10n_ve.overrides.payment_entry import CustomPaymentEntry
from l10n_ve.patches.accounts import payment_entry_controller as pec

try:
    from hrms.overrides import employee_payment_entry as hrms_module
except ImportError:
    hrms_module = None


def _nuevo(cls, party_type):
    pe = cls.__new__(cls)
    pe.party_type = party_type
    return pe


@unittest.skipIf(hrms_module is None, "hrms no está en el bench")
class TestClaseCombinadaConHrms(unittest.TestCase):
    def setUp(self):
        pec.combine_with_hrms()  # ya corrió al importar l10n_ve; es idempotente
        self.combinada = hrms_module.EmployeePaymentEntry

    def test_hereda_de_las_dos_con_l10n_ve_primero(self):
        mro = self.combinada.__mro__
        self.assertIn(CustomPaymentEntry, mro)
        self.assertIn(pec.HRMS_BASE, mro)
        self.assertLess(mro.index(CustomPaymentEntry), mro.index(pec.HRMS_BASE))

    def test_combinar_dos_veces_no_vuelve_a_envolver(self):
        pec.combine_with_hrms()
        self.assertIs(hrms_module.EmployeePaymentEntry, self.combinada)
        self.assertEqual(
            sum(
                1
                for c in self.combinada.__mro__
                if c.__name__ == "VEEmployeePaymentEntry"
            ),
            1,
        )

    def test_referencias_de_cliente_suman_las_notas_de_debito(self):
        validas = _nuevo(self.combinada, "Customer").get_valid_reference_doctypes()
        self.assertIn("Sales Invoice", validas)
        self.assertIn("VE Sales Debit Note", validas)

    def test_referencias_de_empleado_siguen_siendo_las_de_hrms(self):
        validas = _nuevo(self.combinada, "Employee").get_valid_reference_doctypes()
        self.assertIn("Expense Claim", validas)
        self.assertIn("Employee Advance", validas)

    def test_se_puede_guardar_en_la_cache(self):
        """Frappe guarda los documentos en Redis con pickle: la clase tiene que ser importable
        por su nombre. Definida dentro de una función, `get_cached_doc` fallaba."""
        self.assertIs(pickle.loads(pickle.dumps(self.combinada)), self.combinada)
        pe = _nuevo(self.combinada, "Customer")
        self.assertIs(type(pickle.loads(pickle.dumps(pe))), self.combinada)

    def test_los_metodos_de_l10n_ve_estan(self):
        for metodo in ("calculate_government_withholdings", "calculate_igtf_taxes"):
            self.assertIs(
                getattr(self.combinada, metodo), getattr(CustomPaymentEntry, metodo)
            )


class TestLaClaseDelSitio(unittest.TestCase):
    def test_lleva_la_logica_de_l10n_ve(self):
        self.assertTrue(
            issubclass(import_controller("Payment Entry"), CustomPaymentEntry)
        )

    def test_con_hrms_instalado_lleva_tambien_la_de_hrms(self):
        if "hrms" not in frappe.get_installed_apps() or not pec.HRMS_BASE:
            self.skipTest("el sitio no tiene hrms")
        self.assertTrue(issubclass(import_controller("Payment Entry"), pec.HRMS_BASE))


class TestCheckController(unittest.TestCase):
    def test_avisa_si_la_clase_no_lleva_l10n_ve(self):
        with (
            patch(
                "frappe.model.base_document.import_controller",
                return_value=PaymentEntry,
            ),
            patch("frappe.log_error") as log_error,
        ):
            pec.check_controller()
        log_error.assert_called_once()
        self.assertIn("l10n_ve", log_error.call_args.kwargs["title"])

    def test_no_avisa_con_la_clase_de_l10n_ve(self):
        with (
            patch(
                "frappe.model.base_document.import_controller",
                return_value=CustomPaymentEntry,
            ),
            patch(
                "frappe.get_installed_apps",
                return_value=["frappe", "erpnext", "l10n_ve"],
            ),
            patch("frappe.log_error") as log_error,
        ):
            pec.check_controller()
        log_error.assert_not_called()
