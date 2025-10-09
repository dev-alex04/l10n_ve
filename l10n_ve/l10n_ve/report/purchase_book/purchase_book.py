# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt
import frappe
from frappe import _, throw
from frappe.utils import flt, getdate, format_date
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from collections import defaultdict
import calendar
from datetime import date
import base64
from io import StringIO
import json
import re

def get_report_summary(totals):
    summary = [
        {
            "value": totals.get("grand_total"),
            "label": "Total Compras",
            "datatype": "Currency"
        },
        {
            "value": totals.get("total_exempt"),
            "label": "Total Compras Sin Crédito",
            "datatype": "Currency"
        },
        {
            "value": totals.get("base_reducida"),
            "label": "Total Base Reducida",
            "datatype": "Currency"
        },
        {
            "value": totals.get("impuesto_reducida"),
            "label": "Total Impuesto Reducido",
            "datatype": "Currency"
        },
        {
            "value": totals.get("base_general"),
            "label": "Total Base General",
            "datatype": "Currency"
        },
        {
            "value": totals.get("impuesto_general"),
            "label": "Total Impuesto 16%",
            "datatype": "Currency"
        },
        {
            "value": totals.get("base_adicional"),
            "label": "Total Base Adicional",
            "datatype": "Currency"
        },
        {
            "value": totals.get("impuesto_adicional"),
            "label": "Total Impuesto 31%",
            "datatype": "Currency"
        },
        {
            "value": totals.get("taxes_and_charges_deducted"),
            "label": "Total IVA Retenido",
            "datatype": "Currency"
        },
        {
            "value": totals.get("iva_retenido_terceros"),
            "label": "IVA Retenido (a terceros)",
            "datatype": "Currency"
        },
        {
            "value": totals.get("anticipo_iva_importacion"),
            "label": "Anticipo de IVA (Importación)",
            "datatype": "Currency"
        },
        {
            "value": totals.get("total_igtf"),
            "label": "Total IGTF Pagado",
            "datatype": "Currency"
        },
    ]

    return summary

def get_totals_from_data(data):
    # Inicializar los contadores
    grand_total = 0
    total_exempt = 0
    base_reducida = 0
    impuesto_reducida = 0
    base_general = 0
    impuesto_general = 0
    base_adicional = 0
    impuesto_adicional = 0
    taxes_and_charges_deducted = 0
    iva_retenido_terceros = 0
    anticipo_iva_importacion = 0
    total_igtf = 0

    retencion_general = 0
    retencion_adicional = 0
    retencion_reducida = 0

    # Iterar sobre cada fila de la data
    for row in data:
        ret_monto = flt(row.get("taxes_and_charges_deducted"))
        grand_total += row.get("grand_total", 0)
        total_exempt += row.get("total_exempt", 0)
        base_reducida += row.get("base_reducida", 0)
        impuesto_reducida += row.get("impuesto_reducida", 0)
        base_general += row.get("base_general", 0)
        impuesto_general += row.get("impuesto_general", 0)
        base_adicional += row.get("base_adicional", 0)
        impuesto_adicional += row.get("impuesto_adicional", 0)
        total_igtf += row.get("total_igtf", 0)
        if row.get("nro_comprobante_retencion") and ret_monto > 0:
            taxes_and_charges_deducted += ret_monto
            iva_retenido_terceros += row.get("iva_retenido_terceros", 0)
            anticipo_iva_importacion += row.get("anticipo_iva_importacion", 0)


            bases = {
                "general": flt(row.get("base_general")),
                "adicional": flt(row.get("base_adicional")),
                "reducida": flt(row.get("base_reducida")),
            }

            # Encuentra la base más alta (que asume tiene el impuesto más representativo)
            if bases["general"] >= bases["adicional"] and bases["general"] >= bases["reducida"]:
                retencion_general += ret_monto
            elif bases["adicional"] >= bases["general"] and bases["adicional"] >= bases["reducida"]:
                retencion_adicional += ret_monto
            elif bases["reducida"] > 0:
                retencion_reducida += ret_monto
            else:
                retencion_general += ret_monto

    return {
        "grand_total": grand_total,
        "total_exempt": total_exempt,
        "base_reducida": base_reducida,
        "impuesto_reducida": impuesto_reducida,
        "base_general": base_general,
        "impuesto_general": impuesto_general,
        "base_adicional": base_adicional,
        "impuesto_adicional": impuesto_adicional,
        "taxes_and_charges_deducted": taxes_and_charges_deducted,
        "retencion_general": retencion_general,
        "iva_retenido_terceros": iva_retenido_terceros,
        "anticipo_iva_importacion": anticipo_iva_importacion,
        "total_igtf": total_igtf,
        "retencion_adicional": retencion_adicional,
        "retencion_reducida": retencion_reducida,

    }

