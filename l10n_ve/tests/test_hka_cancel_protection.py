# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para _block_cancel_if_invoice_sent_to_hka().

Cubre:
- Bloqueo: facturas con JSON HKA en remarks (imprentaDigital)
- Permitido: facturas internas, sin remarks, Purchase Invoice refs
- Edge case: PE con mixed refs (interna + HKA)

Discriminador: el campo 'remarks' de Sales Invoice contiene JSON
de respuesta HKA con la clave 'imprentaDigital'. Las facturas con
bill_no asignado manualmente NO son bloqueadas.
"""

import json

import frappe
from frappe import _dict
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, MagicMock

from l10n_ve.overrides.payment_entry import CustomPaymentEntry


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

HKA_REMARKS_SAMPLE: str = json.dumps({
    "resultado": {
        "imprentaDigital": "THE FACTORY HKA VENEZUELA, C.A.",
        "serie": "MIR-01",
        "numeroDocumento": "2900",
        "numeroControl": "00-00233094",
    },
    "codigo": "200",
    "mensaje": "Documento procesado correctamente"
})


def _make_pe_reference(
    doctype: str = "Sales Invoice", name: str = "ACC-SINV-2026-00001"
) -> _dict:
    """Crea un mock de Payment Entry Reference (child table).

    Campos clave del schema:
        reference_doctype (Link, *) -> DocType
        reference_name (Dynamic Link, *) -> reference_doctype
    """
    return _dict({
        "reference_doctype": doctype,
        "reference_name": name,
    })


def _make_si_data(
    name: str = "ACC-SINV-2026-00001",
    remarks: str = None,
    bill_no: str = None,
    bill_control: str = None,
) -> _dict:
    """Mock del resultado de frappe.get_all('Sales Invoice') para HKA check.

    Campos consultados en _block_cancel_if_invoice_sent_to_hka:
        name, bill_no (Custom Field), bill_control (Custom Field), remarks
    """
    return _dict({
        "name": name,
        "bill_no": bill_no,
        "bill_control": bill_control,
        "remarks": remarks,
    })


def _get_pe_instance(references: list = None) -> CustomPaymentEntry:
    """Crea una instancia mock de CustomPaymentEntry sin tocar la BD."""
    pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
    pe.name = "ACC-PAY-2026-00001"
    pe.flags = frappe._dict()
    pe.meta = MagicMock()

    # Simular self.get("references") usado en el método
    ref_list: list = references or []

    def _get(key, default=None):
        if key == "references":
            return ref_list
        return default
    pe.get = _get

    return pe


# ═══════════════════════════════════════════════════════════════════
# Bloqueo por HKA
# ═══════════════════════════════════════════════════════════════════

class TestHKACancelProtectionBlock(FrappeTestCase):
    """Tests que verifican el bloqueo de cancelación para facturas HKA."""

    @patch("frappe.get_all")
    def test_blocks_cancel_when_hka_json_in_remarks(
        self, mock_get_all: MagicMock
    ) -> None:
        """Factura con imprentaDigital en remarks → frappe.throw()."""
        pe = _get_pe_instance(references=[
            _make_pe_reference("Sales Invoice", "ACC-SINV-2026-00001")
        ])
        mock_get_all.return_value = [
            _make_si_data(
                name="ACC-SINV-2026-00001",
                remarks=HKA_REMARKS_SAMPLE,
                bill_no="2900",
                bill_control="00-00233094",
            )
        ]

        with self.assertRaises(frappe.exceptions.ValidationError):
            pe._block_cancel_if_invoice_sent_to_hka()

    @patch("frappe.get_all")
    def test_blocks_cancel_with_real_hka_json(
        self, mock_get_all: MagicMock
    ) -> None:
        """Usa JSON de producción completo para validar el parser."""
        real_remarks: str = json.dumps({
            "name": "ACC-SINV-2026-07679",
            "owner": "ylopez@galanet.com.ve",
            "creation": "2026-05-04 08:25:55.412295",
            "modified": "2026-05-11 17:35:33.466080",
            "modified_by": "Administrator",
            "docstatus": 1,
            "bill_no": "2900",
            "bill_control": "00-00233094",
            "resultado": {
                "imprentaDigital": "THE FACTORY HKA VENEZUELA, C.A.",
                "serie": "MIR-01",
            }
        })
        pe = _get_pe_instance(references=[
            _make_pe_reference("Sales Invoice", "ACC-SINV-2026-07679")
        ])
        mock_get_all.return_value = [
            _make_si_data(
                name="ACC-SINV-2026-07679",
                remarks=real_remarks,
                bill_no="2900",
                bill_control="00-00233094",
            )
        ]

        with self.assertRaises(frappe.exceptions.ValidationError):
            pe._block_cancel_if_invoice_sent_to_hka()


# ═══════════════════════════════════════════════════════════════════
# Cancelación permitida
# ═══════════════════════════════════════════════════════════════════

class TestHKACancelProtectionAllow(FrappeTestCase):
    """Tests que verifican que la cancelación es permitida para facturas internas."""

    @patch("frappe.get_all")
    def test_allows_cancel_when_no_remarks(
        self, mock_get_all: MagicMock
    ) -> None:
        """Factura sin remarks (None): cancelación permitida."""
        pe = _get_pe_instance(references=[
            _make_pe_reference("Sales Invoice", "ACC-SINV-2026-00002")
        ])
        mock_get_all.return_value = [
            _make_si_data(name="ACC-SINV-2026-00002", remarks=None)
        ]

        # No debe lanzar excepción
        pe._block_cancel_if_invoice_sent_to_hka()

    @patch("frappe.get_all")
    def test_allows_cancel_when_internal_bill_no(
        self, mock_get_all: MagicMock
    ) -> None:
        """Factura con bill_no manual pero sin HKA: permitida."""
        pe = _get_pe_instance(references=[
            _make_pe_reference("Sales Invoice", "ACC-SINV-2026-00003")
        ])
        mock_get_all.return_value = [
            _make_si_data(
                name="ACC-SINV-2026-00003",
                bill_no="123",
                remarks="Factura interna sin HKA",
            )
        ]

        pe._block_cancel_if_invoice_sent_to_hka()

    @patch("frappe.get_all")
    def test_allows_cancel_when_remarks_plain_text(
        self, mock_get_all: MagicMock
    ) -> None:
        """Factura con remarks de texto libre: permitida."""
        pe = _get_pe_instance(references=[
            _make_pe_reference("Sales Invoice", "ACC-SINV-2026-00004")
        ])
        mock_get_all.return_value = [
            _make_si_data(
                name="ACC-SINV-2026-00004",
                remarks="Pago recibido por transferencia bancaria",
            )
        ]

        pe._block_cancel_if_invoice_sent_to_hka()

    def test_allows_cancel_when_no_si_references(self) -> None:
        """PE sin referencias a Sales Invoice: sale temprano."""
        pe = _get_pe_instance(references=[])

        # No debe lanzar excepción ni llamar a frappe.get_all
        pe._block_cancel_if_invoice_sent_to_hka()

    @patch("frappe.get_all")
    def test_allows_cancel_for_purchase_invoice_refs(
        self, mock_get_all: MagicMock
    ) -> None:
        """PE con refs a Purchase Invoice: protección HKA no aplica."""
        pe = _get_pe_instance(references=[
            _make_pe_reference("Purchase Invoice", "ACC-PINV-2026-00001"),
            _make_pe_reference("Purchase Invoice", "ACC-PINV-2026-00002"),
        ])

        pe._block_cancel_if_invoice_sent_to_hka()

        # frappe.get_all no debería haber sido llamado (sin SI refs)
        mock_get_all.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# Mixed refs
# ═══════════════════════════════════════════════════════════════════

class TestHKACancelProtectionMixed(FrappeTestCase):
    """Tests con referencias mixtas (internas + HKA)."""

    @patch("frappe.get_all")
    def test_blocks_only_hka_invoice_in_mixed_refs(
        self, mock_get_all: MagicMock
    ) -> None:
        """PE con 1 factura interna + 1 HKA: bloquea por la HKA."""
        pe = _get_pe_instance(references=[
            _make_pe_reference("Sales Invoice", "ACC-SINV-2026-INTERNAL"),
            _make_pe_reference("Sales Invoice", "ACC-SINV-2026-HKA"),
        ])
        mock_get_all.return_value = [
            _make_si_data(
                name="ACC-SINV-2026-INTERNAL",
                remarks="Factura interna",
            ),
            _make_si_data(
                name="ACC-SINV-2026-HKA",
                remarks=HKA_REMARKS_SAMPLE,
                bill_no="2901",
                bill_control="00-00233095",
            ),
        ]

        with self.assertRaises(frappe.exceptions.ValidationError):
            pe._block_cancel_if_invoice_sent_to_hka()
