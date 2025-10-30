import frappe
import erpnext
from erpnext.stock import get_warehouse_account_map
from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder

from l10n_ve.controllers.taxes_mixin import TaxesMixin

from frappe.utils import get_link_to_form


class CustomPurchaseOrder(TaxesMixin, PurchaseOrder):

    def validate(self) -> None:
        super().validate()

        #TODO: Mover a una funcion

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
