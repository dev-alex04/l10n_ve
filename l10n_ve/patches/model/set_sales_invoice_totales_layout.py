import frappe
import json

def execute():
    meta = frappe.get_meta("Sales Invoice")
    fields = [f.fieldname for f in meta.fields]

    target_fields = [
        "base_net_total",
        "net_total",
        "base_ve_vat_amount",
        "ve_vat_amount",
        "base_total_with_vat",
        "ve_total_with_vat",
        "base_in_words",
        "column_break_47",
        "outstanding_amount",
    ]

    new_fields = [f for f in fields if f not in target_fields]

    if "section_break_43" in new_fields:
        idx = new_fields.index("section_break_43")
        totales_block = [
            "base_net_total",
            "base_ve_vat_amount",
            "base_total_with_vat",
            "base_in_words",
            "column_break_47",
            "net_total",
            "ve_vat_amount",
            "ve_total_with_vat",
            "outstanding_amount",
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
        {"fieldname": "base_ve_vat_amount", "property": "label", "value": "IVA", "property_type": "Data"},
        {"fieldname": "base_ve_vat_amount", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "base_total_with_vat", "property": "label", "value": "Base Imponible + IVA", "property_type": "Data"},
        {"fieldname": "base_total_with_vat", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "base_in_words", "property": "label", "value": "En palabras", "property_type": "Data"},
        {"fieldname": "base_in_words", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "net_total", "property": "label", "value": "Base Imponible", "property_type": "Data"},
        {"fieldname": "net_total", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "ve_vat_amount", "property": "label", "value": "IVA", "property_type": "Data"},
        {"fieldname": "ve_vat_amount", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "ve_total_with_vat", "property": "label", "value": "Base Imponible + IVA", "property_type": "Data"},
        {"fieldname": "ve_total_with_vat", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "outstanding_amount", "property": "label", "value": "Monto Pendiente", "property_type": "Data"},
        {"fieldname": "outstanding_amount", "property": "hidden", "value": "0", "property_type": "Check"},
        {"fieldname": "base_total_taxes_and_charges", "property": "label", "value": "Impuestos y cargos totales", "property_type": "Data"},
        {"fieldname": "total_taxes_and_charges", "property": "label", "value": "Impuestos y cargos totales", "property_type": "Data"},
        {"fieldname": "base_grand_total", "property": "label", "value": "Total general", "property_type": "Data"},
        {"fieldname": "grand_total", "property": "label", "value": "Total general", "property_type": "Data"},
        {"fieldname": "in_words", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_rounding_adjustment", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "base_rounded_total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "rounding_adjustment", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "rounded_total", "property": "hidden", "value": "1", "property_type": "Check"},
        {"fieldname": "total_advance", "property": "hidden", "value": "1", "property_type": "Check"},
    ]

    # Eliminar Property Setter explícito de ocultación si existía previamente
    for fn in ["outstanding_amount", "base_total_with_vat", "base_ve_vat_amount", "ve_vat_amount", "ve_total_with_vat", "grand_total", "base_grand_total"]:
        ps_name = f"Sales Invoice-{fn}-hidden"
        if frappe.db.exists("Property Setter", ps_name):
            frappe.delete_doc("Property Setter", ps_name, force=True)

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
