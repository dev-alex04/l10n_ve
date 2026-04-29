# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt
import frappe
from frappe import _
from frappe.utils import flt, getdate

import base64

from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring


def execute(filters=None):
    """Punto de entrada principal para el Reporte de Libro de Compras."""
    filters = filters or {}

    if not filters.get("company"):
        frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))
    if not filters.get("from_date") and not filters.get("date_from"):
        frappe.throw(_("Debe ingresar la Fecha Desde."))
    if not filters.get("to_date"):
        frappe.throw(_("Debe ingresar la Fecha Hasta."))

    columns: list[dict] = get_columns()

    data: list[dict] = get_query_data(filters)
    totals: dict = get_totals_from_data(data)
    report_summary: dict = get_report_summary(totals)

    return columns, data, None, None, report_summary


def get_columns() -> list[dict]:

    return [
        {"fieldname": "bill_date", "label": "Fecha Doc.", "fieldtype": "Data", "width": "auto"},
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
        {"fieldname": "islr_retention_applied", "label": "Retención ISLR Aplicada", "fieldtype": "Data", "width": "auto", "hidden": 1},
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

def _get_tax_rates() -> tuple[float, float, float]:
    """Lee las alícuotas de IVA desde la configuración centralizada."""
    try:
        tax_rates_doc = frappe.get_cached_doc("Taxes Rates", "Taxes Rates")
        return (
            tax_rates_doc.get("general_rate") or 16.0,
            tax_rates_doc.get("reduced_rate") or 8.0,
            tax_rates_doc.get("additional_rate") or 31.0,
        )
    except frappe.DoesNotExistError:
        frappe.log_error(
            "Reporte Libro de Compras: DocType 'Taxes Rates' no existe, usando tasas por defecto.",
            "Purchase Book Report"
        )
        return 16.0, 8.0, 31.0
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Purchase Book Report - Error al leer Taxes Rates")
        return 16.0, 8.0, 31.0


def get_query_data(filters: dict) -> list[dict]:
    """Ejecuta la query del Libro de Compras con los filtros proporcionados."""
    from_date: str
    to_date: str
    from_date, to_date = _get_date_range_from_filters(filters)
    filters["from_date"] = from_date
    filters["to_date"] = to_date

    query: str = get_query(filters)

    from_date_obj = getdate(from_date)

    company_currency: str = frappe.get_cached_value(
        "Company", filters.get("company"), "default_currency"
    )

    general_rate, reduced_rate, additional_rate = _get_tax_rates()

    values: dict = {
        "from_date": from_date,
        "to_date": to_date,
        "company_currency": company_currency,
        "month": from_date_obj.month,
        "year": from_date_obj.year,
        "general_rate": general_rate,
        "reduced_rate": reduced_rate,
        "additional_rate": additional_rate,
    }

    if filters.get("company"):
        values["company"] = filters.get("company")

    data: list[dict] = frappe.db.sql(query, values, as_dict=True)

    return data


def get_query(filters: dict) -> str:
    """Construye la query SQL del Libro de Compras."""
    conditions: str = "AND tPI.docstatus = 1"
    conditions += " AND tPI.posting_date BETWEEN %(from_date)s AND %(to_date)s"

    if filters.get("company"):
        conditions += " AND tPI.company = %(company)s"

    query: str = """
        WITH InvoiceData AS (
            SELECT
                tPI.name,
                tPI.posting_date,
                tPI.supplier,
                tPI.supplier_name,
                tPI.is_return,
                tPI.bill_no,
                tPI.bill_control,
                tPI.credit_note_no,
                tPI.debit_note_no,
                tPI.affected_invoice_number,
                tPI.total_igtf,
                tPI.bill_date,
                tPI.is_debit_note,
                tPI.base_grand_total,
                tPI.base_total,
                tPI.total_exempt,
                (CASE WHEN tPI.currency != %(company_currency)s
                    THEN tPI.conversion_rate ELSE 1 END) AS conversion_rate
            FROM `tabPurchase Invoice` AS tPI
            WHERE 1=1 {conditions}
        )
        SELECT
            inv.name AS nro_factura,
            inv.posting_date,
            supp.tax_id,
            inv.supplier_name,
            inv.is_return AS tipo,
            inv.bill_no,
            inv.bill_control,
            inv.base_grand_total AS grand_total,
            inv.total_exempt * inv.conversion_rate AS total_exempt,
            inv.credit_note_no,
            inv.debit_note_no,
            inv.affected_invoice_number,
            inv.total_igtf,
            DATE_FORMAT(inv.bill_date, '%%d/%%m/%%Y') AS bill_date,

            -- Bases imponibles por alícuota (base_total ya en VEF, solo resta exempt)
            SUM(CASE WHEN ptc.rate = %(reduced_rate)s
                AND COALESCE(ptc.charge_type, '') != 'VAT Withholding'
                THEN (inv.base_total - inv.total_exempt * inv.conversion_rate) ELSE 0 END) AS base_reducida,
            SUM(CASE WHEN ptc.rate = %(reduced_rate)s
                AND COALESCE(ptc.charge_type, '') != 'VAT Withholding'
                THEN ptc.base_tax_amount ELSE 0 END) AS impuesto_reducida,
            SUM(CASE WHEN ptc.rate = %(general_rate)s
                AND COALESCE(ptc.charge_type, '') != 'VAT Withholding'
                THEN (inv.base_total - inv.total_exempt * inv.conversion_rate) ELSE 0 END) AS base_general,
            SUM(CASE WHEN ptc.rate = %(general_rate)s
                AND COALESCE(ptc.charge_type, '') != 'VAT Withholding'
                THEN ptc.base_tax_amount ELSE 0 END) AS impuesto_general,
            SUM(CASE WHEN ptc.rate = %(additional_rate)s
                AND COALESCE(ptc.charge_type, '') != 'VAT Withholding'
                THEN (inv.base_total - inv.total_exempt * inv.conversion_rate) ELSE 0 END) AS base_adicional,
            SUM(CASE WHEN ptc.rate = %(additional_rate)s
                AND COALESCE(ptc.charge_type, '') != 'VAT Withholding'
                THEN ptc.base_tax_amount ELSE 0 END) AS impuesto_adicional,

            -- Retención IVA desde comprobantes de retención (ya en VEF)
            COALESCE(ret.tax_amount_vat, 0) AS taxes_and_charges_deducted,
            ret.voucher_number AS nro_comprobante_retencion,
            DATE_FORMAT(ret.delivery_date, '%%d/%%m/%%Y') AS fecha_entrega,
            COALESCE(ret.withholding_rate, 0) AS porcentaje_ret,

            MAX(CASE
                WHEN supp.type_of_person = 'Domiciled legal entity' THEN 'PJD'
                WHEN supp.type_of_person = 'Non-domiciled legal entity' THEN 'PJND'
                WHEN supp.type_of_person = 'Natural person domiciled' THEN 'PND'
                WHEN supp.type_of_person = 'Non-domiciled natural person' THEN 'PNND'
                ELSE 'N/A'
            END) AS supplier_type,
            MAX(CASE
                WHEN inv.is_return = 1 THEN '02-Comp'
                WHEN inv.is_debit_note = 1 THEN '02-Comp'
                ELSE '01-Reg'
            END) AS transaction_type,
            CASE WHEN islr_ref.has_islr = 1 THEN 'Sí' ELSE 'No' END AS islr_retention_applied,
            (inv.base_total - inv.total_exempt * inv.conversion_rate) AS taxable_base
        FROM
            InvoiceData AS inv
        LEFT JOIN
            `tabPurchase Taxes and Charges` AS ptc
            ON ptc.parent = inv.name
        -- Subquery: retención IVA aprobada (evita fan-out)
        LEFT JOIN (
            SELECT
                wvi.purchase_invoice,
                MAX(wvi.tax_amount_vat) AS tax_amount_vat,
                MAX(wvi.withholding_rate) AS withholding_rate,
                MAX(wv.voucher_number) AS voucher_number,
                MAX(wv.delivery_date) AS delivery_date
            FROM `tabVAT Withholding Voucher Item` wvi
            INNER JOIN `tabVAT Withholding Voucher` wv
                ON wvi.parent = wv.name AND wv.docstatus = 1
            GROUP BY wvi.purchase_invoice
        ) AS ret ON ret.purchase_invoice = inv.name
        LEFT JOIN
            `tabSupplier` AS supp
            ON supp.name = inv.supplier
        -- Subquery: flag ISLR con pago aprobado (evita fan-out)
        LEFT JOIN (
            SELECT
                pe_ref.reference_name,
                1 AS has_islr
            FROM `tabPayment Entry Reference` pe_ref
            INNER JOIN `tabPayment Entry` pe
                ON pe.name = pe_ref.parent AND pe.docstatus = 1
            WHERE pe_ref.reference_doctype = 'Purchase Invoice'
                AND pe_ref.islr_concept IS NOT NULL
                AND pe_ref.islr_concept != ''
            GROUP BY pe_ref.reference_name
        ) AS islr_ref ON islr_ref.reference_name = inv.name

        GROUP BY inv.name
        ORDER BY inv.bill_date ASC
    """
    query = query.replace("{conditions}", conditions)

    return query


def get_totals_from_data(data: list[dict]) -> dict:
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
        if row.get("nro_comprobante_retencion") and ret_monto != 0:
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


def get_report_summary(totals: dict) -> dict:
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


def _get_date_range_from_filters(filters: dict) -> tuple[str, str]:
    """Extrae el rango de fechas desde los filtros del reporte."""
    from_date: str | None = filters.get("from_date") or filters.get("date_from")
    to_date: str | None = filters.get("to_date")

    if not from_date or not to_date:
        frappe.throw(_("Por favor, seleccione un rango de fechas para generar el reporte."))

    if getdate(from_date) > getdate(to_date):
        frappe.throw(_("La Fecha Desde no puede ser posterior a la Fecha Hasta."))

    return from_date, to_date


@frappe.whitelist()
def generate_xml_islr_file(filters: dict | str | None = None) -> str | None:
    """
    Generates an XML string for ISLR retentions based on report filters.
    """
    try:
        if not filters:
            frappe.throw(_("Filtros son requeridos."))

        if isinstance(filters, str):
            filters = frappe.parse_json(filters)

        from_date: str
        to_date: str
        from_date, to_date = _get_date_range_from_filters(filters)
        filters["from_date"] = from_date
        filters["to_date"] = to_date

        company_doc = frappe.get_doc("Company", filters.get("company"))
        company_rif = (company_doc.tax_id or "").replace('-', '')
        if not company_rif:
            frappe.throw(_("El RIF de la compañía es obligatorio para generar el XML de ISLR."))

        periodo = getdate(from_date).strftime("%Y%m")

        retentions = frappe.db.sql("""
            SELECT
                REPLACE(supp.tax_id, '-', '') AS supplier_rif,
                pi.bill_no,
                pi.bill_control,
                pe.posting_date,
                ref.islr_concept AS islr_concept,
                tab.codigo AS codigo_concepto,
                ali.aliquot AS porcentaje_retencion,
                ref.islr_base_amount AS monto_operacion,
                supp.type_of_person
            FROM `tabPayment Entry Reference` AS ref
            JOIN `tabPayment Entry` AS pe ON ref.parent = pe.name
            JOIN `tabPurchase Invoice` AS pi ON ref.reference_name = pi.name
            JOIN `tabSupplier` AS supp ON pi.supplier = supp.name
            LEFT JOIN `tabTabulator ISLR` AS tab ON ref.islr_concept = tab.name
            LEFT JOIN `tabTabulator ISLR Aliquots` AS ali ON tab.name = ali.parent AND supp.type_of_person = ali.types_of_person
            WHERE
                pe.docstatus = 1
                AND pe.company = %(company)s
                AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND ref.reference_doctype = 'Purchase Invoice'
                AND ref.islr_concept IS NOT NULL
                AND ref.islr_concept != ''
        """, filters, as_dict=True)

        if not retentions:
            frappe.msgprint(_("No se encontraron retenciones de ISLR para los filtros seleccionados."))
            return None

        root = Element("RelacionRetencionesISLR", {"RifAgente": company_rif, "Periodo": periodo})
        processing_errors = []

        for ret in retentions:
            if not ret.codigo_concepto or ret.porcentaje_retencion is None:
                error_msg = _("No se encontró configuración de alícuota para el concepto '{0}'" \
                " y tipo de persona '{1}' (Factura: {2}).").format(ret.islr_concept, ret.type_of_person, ret.bill_no or 'N/A')

                if error_msg not in processing_errors:
                    processing_errors.append(error_msg)
                continue

            detalle = SubElement(root, "DetalleRetencion")
            SubElement(detalle, "RifRetenido").text = ret.supplier_rif or "N/A"
            SubElement(detalle, "NumeroFactura").text = ret.bill_no or "N/A"
            SubElement(detalle, "NumeroControl").text = str(ret.bill_control) if ret.bill_control is not None else "N/A"
            SubElement(detalle, "FechaOperacion").text = getdate(ret.posting_date).strftime("%d/%m/%Y")
            SubElement(detalle, "CodigoConcepto").text = ret.codigo_concepto
            SubElement(detalle, "MontoOperacion").text = f"{flt(ret.monto_operacion):.2f}"
            SubElement(detalle, "PorcentajeRetencion").text = f"{flt(ret.porcentaje_retencion)}"

        if processing_errors:
            frappe.msgprint(_("Se encontraron errores al procesar algunas retenciones:<br>")
                            + "<br>".join(processing_errors),
                            title=_("Errores de Procesamiento"),
                            indicator="orange")

        # Formatear para una salida legible (pretty print)
        rough_string = tostring(root, "utf-8")
        reparsed = minidom.parseString(rough_string)
        pretty_xml_as_string = reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode()

        return pretty_xml_as_string

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en generate_xml_islr_file")
        frappe.throw(_("Ocurrió un error al generar el archivo XML de ISLR: {0}").format(e))

@frappe.whitelist()
def generate_txt_file(filters: dict | str) -> dict:

    try:
        if isinstance(filters, str):
            filters = frappe.parse_json(filters)

        from_date: str
        to_date: str
        from_date, to_date = _get_date_range_from_filters(filters)
        filters["from_date"] = from_date
        filters["to_date"] = to_date

        company_doc = frappe.get_doc("Company", filters.get("company"))
        company_rif = company_doc.tax_id or ""
        company_rif = company_rif.replace('-', '')

        if not company_rif:
            frappe.throw(_("El RIF de la compañía no está configurado."))

        periodo = getdate(from_date).strftime('%Y%m')
        data: list[dict] = get_query_data(filters)
        invoices_with_voucher = [row for row in data if row.get("nro_comprobante_retencion")]

        if not invoices_with_voucher:
            # Si no hay facturas con comprobante, crea una línea con valores por defecto
            line_data = [

                str(company_rif) or "",
                str(periodo) or "",

            ] + ["0"] * 14

            content = "\t".join(line_data) + "\n"
            encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        else:

            content_lines = []
            for row in invoices_with_voucher:

                tax_rate = "0"
                if flt(row.get("base_general")) != 0:
                    tax_rate = "16"
                elif flt(row.get("base_reducida")) != 0:
                    tax_rate = "8"
                elif flt(row.get("base_adicional")) != 0:
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
                    "C",
                    transaction_code,
                    (row.get("tax_id") or "0").replace('-', ''),
                    document_number,
                    row.get("bill_control") or "0",
                    f"{abs(flt(row.get('grand_total') or 0)):.2f}",
                    f"{abs(flt(row.get('taxable_base') or 0)):.2f}",
                    f"{abs(flt(row.get('taxes_and_charges_deducted') or 0)):.2f}",
                    row.get("affected_invoice_number") or "0",
                    row.get("nro_comprobante_retencion") or "0",
                    f"{abs(flt(row.get('total_exempt') or 0)):.2f}",
                    f"{abs(flt(tax_rate)):.2f}",
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
        frappe.throw(_("Ocurrió un error al generar el archivo TXT: {0}").format(e))
