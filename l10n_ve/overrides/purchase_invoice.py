import frappe
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.utils.utils import validate_return_in_same_month

class CustomPurchaseInvoice(TaxesMixin, PurchaseInvoice):

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