def get_query_data(filters):
    from_date = filters.get("date_from")
    to_date = filters.get("to_date")

    if filters.get("fiscal_year") and filters.get("fiscal_month"):
        try:
            year = int(filters.get("fiscal_year"))
            month_mapping = {
                'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
                'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
            }
            month_num = month_mapping.get(filters.get("fiscal_month"))

            from_date = date(year, month_num, 1)
            last_day = calendar.monthrange(year, month_num)[1]
            to_date = date(year, month_num, last_day)

        except (ValueError, TypeError):
            frappe.throw(_("Valores de Año o Mes Fiscal inválidos."))

    if not from_date or not to_date:
        frappe.throw(_("Por favor, selecciona un rango de fechas o un período fiscal."))

    # Asegurarse de que from_date sea un objeto de fecha
    from_date_obj = getdate(from_date)

    conditions = "AND tPI.docstatus IN (1)"
    values = {}

    conditions += " AND tPI.posting_date BETWEEN %(from_date)s AND %(to_date)s"
    values['from_date'] = from_date
    values['to_date'] = to_date

    if filters.get("company"):
        conditions += " AND tPI.company = %(company)s"
        values['company'] = filters.get("company")

    query = f"""
        SELECT
            tPI.name as nro_factura,
            tPI.posting_date as posting_date,
            T4.tax_id as tax_id,
            tPI.supplier_name as supplier_name,
            tPI.is_return as tipo,
            tPI.bill_no as bill_no,
            tPI.bill_control as bill_control,
            tPI.grand_total as grand_total,
            tPI.total_exempt as total_exempt,
            tPI.credit_note_no,
            tPI.debit_note_no,
            tPI.affected_invoice_number,


            SUM(CASE WHEN T5.rate = 8 THEN (tPI.total-tPI.total_exempt) ELSE 0 END) as base_reducida,
            SUM(CASE WHEN T5.rate = 8 THEN T5.tax_amount ELSE 0 END) as impuesto_reducida,
            SUM(CASE WHEN T5.rate = 16 THEN (tPI.total-tPI.total_exempt) ELSE 0 END) as base_general,
            SUM(CASE WHEN T5.rate = 16 THEN T5.tax_amount ELSE 0 END) as impuesto_general,
            SUM(CASE WHEN T5.rate = 31 THEN (tPI.total-tPI.total_exempt) ELSE 0 END) as base_adicional,
            SUM(CASE WHEN T5.rate = 31 THEN T5.tax_amount ELSE 0 END) as impuesto_adicional,
            SUM(CASE WHEN T5.charge_type = 'VAT Withholding' THEN T5.tax_amount ELSE 0 END) as taxes_and_charges_deducted,
            MAX(T2.name) as nro_comprobante_retencion,
            MAX(T2.delivery_date) as fecha_entrega,
            MAX(CASE WHEN T5.charge_type = 'VAT Withholding' THEN T5.rate ELSE 0 END) as porcentaje_ret,

            CASE
                WHEN T4.type_of_person = 'Domiciled legal entity' THEN 'PJD'
                WHEN T4.type_of_person = 'Non-domiciled legal entity' THEN 'PJND'
                WHEN T4.type_of_person = 'Natural person domiciled' THEN 'PND'
                WHEN T4.type_of_person = 'Non-domiciled natural person' THEN 'PNND'
                ELSE 'N/A'
            END AS supplier_type,
            CASE
                WHEN tPI.docstatus = 2 THEN '03-Anu'
                WHEN MONTH(tPI.posting_date) != %(month)s OR YEAR(tPI.posting_date) != %(year)s THEN '04-Ajuste'
                WHEN tPI.is_return = 1 THEN '02-Comp'
                WHEN tPI.is_debit_note = 1 THEN '02-Comp'
                ELSE '01-Reg'
			END AS transaction_type,
            tPI.total AS taxable_base
        FROM
            `tabPurchase Invoice` as tPI
        LEFT JOIN
            `tabPurchase Taxes and Charges` as T5
            ON T5.parent = tPI.name
        LEFT JOIN
            `tabVAT Withholding Voucher Item` as T3
            ON T3.purchase_invoice = tPI.name
        LEFT JOIN
            `tabVAT Withholding Voucher` as T2
            ON T3.parent = T2.name
        LEFT JOIN
            `tabSupplier` as T4
            ON T4.name = tPI.supplier
        WHERE
            1=1 {conditions}
        GROUP BY tPI.name
    """

    values['month'] = from_date_obj.month
    values['year'] = from_date_obj.year

    return frappe.db.sql(query, values, as_dict=True)

