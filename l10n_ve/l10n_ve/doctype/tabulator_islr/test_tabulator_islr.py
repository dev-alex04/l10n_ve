# Copyright (c) 2025, DominaERP and Contributors
# See license.txt

# import frappe
# import frappe
# import frappe
from frappe.model.document import Document
import frappe

class TabulatorISLR(Document):
    def before_save(self):
        # Valor del factor para la prueba (puedes ajustarlo si lo necesitas)
        factor_pnr = 10 

        # Iterar sobre las filas de la tabla de alícuotas
        for row in self.alicuotas:
            if row.tipo_persona == "Persona Natural Residente":
                try:
                    # Obtener el valor de la U.T. directamente
                    ut_doc = frappe.get_doc('Unidad Tributaria', filters={'is_active': 1})
                    valor_ut = ut_doc.valor
                except Exception as e:
                    frappe.log_error(f"Error al obtener Unidad Tributaria: {e}")
                    valor_ut = 0
                
                # Fórmula para Persona Natural Residente
                if row.alicuota and valor_ut > 0:
                    row.sustraendo = (valor_ut * factor_pnr) * (row.alicuota / 100)
                else:
                    row.sustraendo = 0
            else:
                # Para los demás, el sustraendo es 0
                row.sustraendo = 0