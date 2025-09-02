# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt
# import frappe
from frappe.model.document import Document
import frappe

class TabulatorISLR(Document):

    def before_save(self) -> None:
        self.set_subtracting()

    def set_subtracting(self) -> None:

        factor_pnr= frappe.db.get_single_value('Venezuela Account Settings',
                                               'subtracting_calculation_factor')

        value_ut = frappe.db.get_value('Tax Unit', {'is_active': 1}, 'value')

        for row in self.aliquot:
            if row.types_of_person == "Natural person domiciled":

                # Fórmula para Persona Natural Residente
                if row.aliquot and value_ut > 0:

                    row.subtracting = \
                        (value_ut * factor_pnr) * (row.aliquot / row.percentage_base)
                else:
                    row.subtracting = 0
            else:
                # Para los demás, el subtracting es 0
                row.subtracting = 0
