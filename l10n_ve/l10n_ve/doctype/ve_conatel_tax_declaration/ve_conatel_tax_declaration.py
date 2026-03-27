# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_first_day, get_last_day, flt

class VEConatelTaxDeclaration(Document):
    def autoname(self) -> None:
        """Genera el nombre del documento basado en el rango de fechas con un secuencial."""
        from frappe.model.naming import make_autoname
        base_name = f"CONATEL-{self.company}-{self.from_date}-{self.to_date}-.#####"
        self.name = make_autoname(base_name)

    def after_insert(self) -> None:
        """Set defaults after creation if not already set."""
        from frappe.utils import now_datetime, nowdate
        now = now_datetime()
        if not self.declaration_year:
            self.declaration_year = now.year
        if not self.declaration_date:
            self.declaration_date = nowdate()

    @frappe.whitelist()
    def make_journal_entry(self):
        """Crea un Asiento Contable (Journal Entry) basado en los tributos calculados."""
        if self.journal_entry:
            frappe.throw(_("Ya existe un asiento contable asociado: {0}").format(self.journal_entry))
        
        if self.status != "Declarado":
            frappe.throw(_("Solo se puede generar el asiento contable cuando el estado es 'Declarado'."))
        
        if not self.taxes:
            frappe.throw(_("No hay tributos calculados para generar el asiento."))
            
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = self.declaration_date
        je.user_remark = _("Declaración CONATEL {0} al {1}").format(self.from_date, self.to_date)
        
        if not self.tax_payable_account or not self.tax_expense_account:
            frappe.throw(_("Debe configurar la Cuenta de Pasivo y "
                           "Gasto en la sección de Integración Contable."))
            
        je.append("accounts", {
            "account": self.tax_expense_account,
            "debit_in_account_currency": self.total_to_pay,
            "cost_center": frappe.get_cached_value("Company", self.company, "cost_center")
        })
        
        je.append("accounts", {
            "account": self.tax_payable_account,
            "credit_in_account_currency": self.total_to_pay,
        })
            
        je.insert()
        je.submit()
        
        self.db_set("journal_entry", je.name)
        return je.name

    @frappe.whitelist()
    def cancel_journal_entry(self):
        """Cancela y desvincula el asiento contable asociado."""
        if not self.journal_entry:
            frappe.throw(_("No hay un asiento contable asociado para cancelar."))
            
        je_name = self.journal_entry
        
        self.db_set("journal_entry", None)
        self.journal_entry = None
        
        je = frappe.get_doc("Journal Entry", je_name)
        if je.docstatus == 1:
            je.cancel()
        elif je.docstatus == 0:
            je.delete()

    def validate(self) -> None:
        """Valida rango de fechas, duplicados y recalcula totales y estado."""
        if self.from_date > self.to_date:
            frappe.throw(_("La fecha 'Desde' no puede ser mayor a la fecha 'Hasta'"))

        self.total_taxable_base = flt(sum(flt(item.taxable_base) for item in self.items), 2)
        self.total_to_pay = flt(sum(flt(tax.amount) for tax in self.taxes), 2)

        if self.num_declaration and self.declaration_document:
            self.status = "Declarado"
        elif self.total_taxable_base > 0:
            self.status = "Por Declarar"
        else:
            self.status = "Por Procesar"

        if self.company:
            comp = frappe.get_doc("Company", self.company)
            if not self.tax_id:
                self.tax_id = comp.tax_id
            if not getattr(self, "legal_representative", None):
                self.legal_representative = getattr(comp, "legal_representative", None)
            if not self.currency:
                self.currency = comp.default_currency
            if not getattr(self, "fiscal_address", None) and getattr(comp, "custom_company_primary_address", None):
                self.fiscal_address = frappe.db.get_value("Address", comp.custom_company_primary_address, "address_line1")

        if self.is_new():
            self.tax_id = frappe.db.get_value("Company", self.company, "tax_id")
            
            overlap = frappe.db.sql("""
                SELECT name FROM `tabVE Conatel Tax Declaration`
                WHERE 
                    company = %s 
                    AND docstatus != 2
                    AND (
                        (from_date <= %s AND to_date >= %s) OR
                        (from_date <= %s AND to_date >= %s) OR
                        (%s <= from_date AND %s >= to_date)
                    )
            """, (self.company, self.from_date, self.from_date, self.to_date, self.to_date, self.from_date, self.to_date))
            
            if overlap:
                frappe.msgprint(_("⚠️ **Advertencia**: El periodo seleccionado se solapa con una declaración existente: {0}. Verifica que no estés duplicando información.").format(overlap[0][0]), indicator='orange')

@frappe.whitelist()
def get_conatel_data(company, from_date, to_date, branch=None):
    """Obtiene los datos de ingresos y calcula tributos dinámicamente usando un rango de fechas."""
    
    query_filters = [company, from_date, to_date]
    branch_filter = ""
    if branch:
        if frappe.db.has_column("VE Branch", "lft") and frappe.db.has_column("VE Branch", "rgt"):
            b_info = frappe.db.get_value("VE Branch", branch, ["lft", "rgt"], as_dict=True)
            if b_info:
                branch_filter = "AND si.branch IN (SELECT name FROM `tabVE Branch` WHERE lft >= %s AND rgt <= %s)"
                query_filters.extend([b_info.lft, b_info.rgt])
        else:
            branch_filter = "AND si.branch = %s"
            query_filters.append(branch)

    items = frappe.db.sql(f"""
        SELECT 
            'Total Facturado' as item_code,
            'Resumen de Ventas del Periodo' as item_name,
            COUNT(DISTINCT si.name) as invoice_count,
            SUM(CASE WHEN si.is_return = 1 THEN -sii.base_amount ELSE sii.base_amount END) as taxable_base
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON sii.parent = si.name
        WHERE 
            si.docstatus = 1 
            AND si.company = %s
            AND si.posting_date BETWEEN %s AND %s
            {branch_filter}
    """, tuple(query_filters), as_dict=True)
    
    if items and not items[0].get('invoice_count'):
        items = []
    
    total_taxable_base = sum(flt(item.taxable_base) for item in items)
    
    tax_types = frappe.get_all("VE Conatel Tax Type", 
                               fields=["name", "aliquot"])
    
    calculated_taxes = []
    for t in tax_types:
        aliquot = flt(t.aliquot)
        amount = flt(total_taxable_base * (aliquot / 100), 2)
        calculated_taxes.append({
            "tax_type": t.name,
            "aliquot": aliquot,
            "amount": amount
        })
        
    return {
        "items": items,
        "taxes": calculated_taxes,
        "total_taxable_base": total_taxable_base
    }
