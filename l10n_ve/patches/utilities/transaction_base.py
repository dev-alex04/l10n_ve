import frappe
from frappe import _
from erpnext.utilities.transaction_base import TransactionBase

original_compare_values = TransactionBase.compare_values

def custom_compare_values(self, ref_doc, fields, doc=None):
    """
    Esta es nuestra versión personalizada de `compare_values`.
    Toma la información del documento de origen y la pasa a `validate_value`.
    """
    for reference_doctype, ref_dn_list in ref_doc.items():
        prev_doc_detail_map = self.get_prev_doc_reference_details(ref_dn_list,
                                                                  reference_doctype,
                                                                  fields)
        for reference_name in ref_dn_list:
            prevdoc_values = prev_doc_detail_map.get(reference_name)
            if not prevdoc_values:
                frappe.throw(_("Referencia inválida {0} {1}").format(reference_doctype,
                                                                      reference_name))
            for field, condition in fields:
                if prevdoc_values.get(field) is not None and field not in getattr(self, "exclude_fields", []):
                    # tupla con la información del documento de origen
                    source_info = (reference_doctype, reference_name)
                    self.validate_value(field, condition,
                                         prevdoc_values[field],
                                           doc, source_doc_info=source_info)

TransactionBase.compare_values = custom_compare_values