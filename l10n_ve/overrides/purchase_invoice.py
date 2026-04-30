import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form, getdate

import erpnext
from erpnext.stock import get_warehouse_account_map
from erpnext.accounts.utils import get_account_currency
from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.utils.utils import validate_return_in_same_month


class CustomPurchaseInvoice(TaxesMixin, PurchaseInvoice):

    def on_cancel(self) -> None:
        super().on_cancel()

        # TODO: Mover a una funcion

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

        if self.is_debit_note:
            self.validate_debit_note_number()
            self.validate_affected_invoice_number()
        elif self.is_return:
            self.validate_credit_note_number()

    def validate_supplier_invoice(self) -> None:

        if self.bill_date:
            if getdate(self.bill_date) > getdate(self.posting_date):
                frappe.throw(_("Supplier Invoice Date cannot be greater than Posting Date"))

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
            if not self.bill_no.isdigit():
                frappe.throw("El número de factura solo debe contener números.")

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
            if not self.bill_control.isdigit():
                frappe.throw("El número de control solo debe contener números.")

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

    def set_title_field(self) -> None:
        super().set_title_field()

        if self.docstatus == 0:
            return
        if self.is_return:
            self.title = self.credit_note_no

        elif self.is_debit_note:
            self.title = self.debit_note_no

        else:
            self.title = self.bill_no

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

    def get_gl_entries(self, warehouse_account=None):
        self.auto_accounting_for_stock = erpnext.is_perpetual_inventory_enabled(self.company)

        if self.auto_accounting_for_stock:
            self.stock_received_but_not_billed = self.get_company_default("stock_received_but_not_billed")
        else:
            self.stock_received_but_not_billed = None

        self.negative_expense_to_be_booked = 0.0
        gl_entries = []

        self.make_supplier_gl_entry(gl_entries)
        self.make_item_gl_entries(gl_entries)
        self.make_precision_loss_gl_entry(gl_entries)

        self.make_tax_gl_entries(gl_entries)
        self.make_internal_transfer_gl_entries(gl_entries)
        self.make_gl_entries_for_tax_withholding(gl_entries)

        self.make_payment_gl_entries(gl_entries)
        self.make_write_off_gl_entry(gl_entries)
        self.make_gle_for_rounding_adjustment(gl_entries)
        self.set_transaction_currency_and_rate_in_gl_map(gl_entries)

        for gl in gl_entries:
            gl.bill_control = self.bill_control
            gl.bill_no = self.bill_no or self.credit_note_no or self.debit_note_no

        return gl_entries

    def make_supplier_gl_entry(self, gl_entries):
        # Checked both rounding_adjustment and rounded_total
        # because rounded_total had value even before introduction of posting GLE based on rounded total
        grand_total = (
            self.rounded_total if (self.rounding_adjustment and self.rounded_total) else self.grand_total
        )

        base_grand_total = flt(
            self.base_rounded_total
            if (self.base_rounding_adjustment and self.base_rounded_total)
            else self.base_grand_total,
            self.precision("base_grand_total"),
        )

        if grand_total and not self.is_internal_transfer():
            self.add_supplier_gl_entry(gl_entries, base_grand_total, grand_total)

    def make_tax_gl_entries(self, gl_entries) -> None:
        """
        Override para solo hacer los asientos que NO sean de retenciones
        """

        # tax table gl entries
        valuation_tax = {}

        for tax in self.get("taxes"):
            # Las retenciones se manejan exclusivamente en make_gl_entries_for_tax_withholding
            if tax.is_tax_withholding_account:
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

    def make_gl_entries_for_tax_withholding(self, gl_entries) -> None:
        """Genera los asientos contables para retenciones de IVA e ISLR en compras.

        Solo crea el CRÉDITO a la cuenta de retención correspondiente.
        No toca la cuenta payable porque make_supplier_gl_entry ya usa
        el grand_total neto (descontadas ambas retenciones).

        Asiento resultante (ejemplo: Base 100 + IVA 16% = 116, Ret IVA 75%, Ret ISLR 5%):
          DÉBITO  Gasto           100  (make_item_gl_entries)
          DÉBITO  IVA Crédito      16  (make_tax_gl_entries)
          CRÉDITO Proveedor        99  (make_supplier_gl_entry, grand_total neto)
          CRÉDITO Retención IVA    12  (esta función)
          CRÉDITO Retención ISLR    5  (esta función)
          Total: 116 = 116 ✅
        """
        withholding_charge_types: tuple[str, ...] = ("VAT Withholding", "ISLR")

        for tax in self.get("taxes"):
            if tax.charge_type not in withholding_charge_types:
                continue

            base_tds_amount: float = abs(tax.base_tax_amount_after_discount_amount)
            tds_amount: float = abs(tax.tax_amount_after_discount_amount)

            if not flt(base_tds_amount) and not flt(tds_amount):
                continue

            # CRÉDITO a cuenta de retención (obligación fiscal)
            account_currency: str = get_account_currency(tax.account_head)
            gl_entries.append(
                self.get_gl_dict(
                    {
                        "account": tax.account_head,
                        "against": self.supplier,
                        "credit": base_tds_amount,
                        "credit_in_account_currency": base_tds_amount
                        if account_currency == self.company_currency
                        else tds_amount,
                        "credit_in_transaction_currency": tds_amount,
                        "cost_center": tax.cost_center,
                    },
                    account_currency,
                    item=tax,
                )
            )

    # ------------------------------------------------------------------ #
    # ISLR — Asignación manual de retención en Purchase Invoice            #
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def set_islr_concept(self, tabulator_name: str) -> None:
        """Calcula y agrega la retención de ISLR en la tabla de impuestos.

        Flujo:
        1. Valida prerequisitos (proveedor, cuenta ISLR)
        2. Busca la alícuota según tipo de persona del proveedor
        3. Calcula el monto de retención
        4. Agrega la fila ISLR como Deduct en Purchase Taxes and Charges
        """
        if not tabulator_name:
            frappe.throw(_("Debe seleccionar un concepto de ISLR."))

        type_of_person, islr_account = self._validate_islr_prerequisites()

        tabulator, aliquot_info = self._get_islr_aliquot(
            tabulator_name, type_of_person
        )

        self._validate_no_duplicate_islr(tabulator.codigo)

        islr_amount: float = self._calculate_islr_amount(aliquot_info)
        if islr_amount <= 0:
            frappe.msgprint(
                _("El monto de retención de ISLR calculado es cero o negativo. "
                  "No se agregó retención.")
            )
            return

        tax_row: dict = self._build_islr_tax_row(
            tabulator, aliquot_info, islr_amount, islr_account
        )
        self.append("taxes", tax_row)

        self._reindex_taxes()
        self.calculate_taxes_and_totals()
        self.save()

        frappe.msgprint(
            _("Retención de ISLR agregada: {0} ({1})").format(
                frappe.format_value(islr_amount, {"fieldtype": "Currency"}),
                tax_row["description"]
            ),
            indicator="green",
            alert=True
        )

    @frappe.whitelist()
    def remove_islr_concept(self) -> None:
        """Elimina la retención de ISLR de la tabla de impuestos."""
        has_islr: bool = any(
            tax.get("charge_type") == "ISLR" for tax in self.taxes or []
        )

        if not has_islr:
            frappe.msgprint(
                _("No hay retención de ISLR para eliminar."),
                indicator="orange",
                alert=True
            )
            return

        self._remove_existing_islr_taxes()
        self._reindex_taxes()
        self.calculate_taxes_and_totals()
        self.save()

        frappe.msgprint(
            _("Retención de ISLR eliminada exitosamente."),
            indicator="green",
            alert=True
        )

    # ------------------------------------------------------------------ #
    # Helpers privados para ISLR                                           #
    # ------------------------------------------------------------------ #

    def _validate_islr_prerequisites(self) -> tuple[str, str]:
        """Valida que el proveedor y la compañía tengan la configuración ISLR.

        Returns:
            tuple: (type_of_person, islr_account)
        """
        type_of_person: str = frappe.db.get_value(
            "Supplier", self.supplier, "type_of_person"
        ) or ""
        if not type_of_person:
            frappe.throw(
                _("El proveedor {0} no tiene configurado el Tipo de Persona.").format(
                    self.supplier
                )
            )

        islr_account: str = frappe.get_cached_value(
            "Company", self.company, "purchase_islr_account"
        ) or ""
        if not islr_account:
            frappe.throw(
                _("La cuenta de ISLR de compras no está configurada "
                  "en la Compañía {0}.").format(self.company)
            )

        return type_of_person, islr_account

    def _get_islr_aliquot(
        self, tabulator_name: str, type_of_person: str
    ) -> tuple:
        """Obtiene el tabulador y la alícuota correspondiente al tipo de persona.

        Returns:
            tuple: (tabulator_doc, aliquot_row)
        """
        tabulator = frappe.get_cached_doc("Tabulator ISLR", tabulator_name)
        if not tabulator.aliquot:
            frappe.throw(
                _("El tabulador {0} no tiene alícuotas configuradas.").format(
                    tabulator_name
                )
            )

        aliquot_info = next(
            (
                aq for aq in tabulator.aliquot
                if aq.types_of_person == type_of_person and flt(aq.aliquot) > 0
            ),
            None
        )
        if not aliquot_info:
            frappe.throw(
                _("No se encontró alícuota para el tipo de persona '{0}' "
                  "en el tabulador '{1}'.").format(type_of_person, tabulator_name)
            )

        return tabulator, aliquot_info

    def _calculate_islr_amount(self, aliquot_info) -> float:
        """Calcula el monto de retención ISLR sobre la base imponible.

        Fórmula: (total × %base / 100 × alícuota / 100) - sustraendo
        """
        base_amount: float = flt(self.total)
        tax_base: float = flt(
            base_amount * flt(aliquot_info.percentage_base) / 100, 2
        )
        return flt(
            (tax_base * flt(aliquot_info.aliquot) / 100)
            - flt(aliquot_info.subtracting), 2
        )

    def _build_islr_tax_row(
        self, tabulator, aliquot_info, islr_amount: float, islr_account: str
    ) -> dict:
        """Construye el diccionario para la fila ISLR en Purchase Taxes and Charges."""
        description: str = (
            f"ISLR {tabulator.codigo} {tabulator.descripcion}"
            f" ({flt(aliquot_info.aliquot)}%)"
        )

        return {
            "charge_type": "ISLR",
            "category": "Total",
            "add_deduct_tax": "Deduct",
            "description": description,
            "is_tax_withholding_account": True,
            "account_head": islr_account,
            "tax_amount": islr_amount,
            "base_tax_amount": islr_amount,
            "rate": flt(aliquot_info.aliquot),
            "percentage_base": flt(aliquot_info.percentage_base),
            "subtracting": flt(aliquot_info.subtracting),
            "code": tabulator.codigo,
            "tabulator_islr": tabulator.name,
        }

    def _validate_no_duplicate_islr(self, codigo: str) -> None:
        """Valida que no exista ya una retención ISLR con el mismo código."""
        existing_codes: list[str] = [
            tax.get("code", "") for tax in self.taxes or []
            if tax.get("charge_type") == "ISLR"
        ]
        if codigo in existing_codes:
            frappe.throw(
                _("Ya existe una retención ISLR con el código '{0}' "
                  "en esta factura.").format(codigo)
            )

    def _remove_existing_islr_taxes(self) -> None:
        """Elimina todas las filas ISLR existentes de la tabla de impuestos."""
        self.taxes = [
            tax for tax in self.taxes or []
            if tax.get("charge_type") != "ISLR"
        ]

    def _reindex_taxes(self) -> None:
        """Ordena y reindexar las filas de impuestos después de agregar o eliminar."""
        self._sort_and_reindex_taxes()


