# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate


class ISLRWithholdingVoucher(Document):
	def before_insert(self):
		# 1. Obtener el documento de la compañía.
		company_doc = frappe.get_doc("Company", self.empresa)

		# 2. Leer el valor completo del correlativo de la compañía.
		current_correlative_value = company_doc.vat_withholding_correlative

		# 3. Obtener la fecha actual.
		today = getdate(nowdate())
		current_year = str(today.year)
		current_month = f"{today.month:02d}"

		if current_correlative_value:
			last_correlative_part = current_correlative_value[6:]
			voucher_correlative_num = int(last_correlative_part)

			next_correlative_num = int(last_correlative_part) + 1
			num_digits = len(last_correlative_part)
		else:
			voucher_correlative_num = 1
			next_correlative_num = 2
			
			template = company_doc.vat_withholding_format
			num_digits = len(template) - 6

		formatted_voucher_correlative = str(voucher_correlative_num).zfill(num_digits)
		formatted_next_correlative = str(next_correlative_num).zfill(num_digits)

		final_voucher_number = f"{current_year}{current_month}{formatted_voucher_correlative}"
		final_next_correlative_number = f"{current_year}{current_month}{formatted_next_correlative}"

		# 4. Asigna el número al campo del comprobante.
		self.voucher_number = final_voucher_number

		# 5. Guarda el próximo correlativo en el DocType Company.
		company_doc.vat_withholding_correlative = final_next_correlative_number
		company_doc.save(ignore_permissions=True)

@frappe.whitelist()
def get_supplier_address(supplier_name):
    if not supplier_name:
        return

    try:
        # Intenta obtener la dirección por el campo 'address' o 'default_billing_address'
        supplier_doc = frappe.get_doc("Supplier", supplier_name)
        address_link = supplier_doc.get("supplier_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting supplier address")

@frappe.whitelist()
def get_company_address(company_name):
    if not company_name:
        return

    try:
        # Intenta obtener la dirección por el campo 'address' o 'default_billing_address'
        company_doc = frappe.get_doc("Company", company_name)
        address_link = company_doc.get("custom_company_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()
            
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting company address")

@frappe.whitelist()
def get_vat_correlative(company_name):
    if not company_name:
        return
    
    company_doc = frappe.get_doc("Company", company_name)
    
    correlative_value = company_doc.vat_withholding_correlative
    
    today = getdate(nowdate())
    current_year = str(today.year)
    current_month = f"{today.month:02d}"

    if correlative_value:
        last_correlative_part = correlative_value[6:]
        
        new_correlative = int(last_correlative_part)
        num_digits = len(last_correlative_part)
            
    else:
        # Si es el primer correlativo, lo inicializa
        # Se asume que el formato es siempre AAAA-MM-#########
        new_correlative = 1
        template = company_doc.vat_withholding_format
        num_digits = len(template) - 6  # Resta los 6 dígitos del AAAA-MM
    
    formatted_correlative = str(new_correlative).zfill(num_digits)
    
    final_withholding_number = f"{current_year}{current_month}{formatted_correlative}"
    
    return final_withholding_number

@frappe.whitelist()
def get_valid_invoices(supplier, start_date, end_date, company):
    # Obtiene los nombres de todas las facturas que ya están en un Comprobante de Retención
    excluded_from_withholding = frappe.get_all(
        "ISLR Withholding Voucher Item",
        filters={"purchase_invoice": ["!=", ""]},
        fields=["purchase_invoice"]
    )
    excluded_from_withholding_list = [d.purchase_invoice for d in excluded_from_withholding]

    # La lista de exclusión es simplemente la lista que acabamos de obtener
    all_excluded_invoices = excluded_from_withholding_list

    # Obtiene los datos de las facturas que cumplen con los criterios y no están excluidas
    valid_invoices_names = frappe.get_all(
        "Purchase Invoice",
        filters=[
            {"supplier": supplier},
            {"posting_date": ["between", [start_date, end_date]]},
            {"company": company},
            {"docstatus": 1},
            {"name": ["not in", all_excluded_invoices]},
            # Filtra por invoices que tienen un impuesto con `charge_type` = 'Actual'
            ["Purchase Taxes and Charges", "charge_type", "=", "ISLR"]
        ],
        fields=["name"]
    )

    # Itera sobre la lista de facturas para obtener los detalles completos, incluyendo los impuestos
    invoices_with_taxes = []
    for item in valid_invoices_names:
        invoice = frappe.get_doc("Purchase Invoice", item.name)
        tax_item = None

        if invoice.taxes and len(invoice.taxes) > 0:
        # Itera sobre la lista de impuestos para encontrar el correcto
            for tax in invoice.taxes:
                if tax.charge_type == "ISLR":
                    tax_item = tax
                    break # Detiene el bucle una vez que se encuentra el impuesto ISLR
        
            if tax_item:
                invoice_data = {
                    "purchase_invoice": invoice.name,
                    "bill_no": invoice.bill_no,
                    "bill_control": invoice.bill_control,
                    "posting_date": invoice.posting_date,
                    "rate": tax_item.rate, 
                    "subtracting": tax_item.subtracting, 
                    "codigo": tax_item.codigo, 
                    "amount_paid": invoice.grand_total,
                    "grand_total": invoice.grand_total,
                    "total": invoice.total,
                    "tax_amount": tax_item.tax_amount,
                    "taxes": tax_item 
                }

                invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes