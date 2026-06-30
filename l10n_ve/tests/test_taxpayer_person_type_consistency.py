# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para la consistencia entre Naturaleza del Contribuyente y
Tipo de Persona, y para is_juridical_customer().

Cubre el caso nuevo permitido: empresa extranjera (Naturaleza 'Extranjero'
con Tipo de Persona 'Persona jurídica no domiciliada'), que debe poder crearse
y tratarse fiscalmente como persona jurídica.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.utils.utils import (
    is_juridical_customer,
    validate_taxpayer_and_person_type_consistency,
)


def _party(nature: str, person_type: str) -> "frappe._dict":
    return frappe._dict(
        nature_of_the_taxpayer=nature,
        type_of_person=person_type,
    )


class TestTaxpayerPersonTypeConsistency(FrappeTestCase):
    """Tests para validate_taxpayer_and_person_type_consistency()."""

    def test_foreign_non_domiciled_legal_entity_allowed(self) -> None:
        """Extranjero + Persona jurídica no domiciliada -> permitido (caso nuevo)."""
        validate_taxpayer_and_person_type_consistency(
            _party("Extranjero", "Non-domiciled legal entity")
        )

    def test_foreign_natural_person_still_allowed(self) -> None:
        """Extranjero + persona natural -> sigue permitido."""
        validate_taxpayer_and_person_type_consistency(
            _party("Extranjero", "Non-domiciled natural person")
        )

    def test_juridical_legal_entity_still_allowed(self) -> None:
        """Jurídico + entidad legal -> sigue permitido."""
        validate_taxpayer_and_person_type_consistency(
            _party("Juridical", "Domiciled legal entity")
        )

    def test_foreign_domiciled_legal_entity_blocked(self) -> None:
        """Extranjero + Persona jurídica DOMICILIADA -> sigue bloqueado."""
        with self.assertRaises(frappe.ValidationError):
            validate_taxpayer_and_person_type_consistency(
                _party("Extranjero", "Domiciled legal entity")
            )

    def test_venezuelan_legal_entity_blocked(self) -> None:
        """Venezolano + entidad legal -> sigue bloqueado."""
        with self.assertRaises(frappe.ValidationError):
            validate_taxpayer_and_person_type_consistency(
                _party("Venezuelan", "Non-domiciled legal entity")
            )

    def test_juridical_natural_person_blocked(self) -> None:
        """Jurídico + persona natural -> sigue bloqueado."""
        with self.assertRaises(frappe.ValidationError):
            validate_taxpayer_and_person_type_consistency(
                _party("Juridical", "Natural person domiciled")
            )


class TestIsJuridicalCustomer(FrappeTestCase):
    """Tests para is_juridical_customer()."""

    @patch("l10n_ve.utils.utils.frappe.get_cached_value")
    def test_foreign_legal_entity_is_juridical(self, mock_get_cached_value) -> None:
        """Empresa extranjera no domiciliada -> jurídica (tratamiento fiscal correcto)."""
        mock_get_cached_value.return_value = ["Extranjero", "Non-domiciled legal entity"]
        self.assertTrue(is_juridical_customer("CUST-FOREIGN-CO"))

    @patch("l10n_ve.utils.utils.frappe.get_cached_value")
    def test_foreign_natural_is_not_juridical(self, mock_get_cached_value) -> None:
        """Persona natural extranjera -> NO jurídica."""
        mock_get_cached_value.return_value = ["Extranjero", "Non-domiciled natural person"]
        self.assertFalse(is_juridical_customer("CUST-FOREIGN-NAT"))

    @patch("l10n_ve.utils.utils.frappe.get_cached_value")
    def test_juridical_nature_is_juridical(self, mock_get_cached_value) -> None:
        """Naturaleza jurídica -> jurídica (comportamiento previo intacto)."""
        mock_get_cached_value.return_value = ["Juridical", "Domiciled legal entity"]
        self.assertTrue(is_juridical_customer("CUST-JUR"))

    @patch("l10n_ve.utils.utils.frappe.get_cached_value")
    def test_venezuelan_natural_is_not_juridical(self, mock_get_cached_value) -> None:
        """Persona natural venezolana -> NO jurídica (comportamiento previo intacto)."""
        mock_get_cached_value.return_value = ["Venezuelan", "Natural person domiciled"]
        self.assertFalse(is_juridical_customer("CUST-VE-NAT"))