@frappe.whitelist()
def get_tabulators_by_person_type(
    doctype: str,
    txt: str,
    searchfield: str,
    start: int,
    page_len: int,
    filters: dict,
) -> list[tuple]:
    """Filtra Tabuladores ISLR que tengan alícuota para el tipo de persona indicado.

    Se usa como query del campo Link en el diálogo de ISLR de Purchase Invoice.
    Excluye tabuladores cuyos códigos ya están en la factura (existing_codes).
    """
    type_of_person: str = filters.get("type_of_person", "")
    existing_codes: list[str] = filters.get("existing_codes") or []

    # Asegurar que sea una lista (puede llegar como string JSON desde el frontend)
    if isinstance(existing_codes, str):
        import json
        try:
            existing_codes = json.loads(existing_codes)
        except (json.JSONDecodeError, TypeError):
            existing_codes = [existing_codes] if existing_codes else []

    exclusion_clause: str = ""
    if existing_codes:
        escaped: list[str] = [frappe.db.escape(code) for code in existing_codes]
        exclusion_clause = f"AND t.codigo NOT IN ({', '.join(escaped)})"

    return frappe.db.sql(
        f"""
        SELECT DISTINCT t.name, t.codigo, t.descripcion
        FROM `tabTabulator ISLR` t
        INNER JOIN `tabTabulator ISLR Aliquots` a ON a.parent = t.name
        WHERE a.types_of_person = %(type_of_person)s
            AND a.aliquot > 0
            AND (t.name LIKE %(txt)s OR t.codigo LIKE %(txt)s OR t.descripcion LIKE %(txt)s)
            {exclusion_clause}
        ORDER BY t.codigo
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        {
            "type_of_person": type_of_person,
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len,
        },
    )
