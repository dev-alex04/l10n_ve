# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""«Quitar Retención» en facturas de venta aprobadas.

El caso que la pidió lo reportó administración el 16-sep-2026: clientes con el check de
contribuyente especial marcado por error a los que se les descontó el 75% del IVA sin ser
agentes de retención. En producción ese día: 26 facturas de 14 clientes por Bs 187.670,20.
Hasta entonces, en una factura aprobada sólo había camino para AGREGAR una retención.

Lo que se fija acá son las tres cosas que la corrección a mano dejaba a medias: el reverso
tiene que devolverle la deuda al cliente --referenciando la factura, que es lo que hace que
ERPNext le suba el pendiente--, los totales guardados tienen que quedar de acuerdo con las
filas que sobrevivieron, y el aviso «Falta comprobante de retención» tiene que apagarse
cuando ya no queda retención que respaldar.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from l10n_ve.overrides.sales_invoice import (
    _clear_withholding_voucher_metadata,
    _create_sales_withholding_reversal_journal_entry,
    _refresh_sales_totals_after_withholding_change,
    remove_retroactive_sales_withholding,
)

_MOD = "l10n_ve.overrides.sales_invoice"
_INVOICE = "ACC-SINV-2026-26672"
_COMPANY = "Galanet Solution C.A."


def _tax_row(charge_type: str, amount: float, account: str) -> frappe._dict:
    return frappe._dict(
        name=f"fila-{charge_type}",
        charge_type=charge_type,
        add_deduct_tax="Deduct",
        account_head=account,
        tax_amount=amount / 827.0,
        base_tax_amount=amount,
        is_tax_withholding_account=1,
        description=charge_type,
    )


def _invoice(currency: str = "VEF", conversion_rate: float = 1.0) -> frappe._dict:
    """La factura de GRUPO DROSS, con sus tres filas de impuesto."""
    return frappe._dict(
        name=_INVOICE,
        bill_no="14197",
        company=_COMPANY,
        customer="GRUPO DROSS 2023 C.A",
        currency=currency,
        conversion_rate=conversion_rate,
        debit_to="1105001 - Cuentas por Cobrar Clientes - Galanet",
        cost_center="DC-01",
        net_total=51.72,
        base_net_total=42813.99,
        disable_rounded_total=1,
        taxes=[
            frappe._dict(
                name="fila-iva",
                charge_type="VAT",
                add_deduct_tax="Add",
                account_head="2105001 - IVA Debito Fiscal - Galanet",
                tax_amount=8.28,
                base_tax_amount=6850.24,
                is_tax_withholding_account=0,
                description="IVA 16%",
            ),
            _tax_row("VAT Withholding", 5137.68, "1110003 - Retencion de IVA Clientes - Galanet"),
            _tax_row("ISLR", 856.28, "1110002 - Retenciones ISLR Clientes - Galanet"),
        ],
    )


class TestWhatItRefuses(FrappeTestCase):
    def test_an_unknown_withholding_type_is_refused(self) -> None:
        with (
            patch(f"{_MOD}._require_withholding_permissions"),
            self.assertRaises(frappe.ValidationError),
        ):
            remove_retroactive_sales_withholding(_INVOICE, "MUNICIPAL", _COMPANY)

    def test_an_invoice_without_that_withholding_is_refused(self) -> None:
        """Quitar lo que no está sería asentar un reverso contra nada."""
        invoice = _invoice()
        invoice.taxes = [invoice.taxes[0]]  # solo el IVA débito fiscal
        with (
            patch(f"{_MOD}._require_withholding_permissions"),
            patch(f"{_MOD}.get_verified_invoice", return_value=invoice),
            patch("frappe.has_permission"),
            self.assertRaises(frappe.ValidationError),
        ):
            remove_retroactive_sales_withholding(_INVOICE, "VAT", _COMPANY)

    def test_a_foreign_currency_invoice_without_a_rate_is_refused(self) -> None:
        """Sin tasa, el reverso saldría por un monto inventado: mejor cortar."""
        with (
            patch(f"{_MOD}._require_withholding_permissions"),
            patch(f"{_MOD}.get_verified_invoice", return_value=_invoice("USD", 0)),
            patch("frappe.has_permission"),
            patch("frappe.get_cached_value", return_value="VEF"),
            self.assertRaises(frappe.ValidationError),
        ):
            remove_retroactive_sales_withholding(_INVOICE, "VAT", _COMPANY)


class TestWhatItRemoves(FrappeTestCase):
    def _run(self, withholding_type: str) -> tuple:
        invoice = _invoice()
        with (
            patch(f"{_MOD}._require_withholding_permissions"),
            patch(f"{_MOD}.get_verified_invoice", return_value=invoice),
            patch("frappe.has_permission"),
            patch("frappe.get_cached_value", return_value="VEF"),
            patch(
                f"{_MOD}._create_sales_withholding_reversal_journal_entry",
                return_value=frappe._dict(name="ACC-JV-2026-99999"),
            ) as entry,
            patch("frappe.db.delete") as deleted,
            patch(f"{_MOD}._refresh_sales_totals_after_withholding_change"),
            patch(f"{_MOD}._clear_withholding_voucher_metadata") as cleared,
        ):
            result = remove_retroactive_sales_withholding(_INVOICE, withholding_type, _COMPANY)
        return result, entry, deleted, cleared

    def test_only_the_requested_withholding_is_touched(self) -> None:
        """La otra retención de la factura no se toca en ningún caso."""
        _, entry, deleted, _ = self._run("VAT")
        self.assertEqual(entry.call_count, 1)
        self.assertEqual(flt(entry.call_args[0][3], 2), 5137.68)
        self.assertEqual(deleted.call_args[0][1]["name"], "fila-VAT Withholding")

    def test_the_islr_row_is_the_one_removed_when_islr_is_asked(self) -> None:
        _, entry, deleted, _ = self._run("ISLR")
        self.assertEqual(flt(entry.call_args[0][3], 2), 856.28)
        self.assertEqual(deleted.call_args[0][1]["name"], "fila-ISLR")

    def test_it_reports_the_reversal_entry(self) -> None:
        result, _, _, _ = self._run("VAT")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["journal_entries"], ["ACC-JV-2026-99999"])
        self.assertIn("IVA", result["msg"])

    def test_the_voucher_metadata_is_cleared_for_that_type(self) -> None:
        """El número que quedaba respaldaba una retención que ya no está."""
        _, _, _, cleared = self._run("VAT")
        self.assertEqual(cleared.call_args[0][1], "VAT Withholding")


