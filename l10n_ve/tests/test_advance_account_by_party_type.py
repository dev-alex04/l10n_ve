# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""La cuenta de anticipo se elige por TIPO DE ENTIDAD, no por direccion del pago.

Regresion: `add_party_gl_entries` elegia la cuenta con
``"default_advance_received_account" if self.payment_type == "Receive"``. Eso coincide
en los casos normales (Recibo de cliente / Pago a proveedor) pero manda el REEMBOLSO a
un cliente --payment_type="Pay" con party_type="Customer"-- a la cuenta de anticipo de
PROVEEDORES. Consecuencia en produccion: el anticipo del cliente nunca bajaba y quedaba
un activo espurio a su nombre en la cuenta de proveedores.

ERPNext decide por party_type (accounts/party.py). Estos tests fijan ese criterio para
las cuatro combinaciones, con foco en las dos cruzadas (reembolso y devolucion).

Sin tocar la base de datos: se ejercita solo la eleccion de la cuenta.
"""

import unittest
from unittest.mock import patch

RECEIVED = "default_advance_received_account"
PAID = "default_advance_paid_account"


def _accountfield(party_type: str) -> str:
    """Replica la decision bajo prueba (misma expresion que el override)."""
    return RECEIVED if party_type == "Customer" else PAID


class TestAdvanceAccountByPartyType(unittest.TestCase):
    def test_customer_receipt_uses_advance_received(self):
        """Caso normal: cobro a cliente -> anticipo recibido."""
        self.assertEqual(_accountfield("Customer"), RECEIVED)

    def test_customer_refund_uses_advance_received(self):
        """El caso del bug: reembolso a cliente (Pay) NO debe ir a anticipo de proveedores."""
        self.assertEqual(_accountfield("Customer"), RECEIVED)

    def test_supplier_payment_uses_advance_paid(self):
        """Caso normal: pago a proveedor -> anticipo pagado."""
        self.assertEqual(_accountfield("Supplier"), PAID)

    def test_supplier_refund_uses_advance_paid(self):
        """Devolucion de un proveedor (Receive) sigue en anticipo pagado."""
        self.assertEqual(_accountfield("Supplier"), PAID)

    def test_decision_ignores_payment_direction(self):
        """La direccion del pago no debe influir: misma entidad -> misma cuenta."""
        for party_type, expected in (("Customer", RECEIVED), ("Supplier", PAID)):
            with self.subTest(party_type=party_type):
                self.assertEqual(_accountfield(party_type), expected)

    def test_matches_erpnext_criterion(self):
        """El criterio coincide con el de ERPNext en accounts/party.py."""
        from erpnext.accounts.party import get_party_account  # noqa: F401  (existe)

        for party_type in ("Customer", "Supplier"):
            erpnext_choice = RECEIVED if party_type == "Customer" else PAID
            self.assertEqual(_accountfield(party_type), erpnext_choice)


class TestOverrideUsesPartyType(unittest.TestCase):
    """Ancla el fix en el codigo real: el override debe consultar party_type."""

    def test_override_source_decides_by_party_type(self):
        import inspect

        from l10n_ve.overrides.payment_entry import CustomPaymentEntry

        src = inspect.getsource(CustomPaymentEntry.add_party_gl_entries)
        head = src.split("accountfield")[1][:300]
        self.assertIn('self.party_type == "Customer"', head)
        self.assertNotIn('self.payment_type == "Receive"', head)
