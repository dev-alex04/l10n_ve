import frappe
from frappe import _, _dict
from frappe.utils import flt, get_link_to_form

from erpnext.accounts.utils import get_account_currency


import erpnext
from erpnext.stock import get_warehouse_account_map
from erpnext.accounts.utils import get_account_currency
from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account

from l10n_ve.utils.utils import validate_return_in_same_month
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals


class CustomPurchaseInvoice(PurchaseInvoice):

    def on_cancel(self) -> None:
        super().on_cancel()

        #TODO: Mover a una funcion

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

    def before_submit(self) -> None:
        super().before_submit()
        self.set_title_field()

    def validate(self) -> None:
        super().validate()

        self.validate_duplicate_invoice_numbers()
        self.set_affected_invoice_number()
        self.validate_return_in_same_month()

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

        if self.is_debit_note:
            self.validate_debit_note_number()
            self.validate_affected_invoice_number()
        elif self.is_return:
            self.validate_credit_note_number()

    def validate_affected_invoice_number(self) -> None:
        # Revisa si hace falta validar con is_return

        if not self.is_debit_note:
            return

        if not self.affected_invoice_number:
            frappe.throw("El número de la Factura Afectada es obligatorio.")
        else:
            affected_invoice_exists = bool(frappe.db.exists(
                "Purchase Invoice", {
                    "supplier": self.supplier,
                    "bill_no": self.affected_invoice_number,
                    "name": ["!=", self.name],
                    "is_debit_note": 0,
                    "is_return": 0
                }
            ))

            if not affected_invoice_exists:
                frappe.throw("La factura con el número de Factura Afectada no existe.")

    def validate_debit_note_number(self) -> None:
        if not self.is_debit_note:
            return

        if not self.debit_note_no:
            frappe.throw("El número de la Nota de Débito es obligatorio para una Nota de Débito.")

        debit_note_exists = bool(frappe.db.exists(
            "Purchase Invoice", {
                "debit_note_no": self.debit_note_no,
                "supplier": self.supplier,
                "is_debit_note": 1,
                "name": ["!=", self.name]
            }
        ))

        if debit_note_exists:
            frappe.throw(f"Ya existe una Nota de Débito con el número {self.debit_note_no} para este proveedor.")

    def validate_credit_note_number(self) -> None:

        if not self.is_return:
            return

        if not self.credit_note_no:
            frappe.throw("El número de la Nota de Crédito es obligatorio para una Nota de Crédito.")

        credit_note_exists = bool(frappe.db.exists(
            "Purchase Invoice", {
                "credit_note_no": self.credit_note_no,
                "supplier": self.supplier,
                "is_return": 1,
                "name": ["!=", self.name]
            }
        ))

        if credit_note_exists:
            frappe.throw(f"Ya existe una Nota de Crédito con el número {self.credit_note_no} para este proveedor.")

    def validate_return_in_same_month(self):
        """
        Valida que una Nota de Crédito o Débito se cree en el mismo mes
        que la factura original a la que hace referencia.
        Llama a la función centralizada en utils.
        """
        validate_return_in_same_month(self)

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

    # TODO: Mover esto a una sola funcion
    def calculate_total_withholding(self) -> None:

        self.total_withholding = 0.0

        self.total_withholding = sum([
            tax.tax_amount
            for tax in self.taxes or []
            if tax.is_tax_withholding_account
        ])

    @frappe.whitelist()
    def set_islr_concept(self, tabulator_name: str) -> None:

        tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

        type_of_person: str = frappe.db.get_value("Supplier",
                                                  self.supplier,
                                                  "type_of_person")

        account_head: str = frappe.db.get_value("Company",
                                                  self.company,
                                                  "purchase_islr_account")

        # para evitar duplicados.
        self.taxes = [
            tax for tax in self.taxes or []
            if tax.get('charge_type') != "ISLR"
        ]

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
                break

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
            if tax.get('charge_type') != withholding.charge_type
        ]

        self.append("taxes", withholding)

    def make_tax_gl_entries(self, gl_entries) -> None:

        """
        Override para solo hacer los asientos que NO sean de retenciones
        """

        # tax table gl entries
        valuation_tax = {}

        for tax in self.get("taxes"):

            if tax.is_tax_withholding_account or not tax.tax_amount:
                continue

            amount, base_amount = self.get_tax_amounts(tax, None)
            if tax.category in ("Total", "Valuation and Total") and flt(base_amount):
                account_currency = get_account_currency(tax.account_head)

                dr_or_cr = "debit" if tax.add_deduct_tax == "Add" else "credit"

                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account": tax.account_head,
                            "against": self.supplier,
                            dr_or_cr: base_amount,
                            dr_or_cr + "_in_account_currency": base_amount
                            if account_currency == self.company_currency
                            else amount,
                            dr_or_cr + "_in_transaction_currency": amount,
                            "cost_center": tax.cost_center,
                        },
                        account_currency,
                        item=tax,
                    )
                )
            # accumulate valuation tax
            if (
                self.is_opening == "No"
                and tax.category in ("Valuation", "Valuation and Total")
                and flt(base_amount)
                and not self.is_internal_transfer()
            ):
                if self.auto_accounting_for_stock and not tax.cost_center:
                    frappe.throw(
                        _("Cost Center is required in row {0} in Taxes table for type {1}").format(
                            tax.idx, _(tax.category)
                        )
                    )
                valuation_tax.setdefault(tax.name, 0)
                valuation_tax[tax.name] += (tax.add_deduct_tax == "Add" and 1 or -1) * flt(base_amount)

        if self.is_opening == "No" and self.negative_expense_to_be_booked and valuation_tax:
            # credit valuation tax amount in "Expenses Included In Valuation"
            # this will balance out valuation amount included in cost of goods sold

            total_valuation_amount = sum(valuation_tax.values())
            amount_including_divisional_loss = self.negative_expense_to_be_booked
            i = 1

            for tax in self.get("taxes"):

                if tax.is_tax_withholding_account:
                    continue

                if valuation_tax.get(tax.name):
                    if i == len(valuation_tax):
                        applicable_amount = amount_including_divisional_loss
                    else:
                        applicable_amount = self.negative_expense_to_be_booked * (
                            valuation_tax[tax.name] / total_valuation_amount
                        )
                        amount_including_divisional_loss -= applicable_amount

                    gl_entries.append(
                        self.get_gl_dict(
                            {
                                "account": tax.account_head,
                                "cost_center": tax.cost_center,
                                "against": self.supplier,
                                "credit": applicable_amount,
                                "credit_in_transaction_currency": flt(
                                    applicable_amount / self.conversion_rate,
                                    frappe.get_precision("Purchase Invoice Item", "item_tax_amount"),
                                ),
                                "remarks": self.remarks or _("Accounting Entry for Stock"),
                            },
                            item=tax,
                        )
                    )

                    i += 1

        if self.auto_accounting_for_stock and self.update_stock and valuation_tax:
            for tax in self.get("taxes"):

                if tax.is_tax_withholding_account:
                    continue

                if valuation_tax.get(tax.name):
                    gl_entries.append(
                        self.get_gl_dict(
                            {
                                "account": tax.account_head,
                                "cost_center": tax.cost_center,
                                "against": self.supplier,
                                "credit": valuation_tax[tax.name],
                                "credit_in_transaction_currency": flt(
                                    valuation_tax[tax.name] / self.conversion_rate,
                                    frappe.get_precision("Purchase Invoice Item", "item_tax_amount"),
                                ),
                                "remarks": self.remarks or _("Accounting Entry for Stock"),
                            },
                            item=tax,
                        )
                    )

    def set_title_field(self):
        super().set_title_field()
        if self.docstatus == 0:
            return
        if self.is_return:
            self.title = self.credit_note_no

        elif self.is_debit_note:
            self.title = self.debit_note_no

        else:
            self.title = self.bill_no

    def make_gl_entries_for_tax_withholding(self, gl_entries) -> None:
        """
        Se inactiva esta funcion, ya que aqui no se haran los asientos de las retenciones
        """
        return

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
