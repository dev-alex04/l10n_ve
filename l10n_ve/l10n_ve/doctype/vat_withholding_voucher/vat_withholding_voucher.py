# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate

def get_context(context, doc):
    # Obtiene los datos de la empresa y proveedor
    company_info = frappe.db.get_value(
        "Company",
        doc.empresa,
        ["name", "tax_id", "address", "phone"]
    )
    
    supplier_info = frappe.db.get_value(
        "Supplier",
        doc.supplier,
        ["name", "tax_id", "address", "phone"]
    )

    # Asigna la información al contexto
    context.company_data = company_info
    context.supplier_data = supplier_info

    # Formatea las fechas y las agrega al contexto
    if doc.issue_date:
        context.formatted_issue_date = getdate(doc.issue_date).strftime('%d/%m/%Y')
    else:
        context.formatted_issue_date = ""

    if doc.delivery_date:
        context.formatted_delivery_date = getdate(doc.delivery_date).strftime('%d/%m/%Y')
    else:
        context.formatted_delivery_date = ""

class VATWithholdingVoucher(Document):
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
            # Extrae la parte numérica del correlativo (del 7mo carácter en adelante)
            last_correlative_part = current_correlative_value[6:]
            
            # El número del comprobante es el valor actual (no incrementado)
            voucher_correlative_num = int(last_correlative_part)
            
            # El próximo correlativo para la compañía es el valor actual + 1
            next_correlative_num = int(last_correlative_part) + 1
            num_digits = len(last_correlative_part)
        else:
            # Si es el primer comprobante, el valor es 1
            voucher_correlative_num = 1
            next_correlative_num = 2
            
            # Asume el formato AAAA-MM-######### para la longitud
            template = company_doc.vat_withholding_format
            num_digits = len(template) - 6

        # Formatea el correlativo para el comprobante
        formatted_voucher_correlative = str(voucher_correlative_num).zfill(num_digits)
        
        # Formatea el próximo correlativo para la compañía
        formatted_next_correlative = str(next_correlative_num).zfill(num_digits)
        
        # Construye el número final para el comprobante con la fecha y el correlativo actual
        final_voucher_number = f"{current_year}{current_month}{formatted_voucher_correlative}"

        # Construye el próximo número para la compañía con la fecha y el correlativo incrementado
        final_next_correlative_number = f"{current_year}{current_month}{formatted_next_correlative}"

        # 4. Asigna el número al campo del comprobante.
        self.voucher_number = final_voucher_number

        # 5. Guarda el próximo correlativo en el DocType Company.
        company_doc.vat_withholding_correlative = final_next_correlative_number
        company_doc.save(ignore_permissions=True)

@frappe.whitelist()
def get_vat_correlative(company_name):
    """
    Construye y devuelve el próximo número de comprobante de retención,
    incrementando el correlativo de forma continua.
    """
    if not company_name:
        return None
    
    company_doc = frappe.get_doc("Company", company_name)
    
    # Extrae el valor completo del correlativo guardado
    correlative_value = company_doc.vat_withholding_correlative
    
    # Obtiene la fecha actual
    today = getdate(nowdate())
    current_year = str(today.year)
    current_month = f"{today.month:02d}"

    if correlative_value:
        # Extrae la parte numérica del correlativo (del 7mo carácter en adelante)
        last_correlative_part = correlative_value[6:]
        
        # Incrementa el correlativo y mantiene la longitud
        new_correlative = int(last_correlative_part)
        num_digits = len(last_correlative_part)
            
    else:
        # Si es el primer correlativo, lo inicializa
        # Se asume que el formato es siempre AAAA-MM-#########
        new_correlative = 1
        template = company_doc.vat_withholding_format
        num_digits = len(template) - 6  # Resta los 6 dígitos del AAAA-MM
    
    # Formatea el correlativo con ceros a la izquierda
    formatted_correlative = str(new_correlative).zfill(num_digits)
    
    # Construye el número final con el año y mes actuales
    final_withholding_number = f"{current_year}{current_month}{formatted_correlative}"
    
    return final_withholding_number

@frappe.whitelist()
def get_invoiced_purchase_invoices():
    """
    Devuelve una lista de facturas de compra que ya están enlazadas a un comprobante de retención.
    """
    invoices = frappe.get_list(
        "VAT Withholding Voucher Item",
        filters={"parenttype": "VAT Withholding Voucher"},
        fields=["purchase_invoice"]
    )
    return [d.purchase_invoice for d in invoices]

@frappe.whitelist()
def get_valid_invoices(supplier, start_date, end_date):
    """
    Devuelve una lista de facturas de compra para un proveedor y rango de fechas,
    excluyendo las que ya están en otros comprobantes de retención.
    """
    # Obtiene los nombres de todas las facturas que ya están en un Comprobante de Retención
    excluded_from_withholding = frappe.get_all(
        "VAT Withholding Voucher Item",
        filters={"purchase_invoice": ["!=", ""]},
        fields=["purchase_invoice"]
    )
    excluded_from_withholding_list = [d.purchase_invoice for d in excluded_from_withholding]

    # La lista de exclusión es simplemente la lista que acabamos de obtener
    all_excluded_invoices = excluded_from_withholding_list

    # Obtiene los datos de las facturas que cumplen con los criterios y no están excluidas
    valid_invoices_names = frappe.get_all(
        "Purchase Invoice",
        filters={
            "supplier": supplier,
            "posting_date": ["between", [start_date, end_date]],
            # "docstatus": 1,
            # "is_return": 0,
            # "status": ["!=", "Cancelled"],
            "name": ["not in", all_excluded_invoices]
        },
        fields=["name"]
    )

    # Itera sobre la lista de facturas para obtener los detalles completos, incluyendo los impuestos
    invoices_with_taxes = []
    for item in valid_invoices_names:
        invoice = frappe.get_doc("Purchase Invoice", item.name)
        
        rate = 0
        if invoice.taxes and len(invoice.taxes) > 0:
            tax_item = invoice.taxes[0]
            rate = tax_item.rate
            
        invoice_data = {
            "purchase_invoice": invoice.name,
            "bill_no": invoice.bill_no,
            "bill_control": invoice.bill_control,
            "posting_date": invoice.posting_date,
            "rate": rate, 
            "grand_total": invoice.grand_total,
            "total": invoice.total,
            "taxes_and_charges_added": invoice.taxes_and_charges_added,
            "taxes_and_charges_deducted": invoice.taxes_and_charges_deducted,
            "taxes": invoice.get("taxes") 
        }
        invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes

# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document
# from frappe.utils import nowdate, getdate
# from frappe.model.db_query import get_query

# @frappe.whitelist()
# def get_vat_correlative(company_name):
#     """
#     Construye y devuelve el próximo número de comprobante de retención,
#     incrementando el correlativo de forma continua.
#     """
#     if not company_name:
#         return None
    
#     company_doc = frappe.get_doc("Company", company_name)
    
#     # Extrae el valor completo del correlativo guardado
#     correlative_value = company_doc.vat_withholding_correlative
    
#     today = getdate(nowdate())
#     current_year = str(today.year)
#     current_month = f"{today.month:02d}"

#     if correlative_value:
#         # Extrae la parte numérica y la incrementa
#         last_correlative_part = correlative_value[6:]
#         new_correlative_num = int(last_correlative_part) + 1
#         num_digits = len(last_correlative_part)
            
#     else:
#         # Si es el primer correlativo, lo inicializa
#         new_correlative_num = 1
#         template = company_doc.vat_withholding_format
#         num_digits = len(template) - 6
    
#     # Formatea el nuevo correlativo con ceros a la izquierda
#     formatted_correlative = str(new_correlative_num).zfill(num_digits)
    
#     # Construye el número final
#     final_withholding_number = f"{current_year}{current_month}{formatted_correlative}"
    
#     return final_withholding_number

# @frappe.whitelist()
# def get_valid_invoices(supplier, start_date, end_date):
#     """
#     Devuelve una lista de facturas de compra para un proveedor y rango de fechas,
#     excluyendo las que ya están en otros comprobantes de retención.
#     """
#     # 1. Obtiene las facturas ya enlazadas en una sola consulta
#     excluded_invoices = frappe.get_all(
#         "VAT Withholding Voucher Item",
#         filters={"purchase_invoice": ["!=", ""]},
#         pluck="purchase_invoice"
#     )

#     # 2. Realiza una sola consulta para obtener todas las facturas válidas
#     valid_invoices = frappe.get_all(
#         "Purchase Invoice",
#         filters={
#             "supplier": supplier,
#             "posting_date": ["between", [start_date, end_date]],
#             "docstatus": 1,
#             "is_return": 0,
#             "name": ["not in", excluded_invoices]
#         },
#         fields=[
#             "name as purchase_invoice",
#             "bill_no",
#             "bill_control",
#             "posting_date",
#             "grand_total",
#             "total",
#             "taxes_and_charges_added",
#             "taxes_and_charges_deducted"
#         ]
#     )
    
#     # 3. Itera sobre las facturas válidas para obtener los impuestos en una sola consulta
#     for invoice in valid_invoices:
#         # Usa una consulta más eficiente para los impuestos
#         invoice_taxes = frappe.get_all(
#             "Purchase Taxes and Charges",
#             filters={"parent": invoice.purchase_invoice},
#             fields=["rate", "tax_amount"],
#             limit=1
#         )
#         if invoice_taxes:
#             invoice.update(invoice_taxes[0])
#         else:
#             invoice.update({"rate": 0, "tax_amount": 0})
            
#     return valid_invoices


# class VATWithholdingVoucher(Document):
#     def before_save(self):
#         # Solo genera el número si no tiene uno
#         if not self.voucher_number:
#             company_doc = frappe.get_doc("Company", self.empresa)
            
#             current_correlative_value = company_doc.vat_withholding_correlative
            
#             today = getdate(nowdate())
#             current_year = str(today.year)
#             current_month = f"{today.month:02d}"

#             if current_correlative_value:
#                 last_correlative_part = current_correlative_value[6:]
#                 voucher_correlative_num = int(last_correlative_part)
#                 next_correlative_num = int(last_correlative_part) + 1
#                 num_digits = len(last_correlative_part)
#             else:
#                 voucher_correlative_num = 1
#                 next_correlative_num = 2
#                 template = company_doc.vat_withholding_format
#                 num_digits = len(template) - 6

#             formatted_voucher_correlative = str(voucher_correlative_num).zfill(num_digits)
#             final_voucher_number = f"{current_year}{current_month}{formatted_voucher_correlative}"
#             self.voucher_number = final_voucher_number
            
#             # Formatea y guarda el siguiente correlativo para la empresa
#             formatted_next_correlative = str(next_correlative_num).zfill(num_digits)
#             final_next_correlative_number = f"{current_year}{current_month}{formatted_next_correlative}"
            
#             company_doc.vat_withholding_correlative = final_next_correlative_number
#             company_doc.save(ignore_permissions=True)