import frappe

@frappe.whitelist()
def get_company_address(company_name):
    if not company_name:
        return

    try:
        company_doc = frappe.get_doc("Company", company_name)
        address_link = company_doc.get("custom_company_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()
            
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting company address")

@frappe.whitelist()
def get_supplier_address(supplier_name):
    if not supplier_name:
        return

    try:
        supplier_doc = frappe.get_doc("Supplier", supplier_name)
        address_link = supplier_doc.get("supplier_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting supplier address")