import json

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, get_link_to_form, getdate

import erpnext
from erpnext.stock import get_warehouse_account_map
from erpnext.accounts.utils import get_account_currency
from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
from erpnext.accounts.doctype.sales_invoice.sales_invoice import (
    get_total_in_party_account_currency,
)

from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.utils.utils import validate_return_in_same_month


class CustomPurchaseInvoice(TaxesMixin, PurchaseInvoice):

    def before_cancel(self) -> None:
        self._block_cancel_if_has_active_notes()
        self._block_cancel_if_has_withholdings()
        super().before_cancel()

    def on_cancel(self) -> None:
        super().on_cancel()

    def _block_cancel_if_has_active_notes(self) -> None:
        """Bloquea la cancelación si la factura tiene NC o ND venezolana activa.

        Regla de negocio: para anular una factura con NC/ND, primero se
        deben anular los documentos dependientes.
        """
        active_nc: dict | None = frappe.db.get_value(
            "VE Purchase Credit Note",
            {"return_against": self.name, "docstatus": 1},
            ["name", "bill_no"],
            as_dict=True,
        )
        if active_nc:
            nc_bill: str = active_nc.bill_no or active_nc.name
            nc_link: str = (
                f'<a href="/app/ve-purchase-credit-note/{active_nc.name}">'
                f'{nc_bill}</a>'
            )
            frappe.throw(
                _(
                    "No se puede anular la factura <b>{0}</b> porque tiene "
                    "una Nota de Crédito activa: {1}. "
                    "Anule primero la Nota de Crédito."
                ).format(self.name, nc_link),
                title=_("Cancelación Bloqueada — NC Activa"),
            )

        active_nd: dict | None = frappe.db.get_value(
            "VE Purchase Debit Note",
            {"return_against": self.name, "docstatus": 1},
            ["name", "bill_no"],
            as_dict=True,
        )
        if active_nd:
            nd_bill: str = active_nd.bill_no or active_nd.name
            nd_link: str = (
                f'<a href="/app/ve-purchase-debit-note/{active_nd.name}">'
                f'{nd_bill}</a>'
            )
            frappe.throw(
                _(
                    "No se puede anular la factura <b>{0}</b> porque tiene "
                    "una Nota de Débito activa: {1}. "
                    "Anule primero la Nota de Débito."
                ).format(self.name, nd_link),
                title=_("Cancelación Bloqueada — ND Activa"),
            )

    def _block_cancel_if_has_withholdings(self) -> None:
        """Bloquea la cancelación si la factura está en un comprobante de retención activo."""
        reasons: list[str] = []

        if frappe.db.exists(
            "VAT Withholding Voucher Item",
            {"purchase_invoice": self.name,
            "docstatus": ["!=", 2]}
        ):
            reasons.append("un Comprobante de retención de IVA")

        if frappe.db.exists(
            "ISLR Withholding Voucher Item",
            {"purchase_invoice": self.name,
            "docstatus": ["!=", 2]}
        ):
            reasons.append("un Comprobante de retención de ISLR")

        if reasons:
            frappe.throw(
                _("No se puede cancelar esta factura. Está asociada a {0}.").format(
                    " y a ".join(reasons)
                ),
                frappe.ValidationError,
            )

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

        self._set_base_total_with_vat()

    def validate_supplier_invoice(self) -> None:

        if self.bill_date and getdate(self.bill_date) > getdate(self.posting_date):
            frappe.throw(
                _("La fecha del documento del proveedor ({0}) no puede ser mayor "
                  "a la fecha de contabilización ({1}).").format(
                    frappe.format(self.bill_date, {"fieldtype": "Date"}),
                    frappe.format(self.posting_date, {"fieldtype": "Date"}),
                )
            )

    def set_status(self, update: bool = False, status: str | None = None, update_modified: bool = True) -> None:
        """Extiende set_status para detectar NC/ND venezolanas vinculadas.

        ERPNext core solo busca Purchase Invoice con is_return=1 para marcar
        'Debit Note Issued'. Aquí se agrega la búsqueda en los DocTypes
        VE Purchase Credit Note y VE Purchase Debit Note.
        """
        super().set_status(update=False, status=status, update_modified=update_modified)

        if (
            self.status == "Paid"
            and not cint(self.is_return)
            and flt(self.outstanding_amount) <= 0
            and frappe.db.exists(
                "VE Purchase Credit Note",
                {"return_against": self.name, "docstatus": 1},
            )
        ):
            self.status = "Credit Note Issued"

        if (
            self.status not in ("Debit Note Issued",)
            and not cint(self.is_return)
            and not cint(self.is_debit_note)
            and frappe.db.exists(
                "VE Purchase Debit Note",
                {"return_against": self.name, "docstatus": 1},
            )
        ):
            self.status = "Debit Note Issued"

        if update:
            self.db_set("status", self.status, update_modified=update_modified)

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
            import re
            if re.search(r'\s', self.bill_no):
                frappe.throw(_("El número de factura no debe contener espacios."))

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
            import re
            if not re.match(r'^[A-Za-z0-9\-]+$', self.bill_control):
                frappe.throw("El número de control solo debe contener letras, números y guiones.")

            filters_bill_control = {
                'docstatus': ['!=', 2],
                'name': ['!=', self.name],
                'supplier': self.supplier,
                'bill_control': self.bill_control,
            }

            if not self.is_fiscal_device:
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

    def make_precision_loss_gl_entry(self, gl_entries) -> None:
        """Cancela el asiento de pérdida de precisión cuando el método VE es
        "Desde el total de la factura".

        El ancla (_anchor_item_base_amounts_ve) reduce base_net_amount
        intencionalmente respecto a net_amount × conversion_rate. ERPNext
        detecta esa brecha como "precision_loss" y crea un GL extra en la
        cuenta de redondeo, rompiendo el cuadre débito/crédito (la diferencia
        exacta de 2.17 en el caso de prueba). Con el ancla activa, la
        diferencia ya está absorbida por el base_grand_total anclado, por lo
        que no debe contabilizarse de nuevo.
        """
        from frappe.utils import flt as _flt
        from l10n_ve.controllers.taxes_and_totals import TAX_FROM_TOTAL

        if self._is_multicurrency_doc():
            method = frappe.get_cached_value(
                "Venezuela Account Settings", "Venezuela Account Settings",
                "tax_calculation_method",
            ) or ""
            if method == TAX_FROM_TOTAL:
                # El ancla ya absorbió la diferencia — no crear GL adicional
                return

        super().make_precision_loss_gl_entry(gl_entries)

    def _is_multicurrency_doc(self) -> bool:
        """True si el documento usa moneda distinta a la de la compañía."""
        try:
            company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
            return bool(company_currency) and self.currency != company_currency
        except Exception:
            return False

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

    def _grand_total_includes_withholding(self) -> bool:
        """Indica si base_grand_total incluye las retenciones (bruto).

        En Purchase Invoice, calculate_taxes_and_totals deduce las retenciones
        del grand_total → base_grand_total ya es neto → NO se necesita DR al AP.

        Subclases como VE Purchase Credit Note pueden override este método
        para retornar True cuando su grand_total es bruto.
        """
        return False

    def make_gl_entries_for_tax_withholding(self, gl_entries) -> None:
        """Genera los asientos contables para retenciones de IVA e ISLR en compras.

        Crea CRÉDITO a la cuenta de retención correspondiente.
        Opcionalmente crea DÉBITO al AP cuando grand_total incluye las retenciones
        (caso VE Purchase Credit Note donde grand_total es bruto).

        Flujo Purchase Invoice (grand_total neto = 99):
          DR Gasto 100 + DR IVA 16 = 116
          CR AP 99 + CR Ret IVA 12 + CR Ret ISLR 5 = 116 ✅

        Flujo VE Purchase Credit Note (grand_total bruto = 116):
          DR Gasto 100 + DR IVA 16 + DR AP 12 + DR AP 5 = 133
          CR AP 116 + CR Ret IVA 12 + CR Ret ISLR 5 = 133 ✅
        """
        withholding_charge_types: tuple[str, ...] = ("VAT Withholding", "ISLR")
        needs_ap_debit: bool = self._grand_total_includes_withholding()

        for tax in self.get("taxes"):
            if tax.charge_type not in withholding_charge_types:
                continue

            base_tds_amount: float = abs(tax.base_tax_amount_after_discount_amount)
            tds_amount: float = abs(tax.tax_amount_after_discount_amount)

            if not flt(base_tds_amount) and not flt(tds_amount):
                continue

            # DÉBITO a cuenta AP solo cuando grand_total no descuenta retenciones
            if needs_ap_debit:
                self.add_supplier_gl_entry(gl_entries, -base_tds_amount, -tds_amount)

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
        try:
            existing_codes = json.loads(existing_codes)
        except (json.JSONDecodeError, TypeError):
            existing_codes = [existing_codes] if existing_codes else []

    params: dict = {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len,
    }

    person_clause: str = ""
    if type_of_person:
        person_clause = "AND a.types_of_person = %(type_of_person)s"
        params["type_of_person"] = type_of_person

    exclusion_clause: str = ""
    if existing_codes:
        placeholders: list[str] = []
        for i, code in enumerate(existing_codes):
            key: str = f"exc_{i}"
            placeholders.append(f"%({key})s")
            params[key] = code
        exclusion_clause = f"AND t.codigo NOT IN ({', '.join(placeholders)})"

    return frappe.db.sql(
        f"""
        SELECT DISTINCT t.name, t.codigo, t.descripcion
        FROM `tabTabulator ISLR` t
        INNER JOIN `tabTabulator ISLR Aliquots` a ON a.parent = t.name
        WHERE a.aliquot > 0
            {person_clause}
            AND (t.name LIKE %(txt)s OR t.codigo LIKE %(txt)s OR t.descripcion LIKE %(txt)s)
            {exclusion_clause}
        ORDER BY t.codigo
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        params,
    )


def get_purchase_invoice_dashboard_data(data: dict) -> dict:
    """
    Extiende el dashboard de conexiones de Purchase Invoice para incluir
    las retenciones de IVA e ISLR y las Notas de Débito/Crédito de Compra de Venezuela.
    """
    # Mapeo de campos de relación para las notas
    non_std = data.setdefault("non_standard_fieldnames", {})
    non_std["VE Purchase Debit Note"] = "return_against"
    non_std["VE Purchase Credit Note"] = "return_against"

    # 1. Agregar a Retenciones
    withholdings_candidates = {_("Withholdings"), "Withholdings", _("Retenciones"), "Retenciones"}
    for group in data.setdefault("transactions", []):
        if group.get("label", "") in withholdings_candidates:
            items = group.setdefault("items", [])
            for item in ["VAT Withholding Voucher", "ISLR Withholding Voucher"]:
                if item not in items:
                    items.append(item)
            break
    else:
        data["transactions"].append({
            "label": _("Withholdings"),
            "items": ["VAT Withholding Voucher", "ISLR Withholding Voucher"],
        })

    # 2. Agregar a Devoluciones / Retornos
    returns_candidates = {_("Returns"), "Returns", _("Devoluciones"), "Devoluciones"}
    for group in data["transactions"]:
        if group.get("label", "") in returns_candidates:
            items = group.setdefault("items", [])
            for item in ["VE Purchase Credit Note", "VE Purchase Debit Note"]:
                if item not in items:
                    items.append(item)
            break
    else:
        data["transactions"].append({
            "label": _("Returns"),
            "items": ["VE Purchase Credit Note", "VE Purchase Debit Note"],
        })

    return data


def _resolve_exchange_gain_account(purchase_invoice: object, account: str | None) -> str:
    """
    Devuelve la cuenta de ganancia cambiaria a usar en el asiento.

    Si el llamador pasó una cuenta, se valida contra la compañía de la factura:
    el parámetro llega por un endpoint whitelisted, así que sin validar permitiría
    postear el diferencial contra cualquier cuenta del plan (patrimonio, banco…).
    Solo se aceptan cuentas de resultado, no de grupo, de la misma compañía.
    """
    if account:
        account_data = frappe.db.get_value(
            "Account",
            account,
            ["company", "is_group", "root_type"],
            as_dict=True,
        )

        if not account_data:
            frappe.throw(_("La cuenta {0} no existe").format(account))

        if account_data.company != purchase_invoice.company:
            frappe.throw(
                _("La cuenta {0} no pertenece a la compañía {1}").format(
                    account, purchase_invoice.company
                )
            )

        if account_data.is_group:
            frappe.throw(_("La cuenta {0} es de grupo y no admite movimientos").format(account))

        if account_data.root_type not in ("Income", "Expense"):
            frappe.throw(
                _(
                    "La cuenta {0} no es de resultado. El diferencial cambiario "
                    "solo puede registrarse contra una cuenta de ingreso o gasto."
                ).format(account)
            )

        return account

    accounts = frappe.get_cached_value(
        "Company",
        purchase_invoice.company,
        [
            "unrealized_exchange_gain_loss_account",
            "exchange_gain_loss_account",
        ],
        as_dict=True,
    )
    resolved = (
        accounts.unrealized_exchange_gain_loss_account
        or accounts.exchange_gain_loss_account
    )

    if not resolved:
        frappe.throw(
            _(
                "Configure la cuenta de Ganancia por Diferencial Cambiario "
                "en la Compañía {0}"
            ).format(purchase_invoice.company)
        )

    return resolved


@frappe.whitelist()
def create_purchase_exchange_difference_entry(docname: str, account: str = None) -> dict:
    """
    Crea un Journal Entry para liquidar el residual cambiario de una factura
    de compra parcialmente pagada.

    Caso de uso: la factura quedó con un saldo positivo mínimo (ej. 0,20 Bs)
    después de uno o más pagos. Ese residual se registra como Ganancia para
    la empresa (dejó de pagar ese monto).

    Asiento generado:
        Débito  → credit_to del proveedor  (reduce la deuda pendiente)
        Crédito → cuenta de ganancia cambiaria
    """
    purchase_invoice = frappe.get_doc("Purchase Invoice", docname)

    frappe.has_permission(
        "Purchase Invoice", ptype="write", doc=purchase_invoice, throw=True
    )
    frappe.has_permission("Journal Entry", ptype="submit", throw=True)

    if purchase_invoice.docstatus != 1:
        frappe.throw(_("La factura debe estar enviada para registrar diferencial cambiario"))

    outstanding = flt(purchase_invoice.outstanding_amount, 2)

    if outstanding <= 0:
        frappe.throw(_("La factura no tiene saldo residual positivo pendiente"))

    # El diferencial solo aplica al residual de una factura que YA recibió pagos.
    # Sobre una factura sin abonar, el botón mandaría el 100% del documento a la
    # cuenta de diferencial (Fase 1 acordada: "cualquier factura de compra
    # PARCIALMENTE pagada"). El umbral por monto es una fase posterior.
    total = get_total_in_party_account_currency(purchase_invoice)

    if outstanding >= total:
        frappe.throw(
            _(
                "La factura {0} no tiene pagos aplicados: su saldo pendiente ({1}) "
                "es el total del documento. El diferencial cambiario solo aplica "
                "al residual de una factura parcialmente pagada."
            ).format(purchase_invoice.name, fmt_money(outstanding, currency=purchase_invoice.party_account_currency))
        )

    exchange_gain_account = _resolve_exchange_gain_account(purchase_invoice, account)

    journal_entry = frappe.new_doc("Journal Entry")
    journal_entry.voucher_type = "Exchange Gain Or Loss"
    journal_entry.posting_date = purchase_invoice.posting_date
    journal_entry.company = purchase_invoice.company

    # Crédito en cuenta de ganancia cambiaria
    journal_entry.append("accounts", {
        "account": exchange_gain_account,
        "credit_in_account_currency": outstanding,
        "debit_in_account_currency": 0,
        "cost_center": purchase_invoice.cost_center,
    })

    # Débito en cuenta del proveedor (credit_to) — reduce la deuda pendiente
    journal_entry.append("accounts", {
        "account": purchase_invoice.credit_to,
        "party_type": "Supplier",
        "party": purchase_invoice.supplier,
        "debit_in_account_currency": outstanding,
        "credit_in_account_currency": 0,
        "reference_type": "Purchase Invoice",
        "reference_name": purchase_invoice.name,
        "cost_center": purchase_invoice.cost_center,
    })

    journal_entry.remark = (
        f"Diferencial cambiario por factura de compra {purchase_invoice.name}"
    )
    journal_entry.insert(ignore_permissions=True)
    journal_entry.submit()

    return {
        "status": "success",
        "journal_entry": journal_entry.name,
        "amount": outstanding,
    }


from l10n_ve.overrides.sales_invoice import (
    get_company_government_withholding_account,
    _require_withholding_permissions,
)


@frappe.whitelist()
def create_government_withholding_journal_entry_for_purchase_invoice(
    docname: str, amount: float, description: str = None, voucher_number: str = None
) -> dict:
    """Crea y somete un Asiento Contable (Journal Entry) de Retención Gubernamental para una Factura de Compra.

    Validaciones:
    1. Permisos del usuario.
    2. Existencia de la Factura de Compra.
    3. Factura en estado Sometida (docstatus == 1).
    4. Monto debe ser > 0.
    5. Monto no debe exceder el saldo pendiente de la factura ni el monto total de la factura.
    6. La empresa emisora debe tener configurada la cuenta contable de Retención Gubernamental.

    Asiento Contable:
    - Debe (Debit): Cuenta por Pagar al Proveedor (credit_to) con reference_type="Purchase Invoice", reference_name=doc.name, party_type="Supplier", party=supplier.
    - Haber (Credit): Cuenta de Retenciones Gubernamentales de la Empresa (gov_account).
    - user_remark: Descripción/Concepto y Número de Comprobante concatenados en las observaciones.
    """
    _require_withholding_permissions()

    if not docname:
        frappe.throw(_("Debe especificar el número o ID de la Factura de Compra."))

    invoice = frappe.get_doc("Purchase Invoice", docname)

    if invoice.docstatus != 1:
        frappe.throw(
            _(
                "La Factura de Compra {0} debe estar en estado Sometida (Validada) para aplicar una Retención Gubernamental."
            ).format(docname)
        )

    amount = flt(amount)
    if amount <= 0:
        frappe.throw(_("El monto de la retención debe ser mayor a cero."))

    gov_account = get_company_government_withholding_account(invoice.company)

    company_currency = frappe.db.get_value("Company", invoice.company, "default_currency") or "VED"
    invoice_currency = invoice.currency or company_currency
    conversion_rate = flt(invoice.conversion_rate) or 1.0

    tax_account_currency = frappe.db.get_value("Account", gov_account, "account_currency") or company_currency
    payable_currency = frappe.db.get_value("Account", invoice.credit_to, "account_currency") or company_currency

    base_grand_total = flt(invoice.base_grand_total) if invoice.base_grand_total else flt(flt(invoice.grand_total) * conversion_rate)

    if payable_currency != company_currency and conversion_rate > 0 and flt(invoice.outstanding_amount) <= flt(invoice.grand_total):
        base_outstanding = flt(invoice.outstanding_amount * conversion_rate)
    else:
        base_outstanding = flt(invoice.outstanding_amount)

    if round(flt(amount), 2) > round(flt(base_grand_total), 2) + 0.001:
        frappe.throw(
            _(
                "El monto de la retención ({0}) no puede ser mayor que el monto total de la factura ({1})."
            ).format(f"{amount:,.2f} {company_currency}", f"{base_grand_total:,.2f} {company_currency}")
        )

    if round(flt(amount), 2) > round(flt(base_outstanding), 2) + 0.001:
        frappe.throw(
            _(
                "El monto de la retención ({0}) no puede ser mayor que el saldo pendiente de la factura ({1})."
            ).format(f"{amount:,.2f} {company_currency}", f"{base_outstanding:,.2f} {company_currency}")
        )

    base_amount = round(flt(amount), 2)

    cost_center = (
        invoice.cost_center
        or frappe.db.get_value("Company", invoice.company, "cost_center")
    )

    je = frappe.new_doc("Journal Entry")
    je.company = invoice.company
    je.voucher_type = "Journal Entry"
    je.posting_date = frappe.utils.today()

    remark_parts = []
    if voucher_number and str(voucher_number).strip():
        remark_parts.append(f"Comprobante N°: {str(voucher_number).strip()}")

    if description and description.strip():
        remark_parts.append(description.strip())
    else:
        remark_parts.append(f"Retención Gubernamental aplicada a la Factura de Compra {invoice.name}")

    je.user_remark = " - ".join(remark_parts)

    je.multi_currency = (
        1
        if (
            invoice_currency != company_currency
            or tax_account_currency != company_currency
            or payable_currency != company_currency
        )
        else 0
    )

    # Debe: Cuenta por pagar al proveedor (reduce deuda)
    pay_exchange_rate = (
        conversion_rate
        if (payable_currency != company_currency and payable_currency == invoice_currency)
        else 1.0
    )
    pay_row = {
        "account": invoice.credit_to,
        "party_type": "Supplier",
        "party": invoice.supplier,
        "reference_type": "Purchase Invoice",
        "reference_name": invoice.name,
        "cost_center": cost_center,
    }
    if payable_currency != company_currency:
        proportional_amount_usd = flt(base_amount / pay_exchange_rate) if pay_exchange_rate else base_amount
        pay_row.update({
            "account_currency": payable_currency,
            "exchange_rate": pay_exchange_rate,
            "debit_in_account_currency": proportional_amount_usd,
            "debit": base_amount,
        })
    else:
        pay_row.update({
            "account_currency": company_currency,
            "debit_in_account_currency": base_amount,
            "debit": base_amount,
            "exchange_rate": 1.0,
        })
    je.append("accounts", pay_row)

    # Haber: Cuenta de Retención Gubernamental
    tax_row = {
        "account": gov_account,
        "cost_center": cost_center,
    }
    if tax_account_currency != company_currency:
        amount_in_tax_currency = flt(base_amount / conversion_rate) if (tax_account_currency == invoice_currency and conversion_rate) else base_amount
        tax_row.update({
            "account_currency": tax_account_currency,
            "exchange_rate": conversion_rate if tax_account_currency == invoice_currency else 1.0,
            "credit_in_account_currency": amount_in_tax_currency,
            "credit": base_amount,
        })
    else:
        tax_row.update({
            "account_currency": company_currency,
            "credit_in_account_currency": base_amount,
            "credit": base_amount,
            "exchange_rate": 1.0,
        })
    je.append("accounts", tax_row)

    try:
        je.insert(ignore_permissions=True)
        je.submit()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error Contabilizando Retención Gubernamental en Compra")
        frappe.throw(_("Error al intentar contabilizar la Retención Gubernamental: {0}").format(str(e)))

    je_link = get_link_to_form("Journal Entry", je.name)
    return {
        "status": "success",
        "journal_entry": je.name,
        "message": _("Asiento Contable de Retención Gubernamental {0} creado y sometido exitosamente.").format(je_link),
    }