class TestTheReversalEntry(FrappeTestCase):
    """El reverso es el espejo del asiento que registra la retención."""

    def _entry(self, currency: str = "VEF") -> MagicMock:
        entry = MagicMock()
        entry.accounts = []
        entry.append = lambda campo, fila: entry.accounts.append(fila)
        with (
            patch("frappe.new_doc", return_value=entry),
            patch("frappe.db.get_value", return_value="VEF"),
        ):
            _create_sales_withholding_reversal_journal_entry(
                _invoice(currency, 827.0), "VAT", "1110003 - Retencion de IVA Clientes - Galanet",
                5137.68, 827.0, "VEF", currency,
            )
        return entry

    def test_the_debt_goes_back_to_the_customer_against_the_invoice(self) -> None:
        """La referencia a la factura es lo que hace que ERPNext le suba el pendiente."""
        fila = self._entry().accounts[0]
        self.assertEqual(fila["party"], "GRUPO DROSS 2023 C.A")
        self.assertEqual(fila["reference_type"], "Sales Invoice")
        self.assertEqual(fila["reference_name"], _INVOICE)
        self.assertEqual(flt(fila["debit"], 2), 5137.68)

    def test_the_withholding_account_is_emptied(self) -> None:
        fila = self._entry().accounts[1]
        self.assertIn("1110003", fila["account"])
        self.assertEqual(flt(fila["credit"], 2), 5137.68)

    def test_the_entry_is_submitted(self) -> None:
        entry = self._entry()
        entry.insert.assert_called_once()
        entry.submit.assert_called_once()

    def test_the_remark_says_why(self) -> None:
        """Quien abra el asiento dentro de un año tiene que entender qué pasó."""
        entry = self._entry()
        self.assertIn(_INVOICE, entry.user_remark)
        self.assertIn("agente de retención", entry.user_remark)


class TestTheTotals(FrappeTestCase):
    """Los totales guardados tienen que quedar de acuerdo con las filas que sobrevivieron."""

    def _refresh(self, taxes: list) -> dict:
        invoice = _invoice()
        invoice.taxes = taxes
        with (
            patch("frappe.clear_document_cache"),
            patch("frappe.get_doc", return_value=invoice),
            patch("frappe.get_cached_value", return_value="VEF"),
            patch("frappe.db.set_value") as written,
        ):
            invoice.precision = lambda campo: 2
            _refresh_sales_totals_after_withholding_change(_INVOICE)
        return written.call_args[0][2]

    def test_without_withholdings_the_total_is_the_net_plus_vat(self) -> None:
        valores = self._refresh([_invoice().taxes[0]])
        self.assertEqual(flt(valores["base_grand_total"], 2), 49664.23)
        self.assertEqual(flt(valores["total_withholding"], 2), 0.0)

    def test_the_withholding_that_remains_still_subtracts(self) -> None:
        taxes = _invoice().taxes
        valores = self._refresh([taxes[0], taxes[2]])  # IVA + ISLR, sin la retención de IVA
        self.assertEqual(flt(valores["base_grand_total"], 2), 48807.95)

    def test_the_rounded_total_is_left_alone_when_the_invoice_disables_it(self) -> None:
        """18 de 424 facturas usan el total redondeado: si está apagado, no se inventa."""
        self.assertNotIn("rounded_total", self._refresh([_invoice().taxes[0]]))


class TestTheMissingVoucherWarning(FrappeTestCase):
    """El aviso se apaga solo cuando ya no queda retención sin comprobante."""

    def test_the_voucher_number_of_that_type_is_erased(self) -> None:
        with (
            patch("frappe.db.set_value") as written,
            patch("frappe.clear_document_cache"),
            patch("frappe.get_doc", return_value=_invoice()),
            patch(f"{_MOD}.refresh_missing_withholding_voucher"),
        ):
            _clear_withholding_voucher_metadata(_INVOICE, "VAT Withholding")
        self.assertEqual(written.call_args[0][2], "vat_withholding_voucher_number")
        self.assertIsNone(written.call_args[0][3])

    def test_the_warning_is_recalculated_on_the_invoice_as_it_is_now(self) -> None:
        """Se relee de la base: el documento en memoria todavía tiene la fila borrada."""
        invoice = _invoice()
        with (
            patch("frappe.db.set_value"),
            patch("frappe.clear_document_cache") as cache,
            patch("frappe.get_doc", return_value=invoice) as leido,
            patch(f"{_MOD}.refresh_missing_withholding_voucher") as recalculado,
        ):
            _clear_withholding_voucher_metadata(_INVOICE, "ISLR")
        cache.assert_called_once_with("Sales Invoice", _INVOICE)
        leido.assert_called_once_with("Sales Invoice", _INVOICE)
        recalculado.assert_called_once_with(invoice)
