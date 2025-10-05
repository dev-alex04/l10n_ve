import frappe
from frappe import _, _dict
from frappe.utils import flt, get_link_to_form

import erpnext
from erpnext.stock import get_warehouse_account_map
from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals


class CustomPurchaseInvoice(PurchaseInvoice):

    def on_cancel(self) -> None:
        super().on_cancel()

        has_iva_withholding = frappe.db.exists(
            "VAT Withholding Voucher Item",
            {"purchase_invoice": self.name }
        )

        has_islr_withholding = frappe.db.exists(
            "ISLR Withholding Voucher Item",
            {"purchase_invoice": self.name }
        )

        reasons = []
        if has_iva_withholding:
            reasons.append("un Comprobante de retención de IVA")

        if has_islr_withholding:
            reasons.append("un Comprobante de retención de ISLR")

        if reasons:
            message = "No se puede cancelar esta factura. Está asociada a " + " y a ".join(reasons) + "."
            frappe.throw(message, frappe.ValidationError)

    def validate(self) -> None:
        super().validate()

        self.validate_duplicate_invoice_numbers()
        self.set_affected_invoice_number()

        has_taxable_items = False
        for item in self.items:
            if not item.vat_exempt:
                has_taxable_items = True
                break

        if not has_taxable_items and self.taxes_and_charges:
            self.taxes_and_charges = None
            self.set("taxes", [])

            self.apply_tds = 0

        has_vat_charge = False
        for tax in self.taxes:
            if tax.charge_type == 'VAT':
                has_vat_charge = True
                break

        if not has_vat_charge and self.apply_tds == 1:
            self.set("taxes", [])
            self.apply_tds = 0

        if self.is_debit_note:
            self.validate_debit_note_number()
            self.validate_affected_invoice_number()
        elif self.is_return:
            self.validate_credit_note_number()

    def validate_affected_invoice_number(self) -> None:
        if self.is_debit_note:
            if not self.affected_invoice_number:
                frappe.throw("El número de la Factura Afectada es obligatorio.")
            else:
                affected_invoice_exists = frappe.db.exists(
                    "Purchase Invoice", {
                        "supplier": self.supplier,
                        "bill_no": self.affected_invoice_number,
                        "name": ["!=", self.name],
                        "is_debit_note": 0,
                        "is_return": 0
                    }
                )

                if not affected_invoice_exists:
                    frappe.throw("La factura con el número de Factura Afectada no existe.")

    def validate_debit_note_number(self) -> None:
        if self.is_debit_note:
            if not self.debit_note_no:
                frappe.throw("El número de la Nota de Débito es obligatorio para una Nota de Débito.")

            debit_note_exists = frappe.db.exists(
                "Purchase Invoice", {
                    "debit_note_no": self.debit_note_no,
                    "supplier": self.supplier,
                    "is_debit_note": 1,
                    "name": ["!=", self.name]
                }
            )

            if debit_note_exists:
                frappe.throw(f"Ya existe una Nota de Débito con el número {self.debit_note_no} para este proveedor.")

    def validate_credit_note_number(self) -> None:
        if self.is_return:
            if not self.credit_note_no:
                frappe.throw("El número de la Nota de Crédito es obligatorio para una Nota de Crédito.")

            credit_note_exists = frappe.db.exists(
                "Purchase Invoice", {
                    "credit_note_no": self.credit_note_no,
                    "supplier": self.supplier,
                    "is_return": 1,
                    "name": ["!=", self.name]
                }
            )

            if credit_note_exists:
                frappe.throw(f"Ya existe una Nota de Crédito con el número {self.credit_note_no} para este proveedor.")

    def validate_duplicate_invoice_numbers(self) -> None:
        if self.bill_no:
            filters_bill_no = {
                'docstatus': ['!=', 2],
                'bill_no': self.bill_no,
                'supplier': self.supplier,
                'name': ('!=', self.name),
            }

            if frappe.db.get_all("Purchase Invoice", filters=filters_bill_no):
                message = "El número de factura ya se encuentra asignado a otra factura del mismo proveedor."
                frappe.throw(message)

        if self.bill_control:
            filters_bill_control = {
                'docstatus': ['!=', 2],
                'name': ['!=', self.name],
                'supplier': self.supplier,
                'bill_control': self.bill_control,
            }

            if frappe.db.get_all("Purchase Invoice", filters=filters_bill_control):
                message = "El número de control ya se encuentra asignado a otra factura del mismo proveedor."
                frappe.throw(message)

    def set_affected_invoice_number(self) -> None:
        if self.is_return or self.is_debit_note :

            if self.return_against:
                self.affected_invoice_number  = frappe.db.get_value(
                    "Purchase Invoice",
                    self.return_against,
                    "bill_no"
                )

    def calculate_total_withholding(self) -> None:
        self.total_withholding = 0.0

        if not self.get("taxes"):
            return

        for tax in self.get("taxes"):

            if not tax.is_tax_withholding_account:
                continue

            self.total_withholding += tax.get('tax_amount', 0)

    @frappe.whitelist()
    def set_islr_concept(self, tabulator_name: str) -> None:

        tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

        type_of_person: str = frappe.db.get_value("Supplier",
                                                  self.supplier,
                                                  "type_of_person")

        account_head: str = frappe.db.get_value("Company",
                                                  self.company,
                                                  "purchase_islr_account")

        for aliquot in tabulator.aliquot:
            if type_of_person == aliquot.types_of_person:

                self.append("taxes", {
                    "category": "Total",
                    "charge_type": "ISLR",
                    "add_deduct_tax": "Deduct",
                    "rate": aliquot.aliquot,
                    "code": tabulator.codigo,
                    "account_head": account_head,
                    "is_tax_withholding_account": True,
                    "subtracting": aliquot.subtracting,
                    "description": tabulator.descripcion,
                    "percentage_base": aliquot.percentage_base,
                })

        self.save()
        return self.name

    # ------------------------------ OVERRIDES ------------------------------ #

    def set_taxes_and_charges(self) -> None:
        super().set_taxes_and_charges()

        self.set_tax_withholding_ve()

    def calculate_taxes_and_totals(self) -> None:
        taxes_and_totals_calculator = TaxesAndTotals(self)
        taxes_and_totals_calculator.calculate_total_exempt()

        self.calculate_total_withholding()

    def set_expense_account(self, for_validate=False) -> None:
            auto_accounting_for_stock = erpnext.is_perpetual_inventory_enabled(self.company)

            if auto_accounting_for_stock:
                stock_not_billed_account = self.get_company_default("stock_received_but_not_billed")
                stock_items = self.get_stock_items()

            self.asset_received_but_not_billed = None

            if self.update_stock:
                self.validate_item_code()
                self.validate_warehouse(for_validate)
                if auto_accounting_for_stock:
                    warehouse_account = get_warehouse_account_map(self.company)

            for item in self.get("items"):
                # in case of auto inventory accounting,
                # expense account is always "Stock Received But Not Billed" for a stock item
                # except opening entry, drop-ship entry and fixed asset items
                if (
                    auto_accounting_for_stock
                    and item.item_code in stock_items
                    and self.is_opening == "No"
                    and not item.is_fixed_asset
                    and (
                        not item.po_detail
                        or not frappe.db.get_value("Purchase Order Item",
                                                   item.po_detail,
                                                   "delivered_by_supplier")
                    )
                ):
                    if self.update_stock and item.warehouse and (not item.from_warehouse):
                        if (
                            for_validate
                            and item.expense_account
                            and item.expense_account != warehouse_account[item.warehouse]["account"]
                        ):
                            msg = _(
                                "Row {0}: Expense Head changed to {1} because account {2} is not linked to warehouse {3} or it is not the default inventory account"
                            ).format(
                                item.idx,
                                frappe.bold(warehouse_account[item.warehouse]["account"]),
                                frappe.bold(item.expense_account),
                                frappe.bold(item.warehouse),
                            )
                            # Se desactiva este mensaje hasta que sea revisado
                            # Por el contador
                            # frappe.msgprint(msg, title=_("Expense Head Changed"))
                        item.expense_account = warehouse_account[item.warehouse]["account"]
                    else:
                        # check if 'Stock Received But Not Billed' account is credited in Purchase receipt or not
                        if item.purchase_receipt:
                            negative_expense_booked_in_pr = frappe.db.sql(
                                """select name from `tabGL Entry`
                                where voucher_type='Purchase Receipt' and voucher_no=%s and account = %s""",
                                (item.purchase_receipt, stock_not_billed_account),
                            )

                            if negative_expense_booked_in_pr:
                                if (
                                    for_validate
                                    and item.expense_account
                                    and item.expense_account != stock_not_billed_account
                                ):
                                    msg = _(
                                        "Row {0}: Expense Head changed to {1} because expense is booked against this account in Purchase Receipt {2}"
                                    ).format(
                                        item.idx,
                                        frappe.bold(stock_not_billed_account),
                                        frappe.bold(item.purchase_receipt),
                                    )
                                    # Se desactiva este mensaje hasta que sea revisado
                                    # Por el contador
                                    # frappe.msgprint(msg, title=_("Expense Head Changed"))

                                item.expense_account = stock_not_billed_account
                        else:
                            # If no purchase receipt present then book expense in 'Stock Received But Not Billed'
                            # This is done in cases when Purchase Invoice is created before Purchase Receipt
                            if (
                                for_validate
                                and item.expense_account
                                and item.expense_account != stock_not_billed_account
                            ):
                                msg = _(
                                    "Row {0}: Expense Head changed to {1} as no Purchase Receipt is created against Item {2}."
                                ).format(
                                    item.idx, frappe.bold(stock_not_billed_account), frappe.bold(item.item_code)
                                )
                                msg += "<br>"
                                msg += _(
                                    "This is done to handle accounting for cases when Purchase Receipt is created after Purchase Invoice"
                                )
                                # Se desactiva este mensaje hasta que sea revisado
                                # Por el contador
                                # frappe.msgprint(msg, title=_("Expense Head Changed"))

                            item.expense_account = stock_not_billed_account
                elif item.is_fixed_asset:
                    account = None
                    if not item.pr_detail and item.po_detail:
                        receipt_item = frappe.get_cached_value(
                            "Purchase Receipt Item",
                            {
                                "purchase_order": item.purchase_order,
                                "purchase_order_item": item.po_detail,
                                "docstatus": 1,
                            },
                            ["name", "parent"],
                            as_dict=1,
                        )
                        if receipt_item:
                            item.pr_detail = receipt_item.name
                            item.purchase_receipt = receipt_item.parent

                    if item.pr_detail:
                        if not self.asset_received_but_not_billed:
                            self.asset_received_but_not_billed = self.get_company_default(
                                "asset_received_but_not_billed"
                            )

                        # check if 'Asset Received But Not Billed' account is credited in Purchase receipt or not
                        arbnb_booked_in_pr = frappe.db.get_value(
                            "GL Entry",
                            {
                                "voucher_type": "Purchase Receipt",
                                "voucher_no": item.purchase_receipt,
                                "account": self.asset_received_but_not_billed,
                            },
                            "name",
                        )
                        if arbnb_booked_in_pr:
                            account = self.asset_received_but_not_billed

                    if not account:
                        account_type = (
                            "capital_work_in_progress_account"
                            if is_cwip_accounting_enabled(item.asset_category)
                            else "fixed_asset_account"
                        )
                        account = get_asset_category_account(
                            account_type, item=item.item_code, company=self.company
                        )
                        if not account:
                            form_link = get_link_to_form("Asset Category", item.asset_category)
                            frappe.throw(
                                _("Please set Fixed Asset Account in {} against {}.").format(
                                    form_link, self.company
                                ),
                                title=_("Missing Account"),
                            )
                    item.expense_account = account
                elif not item.expense_account and for_validate:
                    frappe.throw(_("Expense account is mandatory for item {0}").format(item.item_code or item.item_name))

    def set_tax_withholding(self) -> None:
        """
        Se inactiva la funcion nativa para obtener las retenciones.
        La funcion set_tax_withholding_ve  se encargara de esto
        """
        return

    # TODO: Refactorizar a una sola funcion
    def set_tax_withholding_ve(self) -> None:

        if not bool(frappe.db.get_value('Company',
                                        self.company,
                                        'is_special_taxpayer')):
            return

        withholding_category_name = frappe.db.get_value("Supplier",
                                                        self.supplier,
                                                        "tax_withholding_category")
        if not withholding_category_name:
            return

        withholding_category = frappe.get_doc("Tax Withholding Category",
                                              withholding_category_name)

        withholding: _dict = withholding_category.get_withholding(self.company,
                                                                  self.doctype)
        if self.is_return:
            if not self.return_against:
                return

            withholding['description'] = \
                f'{withholding.description} por Nota de Crédito contra factura {self.affected_invoice_number}'

        elif self.is_debit_note:

            withholding.description = \
                f'{withholding["description"]} por Nota de Crédito contra factura {self.affected_invoice_number}'

        # Primero se limpia la tabla de impuestos
        # Dejando solo los impuestos que no sean retencion de IVA
        self.taxes = [
            tax
            for tax in self.taxes or []
            if tax.charge_type != withholding.charge_type
        ]

        self.append("taxes", withholding)

    def make_gl_entries_for_tax_withholding(self, gl_entries) -> None:
        """
        Tax withholding amount is not part of supplier invoice.
        Separate supplier GL Entry for correct reporting.
        """

        for tax in self.get("taxes") or []:

            if not tax.is_tax_withholding_account or not tax.tax_amount:
                continue

            if (
                self.is_return
                and self.return_against
                and not self.update_outstanding_for_self
            ):
                against_voucher = self.return_against
            else:
                against_voucher = self.name

            debit_or_credit = "debit" if self.docstatus == 1 else "credit"

            gl = {
                "account": self.credit_to,
                "against": tax.account_head,
                "against_voucher": against_voucher,
                "against_voucher_type": self.doctype,
                "cost_center": self.cost_center,
                debit_or_credit: tax.tax_amount,
                f"{debit_or_credit}_in_account_currency": tax.tax_amount,
                f"{debit_or_credit}_in_transaction_currency": tax.tax_amount,
                "due_date": self.due_date,
                "party": self.supplier,
                "party_type": "Supplier",
                "project": self.project,
                "remarks": self.remarks,
                "_skip_merge": True,
            }

            gl_entries.append(self.get_gl_dict(gl, self.party_account_currency, item=self))
