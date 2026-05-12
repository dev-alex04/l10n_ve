# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt
# import frappe
from frappe.model.document import Document
import frappe

class TabulatorISLR(Document):

    def before_save(self) -> None:
        self.set_subtracting()

    def set_subtracting(self) -> None:

        subtracting_calculation_factor = \
            frappe.db.get_single_value('Venezuela Account Settings',
                                       'subtracting_calculation_factor')

        value_ut = frappe.db.get_value('Tax Unit', {'is_active': 1}, 'value')

        for row in self.aliquot:
            row.subtracting = 0

            if row.types_of_person != "Natural person domiciled":
                continue

            # Fórmula para Persona Natural Residente
            if all([bool(float(row.aliquot)),
                    bool(float(row.percentage_base)),
                    bool(float(value_ut))]):

                row.subtracting = \
                    (value_ut * subtracting_calculation_factor) * (float(row.aliquot) / float(row.percentage_base))
            else:
                row.subtracting = 0