def execute(filters=None):
    columns = [

        {"fieldname": "posting_date", "label": "Fecha Doc.", "fieldtype": "Date", "width": "auto"},
        {"fieldname": "tax_id", "label": "Rif", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "supplier_name", "label": "Nombre o Razón Social", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "supplier_type", "label": "Tipo", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_no", "label": "Nro. de Factura", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_control", "label": "Nro. de Control", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "credit_note_no", "label": "Nro. Nota de Crédito", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "debit_note_no", "label": "Nro. Nota de Débito", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "affected_invoice_number", "label": "Facturas Afectadas", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "nro_planilla", "label": "Nro. Planilla", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "nro_expediente_importacion", "label": "Nro. Expediente de Importación", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "transaction_type", "label": "Tipo de Transac.", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "grand_total", "label": "Total Compras Incluyendo el IVA", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "total_exempt", "label": "Compras sin Derecho a Crédito IVA", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "base_reducida", "label": "Base (Tasa Red. 8%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "impuesto_reducida", "label": "Impuesto (Tasa Red. 8%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "base_general", "label": "Base (Tasa Gen. 16%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "impuesto_general", "label": "Impuesto (Tasa Gen. 16%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "base_adicional", "label": "Base (Tasa Adic. 31%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "impuesto_adicional", "label": "Impuesto (Tasa Adic. 31%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "total_igtf", "label": "IGTF Pagado", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "nro_comprobante_retencion", "label": "Nro. Comprob. de Retención", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "fecha_entrega", "label": "Fecha de Entrega", "fieldtype": "Date", "width": "auto"},
        {"fieldname": "porcentaje_ret", "label": "% Ret.", "fieldtype": "Percent", "width": "auto"},
        {"fieldname": "taxes_and_charges_deducted", "label": "IVA Reducido (AL VENDEDOR)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "iva_retenido_terceros", "label": "IVA Retenido (a terceros)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "anticipo_iva_importacion", "label": "Anticipo de IVA (Importación)", "fieldtype": "Currency", "width": "auto"}

    ]

    data = get_query_data(filters)
    totals = get_totals_from_data(data)
    report_summary = get_report_summary(totals)
    return columns, data, None, None, report_summary

@frappe.whitelist()
def generate_xml_islr_file(filters=None):
    """
    Generates an XML string for ISLR retentions based on report filters.
    """
    if not filters:
        frappe.throw(_("Filtros de fecha son requeridos."))

    # Asegura que filters es un diccionario
    if isinstance(filters, str):
        filters = json.loads(filters)

    # Lógica para convertir el año y mes fiscal a un rango de fechas
    if filters.get("fiscal_year") and filters.get("fiscal_month"):
        try:
            year = int(filters.get("fiscal_year"))
            month_mapping = {
            'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
            'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10,
            'Noviembre': 11, 'Diciembre': 12
            }
            month_num = month_mapping.get(filters.get("fiscal_month"))

            from_date = date(year, month_num, 1)
            last_day = calendar.monthrange(year, month_num)[1]
            to_date = date(year, month_num, last_day)

            # Reemplaza los filtros originales con el nuevo rango de fechas
            filters["date_from"] = from_date.strftime('%Y-%m-%d')
            filters["to_date"] = to_date.strftime('%Y-%m-%d')

        except (ValueError, TypeError):
            frappe.throw(_("Valores de Año o Mes Fiscal inválidos."))


    invoices = frappe.db.sql("""
        SELECT
            tPI.name,
            tPI.supplier,
            tPI.posting_date,
            tPI.bill_no,
            tPI.bill_control,
            tPI.grand_total,
            tPTC.tax_amount AS retention_amount,
            tPTC.code AS code,
            tPI.affected_invoice_number,
            tPTC.rate AS retention_percentage
        FROM
            `tabPurchase Taxes and Charges` AS tPTC
        JOIN
            `tabPurchase Invoice` AS tPI ON tPTC.parent = tPI.name
        WHERE
            tPTC.charge_type = 'ISLR' AND tPI.docstatus = 1
            AND tPI.posting_date >= %(date_from)s
            AND tPI.posting_date <= %(to_date)s
            AND tPI.company = %(company)s
    """, filters, as_dict=True)

    if not invoices:
        return None

    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    company_doc = frappe.get_doc("Company", filters.get("company"))
    company_rif = (company_doc.tax_id or "").replace('-', '')
    periodo = getdate(from_date).strftime('%Y%m')

    invoices = frappe.db.sql("""
        SELECT
            REPLACE(tS.tax_id, '-', '') AS supplier_rif,
            tPI.bill_no,
            tPI.bill_control,
            tPI.posting_date,
            tPTC.code,
            tPI.grand_total,
            tPTC.rate AS retention_percentage
        FROM `tabPurchase Taxes and Charges` AS tPTC
        JOIN `tabPurchase Invoice` AS tPI ON tPTC.parent = tPI.name
        JOIN `tabSupplier` AS tS ON tPI.supplier = tS.name
        WHERE
            tPTC.charge_type = 'ISLR' AND tPI.docstatus = 1
            AND tPI.posting_date BETWEEN %(date_from)s AND %(to_date)s
            AND tPI.company = %(company)s
    """, filters, as_dict=True)

    if not invoices:
        frappe.msgprint(_("No se encontraron retenciones de "
                        "ISLR para los filtros seleccionados."))
        return None

    # Construcción del XML
    root = Element('RelacionRetencionesISLR', {'RifAgente': company_rif, 'Periodo': periodo})

    for inv in invoices:
        detalle = SubElement(root, 'DetalleRetencion')
        SubElement(detalle, 'RifRetenido').text = inv.supplier_rif or 'N/A'
        SubElement(detalle, 'NumeroFactura').text = inv.bill_no or 'N/A'
        SubElement(detalle, 'NumeroControl').text = inv.bill_control or 'N/A'
        SubElement(detalle, 'FechaOperacion').text = getdate(inv.posting_date).strftime('%d/%m/%Y')
        SubElement(detalle, 'CodigoConcepto').text = inv.code or 'N/A'
        SubElement(detalle, 'MontoOperacion').text = f"{flt(inv.grand_total):.2f}"
        SubElement(detalle, 'PorcentajeRetencion').text = f"{flt(inv.retention_percentage)}"

    # Formatear para una salida legible (pretty print)
    rough_string = tostring(root, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    pretty_xml_as_string = reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode()

    return pretty_xml_as_string

@frappe.whitelist()
def generate_txt_file(filters):

    try:

        filters = frappe.parse_json(filters)
        data = get_query_data(filters)
        # Obtenemos los datos del reporte usando la nueva función

        if not data:
            frappe.throw(_("No se encontraron datos para el período seleccionado."))

        company_doc = frappe.get_doc("Company", filters.get("company"))
        company_rif = company_doc.tax_id or ""

        if not company_rif:
            frappe.throw(_("El RIF de la compañía no está configurado. "
            "Por favor, agregue el RIF en la configuración de la compañía."))

        # Lógica para determinar el período del TXT (mes y año)
        fiscal_year = str(filters.get("fiscal_year"))
        fiscal_month_name = filters.get("fiscal_month")

        if not fiscal_year or not fiscal_month_name:
            date_from = getdate(filters.get("date_from"))

            month = str(date_from.month).zfill(2)
            year = str(date_from.year)

        else:
            month_mapping = {
                'Enero': '01', 'Febrero': '02', 'Marzo': '03', 'Abril': '04', 'Mayo': '05', 'Junio': '06',
                'Julio': '07', 'Agosto': '08', 'Septiembre': '09', 'Octubre': '10', 'Noviembre': '11', 'Diciembre': '12'
            }
            month = month_mapping.get(fiscal_month_name)
            year = fiscal_year

        periodo = f"{year}{month}"

        content_lines = []
        for row in data:
            # Determinamos la alícuota a mostrar
            tax_rate = "0"
            if flt(row.get("base_general")) > 0:
                tax_rate = "16"
            elif flt(row.get("base_reducida")) > 0:
                tax_rate = "8"
            elif flt(row.get("base_adicional")) > 0:
                tax_rate = "31"

            if row.get("credit_note_no"):
                transaction_code = "03"
            elif row.get("debit_note_no"):
                transaction_code = "02"
            else:
                transaction_code = "01"

            document_number = row.get("credit_note_no") or row.get("debit_note_no") or row.get("bill_no") or "0"

            line_data = [
                str(company_rif),
                str(periodo),
                getdate(row.get("posting_date")).strftime("%Y-%m-%d") if row.get("posting_date") else "",
                "V" if flt(row.get("tipo")) == 1 else "C",
                transaction_code,
                (row.get("tax_id") or "0").replace('-', ''),
                document_number,
                row.get("bill_control") or "0",
                f"{flt(row.get('grand_total') or 0):.2f}",
                f"{flt(row.get('taxable_base') or 0):.2f}",
                f"{flt(row.get('taxes_and_charges_deducted') or 0):.2f}",
                row.get("affected_invoice_number") or "0",
                row.get("nro_comprobante_retencion") or "0",
                f"{flt(row.get('total_exempt') or 0):.2f}",
                f"{flt(tax_rate):.2f}",
                "0",
            ]
            content_lines.append("\t".join(line_data))

        content = "\n".join(content_lines) + "\n"
        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        return {
            "type": "download",
            "filename": f"IVA_Compras_TXT-{company_doc.abbr}-{periodo}.txt",
            "filecontent": encoded_content
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en generate_txt_file")
        frappe.throw(_(f"Ocurrió un error al generar el archivo TXT: {e}"))
