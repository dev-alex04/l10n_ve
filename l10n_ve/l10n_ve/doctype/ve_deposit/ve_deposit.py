# -*- coding: utf-8 -*-
# Controller for VE Deposit DocType
# Fully written in English for backend logic, with Spanish error messages for the user.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class VEDeposit(Document):
    def validate(self):
        """Validate deposit inputs and calculate base currency amounts."""
        self.validate_amounts()
        self.validate_accounts()
        self.calculate_base_currency_amount()

    def on_submit(self):
        """Generate and submit the corresponding Journal Entry."""
        self.create_journal_entry()

    def on_cancel(self):
        """Cancel the linked Journal Entry if it exists."""
        self.cancel_journal_entry()

    def validate_amounts(self):
        """Ensure amount and exchange rate are positive values."""
        if flt(self.amount) <= 0:
            frappe.throw(_("El monto del depósito debe ser mayor a cero."))
        
        if flt(self.exchange_rate) <= 0:
            frappe.throw(_("La tasa de cambio de referencia debe ser mayor a cero."))

    def validate_accounts(self):
        """Verify that the selected accounts belong to the selected company."""
        company_dest = frappe.db.get_value("Account", self.destination_account, "company")
        if company_dest != self.company:
            frappe.throw(_("La cuenta de destino '{0}' no pertenece a la empresa seleccionada.").format(self.destination_account))

        company_src = frappe.db.get_value("Account", self.source_account, "company")
        if company_src != self.company:
            frappe.throw(_("La cuenta de origen '{0}' no pertenece a la empresa seleccionada.").format(self.source_account))

        if self.destination_account == self.source_account:
            frappe.throw(_("La cuenta de destino y la cuenta de origen no pueden ser la misma."))

    def calculate_base_currency_amount(self):
        """Calculate the amount in VEF (base currency)."""
        rate = flt(self.exchange_rate) or 1.0
        amount = flt(self.amount)
        
        if self.currency == "USD":
            self.amount_in_base_currency = flt(amount * rate)
        else:
            self.amount_in_base_currency = amount

    def create_journal_entry(self):
        """Create, insert, and submit a matching Journal Entry for this deposit."""
        company_currency = frappe.db.get_value("Company", self.company, "default_currency") or "VEF"
        dest_currency = frappe.db.get_value("Account", self.destination_account, "account_currency") or company_currency
        src_currency = frappe.db.get_value("Account", self.source_account, "account_currency") or company_currency
        
        amount_vef = flt(self.amount_in_base_currency)
        rate = flt(self.exchange_rate) or 1.0
        
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = self.posting_date
        je.user_remark = _("Depósito {0}. Referencia: {1}").format(self.name, self.reference_no or _("N/A"))
        
        # Set multi-currency flag if any account uses foreign currency
        if dest_currency != company_currency or src_currency != company_currency or self.currency != company_currency:
            je.multi_currency = 1
            
        # Get default cost center for the company
        default_cost_center = frappe.db.get_value("Company", self.company, "default_cost_center")
        
        # 1. Debit row (destination bank/cash account)
        dest_line = {
            "account": self.destination_account,
            "debit_in_account_currency": 0.0,
            "debit": amount_vef,
            "credit_in_account_currency": 0.0,
            "credit": 0.0,
            "exchange_rate": 1.0,
            "cost_center": default_cost_center
        }
        
        if dest_currency != company_currency:
            dest_line["account_currency"] = dest_currency
            if self.currency == dest_currency:
                dest_line["debit_in_account_currency"] = flt(self.amount)
            else:
                dest_line["debit_in_account_currency"] = flt(amount_vef / rate)
            dest_line["exchange_rate"] = rate
        else:
            dest_line["debit_in_account_currency"] = amount_vef
            
        # 2. Credit row (source counterparty account)
        src_line = {
            "account": self.source_account,
            "debit_in_account_currency": 0.0,
            "debit": 0.0,
            "credit_in_account_currency": 0.0,
            "credit": amount_vef,
            "exchange_rate": 1.0,
            "cost_center": default_cost_center
        }
        
        if src_currency != company_currency:
            src_line["account_currency"] = src_currency
            if self.currency == src_currency:
                src_line["credit_in_account_currency"] = flt(self.amount)
            else:
                src_line["credit_in_account_currency"] = flt(amount_vef / rate)
            src_line["exchange_rate"] = rate
        else:
            src_line["credit_in_account_currency"] = amount_vef
            
        je.append("accounts", dest_line)
        je.append("accounts", src_line)
        
        # Save and submit Journal Entry
        je.flags.ignore_permissions = True
        je.insert()
        je.submit()
        
        # Link the generated Journal Entry back to the VE Deposit record
        self.db_set("journal_entry", je.name)

    def cancel_journal_entry(self):
        """Cancel the linked Journal Entry document."""
        if self.journal_entry:
            je_status = frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus")
            if je_status == 1:
                je_doc = frappe.get_doc("Journal Entry", self.journal_entry)
                je_doc.flags.ignore_permissions = True
                je_doc.cancel()
                frappe.msgprint(_("El asiento contable '{0}' asociado ha sido cancelado.").format(self.journal_entry))
