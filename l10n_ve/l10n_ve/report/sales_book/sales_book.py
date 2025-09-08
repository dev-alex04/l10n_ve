# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

# import frappe

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, add_days
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from io import BytesIO
import json # Importamos el módulo 'json
import traceback


def execute(filters=None):
	"""
	Punto de entrada principal para el Reporte de Libro de Ventas.
	Devuelve las columnas y los datos basados en los filtros.
	"""

	columns = get_columns()
	data = get_sales_data(filters)
	
	if data:
		total_row = get_total_row(data)
		data.append(total_row)

	return columns, data, None, None, None

def get_columns():
	"""
	Define las columnas de la tabla del reporte.
	"""
	return [
		{"label": _("Fecha"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Nro. Operación"), "fieldname": "sales_invoice_id", "fieldtype": "Data", "width": 120},
		{"label": _("RIF del Cliente"), "fieldname": "customer_tax_id", "fieldtype": "Data", "width": 150},
		{"label": _("Nombre del Cliente"), "fieldname": "customer_name", "fieldtype": "Data", "width": 200},
		{"label": _("Tipo de Persona"), "fieldname": "customer_type", "fieldtype": "Data", "width": 120},
		{"label": _("Nro. de Factura"), "fieldname": "bill_no", "fieldtype": "Data", "width": 150},
		{"label": _("Nro. de Control"), "fieldname": "bill_control", "fieldtype": "Data", "width": 120},
		{"label": _("Nro. de Maquina Fiscal"), "fieldname": "maquina_fiscal", "fieldtype": "Data", "width": 150},
		{"label": _("Nro. Nota de Crédito"), "fieldname": "credit_note_no", "fieldtype": "Data", "width": 150},
		{"label": _("Nro. Nota de Débito"), "fieldname": "debit_note_no", "fieldtype": "Data", "width": 150},
		{"label": _("Tipo de Transacción"), "fieldname": "transaction_type", "fieldtype": "Data", "width": 150},
		{"label": _("Ventas Exoneradas"), "fieldname": "exempt_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Ventas internas no Gravadas"), "fieldname": "exempt_amount", "fieldtype": "Currency", "width": 120},
		
		# Columnas para Ventas a No Contribuyentes
		{"label": _("Base Imponible (No C.) G"), "fieldname": "base_general_non_taxpayer", "fieldtype": "Currency", "width": 150},
		{"label": _("IVA (No C.) G"), "fieldname": "iva_general_non_taxpayer", "fieldtype": "Currency", "width": 120},
		{"label": _("Base Imponible (No C.) R"), "fieldname": "base_reduced_non_taxpayer", "fieldtype": "Currency", "width": 150},
		{"label": _("IVA (No C.) R"), "fieldname": "iva_reduced_non_taxpayer", "fieldtype": "Currency", "width": 120},
		{"label": _("Base Imponible (No C.) A"), "fieldname": "base_additional_non_taxpayer", "fieldtype": "Currency", "width": 150},
		{"label": _("IVA (No C.) A"), "fieldname": "iva_additional_non_taxpayer", "fieldtype": "Currency", "width": 120},
		
		# Columnas para Ventas a Contribuyentes
		{"label": _("Base Imponible (C.) G"), "fieldname": "base_general_taxpayer", "fieldtype": "Currency", "width": 150},
		{"label": _("IVA (C.) G"), "fieldname": "iva_general_taxpayer", "fieldtype": "Currency", "width": 120},
		{"label": _("Base Imponible (C.) R"), "fieldname": "base_reduced_taxpayer", "fieldtype": "Currency", "width": 150},
		{"label": _("IVA (C.) R"), "fieldname": "iva_reduced_taxpayer", "fieldtype": "Currency", "width": 120},
		{"label": _("Base Imponible (C.) A"), "fieldname": "base_additional_taxpayer", "fieldtype": "Currency", "width": 150},
		{"label": _("IVA (C.) A"), "fieldname": "iva_additional_taxpayer", "fieldtype": "Currency", "width": 120},

	    # Campos de Retención de IVA
		{"label": _("IVA Retenido"), "fieldname": "iva_retained", "fieldtype": "Currency", "width": 120},
		{"label": _("Nro. Comprobante de Retención IVA"), "fieldname": "vat_withholding_voucher_number", "fieldtype": "Data", "width": 150},
		{"label": _("Fecha Comprobante"), "fieldname": "withholding_date", "fieldtype": "Date", "width": 120},
		{"label": _("Tasa de Retención IVA"), "fieldname": "vat_withholding_rate", "fieldtype": "Percent", "width": 120},

		# Columnas para IGTF (Impuesto a las Grandes Transacciones Financieras)
		{"label": _("Base Imponible IGTF"), "fieldname": "igtf_base", "fieldtype": "Currency", "width": 120},
		{"label": _("Tasa de IGTF"), "fieldname": "igtf_rate", "fieldtype": "Percent", "width": 120},
		{"label": _("Monto IGTF"), "fieldname": "igtf_amount", "fieldtype": "Currency", "width": 120},

		{"label": _("Total Incl. IVA"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 120},
		{"label": _("Total USD"), "fieldname": "total_in_usd", "fieldtype": "Currency", "width": 120},
	]
def get_sales_data(filters):
	
	"""
	Obtiene los datos del reporte ejecutando una consulta SQL optimizada.
	"""
	try:
		tax_rates_doc = frappe.get_doc("Taxes Rates", "Taxes Rates")
		general_rate = tax_rates_doc.get("general_rate") or 16.0
		reduced_rate = tax_rates_doc.get("reduced_rate") or 8.0
		additional_rate = tax_rates_doc.get("additional_rate") or 31.0
	except frappe.DoesNotExistError:
		general_rate = 16.0
		reduced_rate = 8.0
		additional_rate = 31.0
	except Exception:
		general_rate = 16.0
		reduced_rate = 8.0
		additional_rate = 31.0
	
	# La consulta SQL es la parte principal de la optimización
	data = frappe.db.sql("""
		SELECT
			siv.posting_date,
			siv.name AS sales_invoice_id,
			tc.tax_id AS customer_tax_id,
			siv.customer_name,
			tc.customer_type,
			siv.bill_no,
			siv.bill_control,
			CASE
				WHEN siv.is_return = 1 THEN 'NC'
				WHEN siv.is_debit_note = 1 THEN 'ND'
				ELSE 'REG'
			END AS transaction_type,
			siv.grand_total,
			COALESCE(tstac_ex.base_tax_amount, 0) AS exempt_amount,
			
			-- Ventas a NO Contribuyentes
			CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_gen.base_tax_amount, 0) ELSE 0 END AS base_general_non_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_gen.tax_amount, 0) ELSE 0 END AS iva_general_non_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_red.base_tax_amount, 0) ELSE 0 END AS base_reduced_non_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_red.tax_amount, 0) ELSE 0 END AS iva_reduced_non_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_add.base_tax_amount, 0) ELSE 0 END AS base_additional_non_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_add.tax_amount, 0) ELSE 0 END AS iva_additional_non_taxpayer,
			
			-- Ventas a Contribuyentes
			CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_gen.base_tax_amount, 0) ELSE 0 END AS base_general_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_gen.tax_amount, 0) ELSE 0 END AS iva_general_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_red.base_tax_amount, 0) ELSE 0 END AS base_reduced_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_red.tax_amount, 0) ELSE 0 END AS iva_reduced_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_add.base_tax_amount, 0) ELSE 0 END AS base_additional_taxpayer,
			CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_add.tax_amount, 0) ELSE 0 END AS iva_additional_taxpayer,

			COALESCE(ABS(tstac_retained.tax_amount), 0) AS iva_retained,
			siv.vat_withholding_voucher_number,
			siv.base_grand_total AS total_in_usd,
			COALESCE(ABS(tstac_retained.rate), 0) AS vat_withholding_rate
		FROM
			`tabSales Invoice` siv
		LEFT JOIN
			`tabCustomer` tc ON tc.name = siv.customer
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_ex
			ON tstac_ex.parent = siv.name AND tstac_ex.rate = 0
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_gen
			ON tstac_gen.parent = siv.name AND tstac_gen.rate = %(general_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_red
			ON tstac_red.parent = siv.name AND tstac_red.rate = %(reduced_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_add
			ON tstac_add.parent = siv.name AND tstac_add.rate = %(additional_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_retained
			ON tstac_retained.parent = siv.name AND tstac_retained.tax_amount < 0
		WHERE
			siv.company = %(company)s
			AND siv.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND siv.docstatus IN (1, 2)
		ORDER BY
			siv.posting_date ASC
	""", {
		"company": filters.get("company"),
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
		"general_rate": general_rate,
		"reduced_rate": reduced_rate,
		"additional_rate": additional_rate
	}, as_dict=1)
	
	return data

def get_total_row(data):
	"""
	Calcula los totales para las columnas relevantes y devuelve un diccionario.
	"""
	if not data:
		return {}

	totals = frappe._dict(
		{
			"grand_total": sum(d.get("grand_total", 0) for d in data),
			"exempt_amount": sum(d.get("exempt_amount", 0) for d in data),
			
			"base_general_non_taxpayer": sum(d.get("base_general_non_taxpayer", 0) for d in data),
			"iva_general_non_taxpayer": sum(d.get("iva_general_non_taxpayer", 0) for d in data),
			"base_reduced_non_taxpayer": sum(d.get("base_reduced_non_taxpayer", 0) for d in data),
			"iva_reduced_non_taxpayer": sum(d.get("iva_reduced_non_taxpayer", 0) for d in data),
			"base_additional_non_taxpayer": sum(d.get("base_additional_non_taxpayer", 0) for d in data),
			"iva_additional_non_taxpayer": sum(d.get("iva_additional_non_taxpayer", 0) for d in data),

			"base_general_taxpayer": sum(d.get("base_general_taxpayer", 0) for d in data),
			"iva_general_taxpayer": sum(d.get("iva_general_taxpayer", 0) for d in data),
			"base_reduced_taxpayer": sum(d.get("base_reduced_taxpayer", 0) for d in data),
			"iva_reduced_taxpayer": sum(d.get("iva_reduced_taxpayer", 0) for d in data),
			"base_additional_taxpayer": sum(d.get("base_additional_taxpayer", 0) for d in data),
			"iva_additional_taxpayer": sum(d.get("iva_additional_taxpayer", 0) for d in data),
			
			"iva_retained": sum(d.get("iva_retained", 0) for d in data),
			
			# Totales para las nuevas columnas de IGTF
			"igtf_base": sum(d.get("igtf_base", 0) for d in data),
			"igtf_amount": sum(d.get("igtf_amount", 0) for d in data),

			"total_in_usd": sum(d.get("total_in_usd", 0) for d in data),
		}
	)
	
	
	# El total se mostrará en la columna "Nro. de Factura" para una mejor visualización
	
	totals.bill_no = _("TOTALES")
	return totals


@frappe.whitelist()
def excel_builder(filters):
    """
    Genera y devuelve un archivo Excel para el reporte de Libro de Ventas.
    """
    try:
        frappe.msgprint("Iniciando la generación del archivo Excel en el servidor...")
        
        # Convertimos la cadena de texto de los filtros a un diccionario
        filters = json.loads(filters)

        data = get_sales_data(filters)
        
        # Si no se encontraron datos, mostramos una advertencia y detenemos la ejecución
        if not data:
            frappe.throw(_("No se encontraron datos de ventas para los filtros seleccionados."), title=_("Sin Datos"))
            return None

        columns = get_columns()

        # Crear un nuevo libro de trabajo y hoja
        wb = Workbook()
        ws = wb.active
        ws.title = "Libro de Ventas"

        # Estilos de celda
        bold_font = Font(bold=True)
        centered_alignment = Alignment(horizontal='center', vertical='center')
        thin_border = Border(
            left=Side(style='thin'), 
            right=Side(style='thin'), 
            top=Side(style='thin'), 
            bottom=Side(style='thin')
        )

        # 1. Encabezado del reporte
        company_name = frappe.db.get_value("Company", filters.get("company"), "company_name")
        company_tax_id = frappe.db.get_value("Company", filters.get("company"), "tax_id")
        from_date = getdate(filters.get("from_date"))
        to_date = getdate(filters.get("to_date"))

        ws.append([_("Libro de Ventas Fiscal")])
        ws.append([_("Nombre o Razón Social:"), company_name])
        ws.append([_("Número de Registro de Información Fiscal (RIF):"), company_tax_id])
        ws.append([_("Período Fiscal:"), f"{from_date.strftime('%d-%m-%Y')} - {to_date.strftime('%d-%m-%Y')}"])
        ws.append([]) # Fila en blanco

        # 2. Encabezados de la tabla
        headers = [col["label"] for col in columns]
        ws.append(headers)

        # Aplicar formato a los encabezados
        for cell in ws[6]:
            cell.font = bold_font
            cell.alignment = centered_alignment
            cell.border = thin_border

        # 3. Datos de la tabla
        for row_data in data:
            row = [row_data.get(col["fieldname"]) for col in columns]
            ws.append(row)
            
        # Guardar el libro de trabajo en un archivo temporal
        excel_file = BytesIO()
        wb.save(excel_file)
        excel_file.seek(0)

        file_name = f"LIBRO_VENTA_{from_date.strftime('%Y-%m-%d')}_a_{to_date.strftime('%Y-%m-%d')}.xlsx"
        
        # Devolver el archivo para su descarga
        frappe.local.response.filename = file_name
        frappe.local.response.filecontent = excel_file.getvalue()
        frappe.local.response.type = "download"

        # Mensaje de confirmación para depuración
        frappe.msgprint("El archivo Excel se ha creado correctamente en el servidor.")

    except Exception as e:
        frappe.log_error(title="Error al generar el Excel", message=str(e), exc=traceback.format_exc())
        frappe.msgprint(_("Ocurrió un error inesperado al generar el archivo. Por favor, revise el Log de Errores."), title="Error")
        # Devolver una respuesta vacía o de error para que la descarga no se inicie
        return None

@frappe.whitelist()
def remove_file(file_path):
    """
    Elimina un archivo del sistema de archivos del servidor.
    """
    if file_path and frappe.conf.get("temp_dir"):
        full_path = frappe.get_site_path("public", file_path)
        if frappe.utils.os.path.exists(full_path):
            frappe.utils.os.remove(full_path)
            return True
    return False





