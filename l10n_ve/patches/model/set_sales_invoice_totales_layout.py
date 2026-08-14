import frappe
import json

def execute():
    meta = frappe.get_meta("Sales Invoice")
    fields = [f.fieldname for f in meta.fields]

    target_fields = [
        "base_net_total",
        "net_total",
        "base_total_taxes_and_charges",
        "total_taxes_and_charges",
        "base_grand_total",
        "grand_total",
        "base_in_words",
        "in_words",
        "column_break_47",
        "totals",
    ]

    new_fields = [f for f in fields if f not in target_fields]

    if "section_break_43" in new_fields:
        idx = new_fields.index("section_break_43")
        totales_block = [
            "base_net_total",
            "base_total_taxes_and_charges",
            "base_grand_total",
            "base_in_words",
            "column_break_47",
            "net_total",
            "total_taxes_and_charges",
            "grand_total",
            "in_words",
            "totals",
        ]
        new_fields[idx + 1 : idx + 1] = totales_block

        frappe.make_property_setter(
            args={
                "doctype": "Sales Invoice",
                "property": "field_order",
                "value": json.dumps(new_fields),
                "property_type": "Data",
                "doctype_or_field": "DocType",
            }
        )

    property_setters = [
        {"fieldname": "section_break_43", "property": "label", "value": "Totales", "property_type": "Data"},
        {"fieldname": "section_break_43", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "totals", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_net_total", "property": "label", "value": "Base Imponible", "property_type": "Data"},
        {"fieldname": "base_net_total", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "base_total_taxes_and_charges", "property": "label", "value": "IVA", "property_type": "Data"},
        {"fieldname": "base_total_taxes_and_charges", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "base_grand_total", "property": "label", "value": "Base Imponible + IVA", "property_type": "Data"},
        {"fieldname": "base_grand_total", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "base_in_words", "property": "label", "value": "En palabras", "property_type": "Data"},
        {"fieldname": "base_in_words", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "net_total", "property": "label", "value": "Base Imponible", "property_type": "Data"},
        {"fieldname": "net_total", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "total_taxes_and_charges", "property": "label", "value": "IVA", "property_type": "Data"},
        {"fieldname": "total_taxes_and_charges", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "grand_total", "property": "label", "value": "Base Imponible + IVA", "property_type": "Data"},
        {"fieldname": "grand_total", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "in_words", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_total_with_vat", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_rounding_adjustment", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_rounded_total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "rounding_adjustment", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "rounded_total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "total_advance", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "outstanding_amount", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "outstanding_amount", "property": "label", "value": "Monto Pendiente", "property_type": "Data"},
    ]

    # Eliminar Property Setter explícito de ocultación si existía previamente
    if frappe.db.exists("Property Setter", "Sales Invoice-outstanding_amount-hidden"):
        frappe.delete_doc("Property Setter", "Sales Invoice-outstanding_amount-hidden", force=True)

    for ps in property_setters:
        frappe.make_property_setter(
            args={
                "doctype": "Sales Invoice",
                "fieldname": ps["fieldname"],
                "property": ps["property"],
                "value": ps["value"],
                "property_type": ps["property_type"],
                "doctype_or_field": "DocField",
            }
        )
