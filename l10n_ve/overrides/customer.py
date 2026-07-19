import frappe
from frappe import _
from erpnext.selling.doctype.customer.customer import Customer
from l10n_ve.utils.utils import validate_tax_id_format, validate_unique_tax_id, validate_taxpayer_and_person_type_consistency
from l10n_ve.utils.utils import link_address_to_party


class VECustomer(Customer):
    def validate(self):
        super().validate()

        validate_tax_id_format(self)
        validate_unique_tax_id(self)
        validate_taxpayer_and_person_type_consistency(self)

    def on_update(self):
        super().on_update()

        if self.customer_primary_address:
            link_address_to_party(self.customer_primary_address,
                                  self.doctype,
                                  self.name)

        validate_taxpayer_and_person_type_consistency(self)

    def get_email_list(self) -> list[str]:
        if not self.email_id:
            return []
        return [email.strip() for email in self.email_id.split(",") if email.strip()]

def get_customer_emails(customer_name):
    """
    Busca un cliente por su ID y devuelve la lista de correos.
    """
    doc = frappe.get_doc("Customer", customer_name)
    if hasattr(doc, "get_email_list"):
        return doc.get_email_list()

    return VECustomer.get_email_list(doc)


def get_customer_dashboard_data(data: dict) -> dict:
    """
    Extiende el tablero de conexiones del Cliente para incluir
    VE Sales Credit Note y VE Sales Debit Note en el grupo de Órdenes.
    """
    for group in data.get("transactions", []):
        if group.get("label") in (_("Orders"), "Orders"):
            items: list[str] = group.get("items", [])
            for doctype in ["VE Sales Credit Note", "VE Sales Debit Note"]:
                if doctype not in items:
                    items.append(doctype)
            break

    return data


@frappe.whitelist()
def get_balance_summary(customer: str) -> dict:
    """
    Obtiene un resumen contable detallado y las facturas pendientes
    de un cliente para mostrar en la ficha del Cliente, manejando correctamente
    los anticipos no aplicados y la moneda de la cuenta contable.
    """
    # Obtener la moneda de la cuenta contable del cliente
    # Buscamos la cuenta contable de cuentas por cobrar predeterminada para el cliente
    company = frappe.defaults.get_user_default("Company") or frappe.db.get_value("Company", {}, "name")
    account_currency = None
    if company:
        # Buscar cuenta de cobro del cliente
        debit_to = frappe.db.get_value("Party Account", {"parent": customer, "parenttype": "Customer", "company": company}, "account")
        if not debit_to:
            debit_to = frappe.db.get_value("Company", company, "default_receivable_account")
        if debit_to:
            account_currency = frappe.db.get_value("Account", debit_to, "account_currency")
            
    if not account_currency:
        account_currency = frappe.db.get_value("Company", company, "default_currency") or "USD"

    # Obtener todas las partidas de GL Entry activas del cliente
    entries = frappe.db.sql(
        """
        SELECT 
            voucher_type,
            voucher_no,
            debit_in_account_currency,
            credit_in_account_currency
        FROM `tabGL Entry`
        WHERE party_type = 'Customer' AND party = %s AND is_cancelled = 0
        """,
        (customer,),
        as_dict=True
    )
    
    total_invoiced = 0.0
    total_paid = 0.0
    total_withholdings = 0.0
    total_credits = 0.0
    
    for entry in entries:
        debit = float(entry.debit_in_account_currency or 0)
        credit = float(entry.credit_in_account_currency or 0)
        
        if debit > 0:
            total_invoiced += debit
        if credit > 0:
            if entry.voucher_type in ("Payment Entry", "Journal Entry"):
                total_paid += credit
            elif entry.voucher_type == "VE Sales Credit Note" or (entry.voucher_type == "Sales Invoice" and "NC" in entry.voucher_no):
                total_credits += credit
            elif entry.voucher_type == "Sales Invoice":
                # Retenciones de IVA/ISLR registradas en la propia factura
                total_withholdings += credit
            else:
                total_paid += credit

    # Saldo contable neto del cliente
    net_balance = total_invoiced - total_paid - total_withholdings - total_credits
                
    # Obtener facturas abiertas
    open_invoices = frappe.db.sql(
        """
        SELECT 
            name,
            bill_no,
            posting_date,
            due_date,
            outstanding_amount,
            currency
        FROM `tabSales Invoice`
        WHERE customer = %s AND docstatus = 1 AND outstanding_amount > 0
        ORDER BY due_date ASC
        """,
        (customer,),
        as_dict=True
    )
    
    formatted_invoices = []
    open_invoices_total = 0.0
    for inv in open_invoices:
        due_date = inv.due_date
        today = frappe.utils.getdate()
        days_overdue = (today - due_date).days if today > due_date else 0
        
        # El outstanding_amount en ERPNext para facturas de clientes con cuenta VEF
        # se almacena en la moneda de la cuenta (VEF/Bs).
        outstanding = float(inv.outstanding_amount)
        open_invoices_total += outstanding
        
        formatted_invoices.append({
            "name": inv.name,
            "bill_no": inv.bill_no or inv.name,
            "posting_date": frappe.utils.format_date(inv.posting_date),
            "due_date": frappe.utils.format_date(inv.due_date),
            "outstanding_amount": outstanding,
            "currency": account_currency,  # Usamos la moneda de la cuenta contable
            "days_overdue": days_overdue
        })
        
    # Calcular anticipos o notas de crédito sin aplicar a facturas
    unapplied_credits = 0.0
    if open_invoices_total > net_balance:
        unapplied_credits = open_invoices_total - net_balance

    return {
        "account_currency": account_currency,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "total_withholdings": total_withholdings,
        "total_credits": total_credits,
        "net_balance": net_balance,
        "open_invoices_total": open_invoices_total,
        "unapplied_credits": unapplied_credits,
        "open_invoices": formatted_invoices
    }
