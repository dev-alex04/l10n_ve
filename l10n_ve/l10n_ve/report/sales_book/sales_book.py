# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
    """
    Punto de entrada principal para el Reporte de Libro de Ventas.
    Devuelve las columnas y los datos basados en los filtros.
    """
    filters = filters or {}

    # Validar campos obligatorios
    if not filters.get("company"):
        frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))
    if not filters.get("from_date"):
        frappe.throw(_("Debe ingresar la Fecha Desde."))
    if not filters.get("to_date"):
        frappe.throw(_("Debe ingresar la Fecha Hasta."))

    # Validar rango: from_date no puede ser posterior a to_date
    if getdate(filters["from_date"]) > getdate(filters["to_date"]):
        frappe.throw(_("La Fecha Desde no puede ser posterior a la Fecha Hasta."))

    columns: list[dict] = get_columns()

    main_data: list[dict]
    adjustment_data: list[dict]
    main_data, adjustment_data = get_sales_data(filters)
    data = main_data + adjustment_data

    if data:
        for i, row in enumerate(data):
            row["sequence_number"] = i + 1

    # Calcular totales y resumen usando solo los datos del período principal
    main_totals: dict = get_total_row(main_data)

    report_summary: list[dict] = get_report_summary(main_totals)

    return columns, data, None, None, report_summary


def get_columns() -> list[dict]:
    """
    Define las columnas de la tabla del reporte. Se han simplificado las etiquetas para evitar errores en el archivo Excel.
    """
    return [

        {"label": _("Sucursal"), "fieldname": "branch", "fieldtype": "Data", "width": "auto"},
        {"label": _("Fecha"), "fieldname": "posting_date", "fieldtype": "Data", "width": "auto"},
        {"label": _("RIF del Cliente"), "fieldname": "customer_tax_id", "fieldtype": "Data", "width": "auto"},
        {"label": _("Nombre del Cliente"), "fieldname": "customer_name", "fieldtype": "Data", "width": "auto"},
        {"label": _("Tipo de Persona"), "fieldname": "customer_type", "fieldtype": "Data", "width": "auto"},
        {"label": _("Serie Fiscal"), "fieldname": "fiscal_series", "fieldtype": "Data", "width": "auto"},
        {"label": _("Nro. de Factura"), "fieldname": "bill_no", "fieldtype": "Data", "width": "auto"},
        {"label": _("Nro. de Control"), "fieldname": "bill_control", "fieldtype": "Data", "width": "auto"},
        {"label": _("Nro. Nota de Credito"), "fieldname": "credit_note_no", "fieldtype": "Data", "width": "auto"},
        {"label": _("Nro. Nota de Debito"), "fieldname": "debit_note_no", "fieldtype": "Data", "width": "auto"},
        {"label": _("Facturas afectadas"), "fieldname": "affected_invoice_number", "fieldtype": "Data", "width": "auto"},
        {"label": _("Tipo de Transaccion"), "fieldname": "transaction_type", "fieldtype": "Data", "width": "auto"},
        {"label": _("Total Incl. IVA"), "fieldname": "grand_total", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Ventas Export. FOB"), "fieldname": "ve_fob", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Ventas internas no Gravadas"), "fieldname": "total_exempt", "fieldtype": "Currency", "width": "auto"},

        # Columnas para Ventas a No Contribuyentes

        {"label": _("Base Imponible No C. R"), "fieldname": "base_reduced_non_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("IVA No C. R"), "fieldname": "iva_reduced_non_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Base Imponible No C. G"), "fieldname": "base_general_non_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("IVA No C. G"), "fieldname": "iva_general_non_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Base Imponible No C. A"), "fieldname": "base_additional_non_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("IVA No C. A"), "fieldname": "iva_additional_non_taxpayer", "fieldtype": "Currency", "width": "auto"},

        # Columnas para Ventas a Contribuyentes

        {"label": _("Base Imponible C. R"), "fieldname": "base_reduced_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("IVA C. R"), "fieldname": "iva_reduced_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Base Imponible C. G"), "fieldname": "base_general_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("IVA C. G"), "fieldname": "iva_general_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Base Imponible C. A"), "fieldname": "base_additional_taxpayer", "fieldtype": "Currency", "width": "auto"},
        {"label": _("IVA C. A"), "fieldname": "iva_additional_taxpayer", "fieldtype": "Currency", "width": "auto"},

        # Campos de Retencion de IVA
        {"label": _("IVA Retenido"), "fieldname": "iva_retained", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Nro. Comprobante de Retencion IVA"), "fieldname": "vat_withholding_voucher_number", "fieldtype": "Data", "width": "auto"},
        {"label": _("Fecha Comprobante"), "fieldname": "withholding_date", "fieldtype": "Date", "width": "auto"},
        {"label": _("Tasa de Retencion IVA"), "fieldname": "vat_withholding_rate", "fieldtype": "Percent", "width": "auto"},

        # Columnas para IGTF Impuesto a las Grandes Transacciones Financieras
        {"label": _("Base Imponible IGTF"), "fieldname": "base_amount_igtf", "fieldtype": "Currency", "width": "auto"},
        {"label": _("Tasa de IGTF"), "fieldname": "igtf_rate", "fieldtype": "Percent", "width": "auto"},
        {"label": _("Monto IGTF"), "fieldname": "total_igtf", "fieldtype": "Currency", "width": "auto"},

    ]


def get_sales_data(filters: dict) -> tuple[list[dict], list[dict]]:

    """
    Obtiene los datos del reporte ejecutando una consulta SQL optimizada.
    """
    company_currency: str = frappe.get_cached_value(
        "Company", filters.get("company"), "default_currency"
    )

    try:
        tax_rates_doc = frappe.get_cached_doc("Taxes Rates", "Taxes Rates")
        general_rate = tax_rates_doc.get("general_rate") or 16.0
        reduced_rate = tax_rates_doc.get("reduced_rate") or 8.0
        additional_rate = tax_rates_doc.get("additional_rate") or 31.0
    except frappe.DoesNotExistError:
        frappe.log_error(
            "Reporte Libro de Ventas: DocType 'Taxes Rates' no existe, usando tasas por defecto.",
            "Sales Book Report"
        )
        general_rate = 16.0
        reduced_rate = 8.0
        additional_rate = 31.0
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Sales Book Report - Error al leer Taxes Rates")
        general_rate = 16.0
        reduced_rate = 8.0
        additional_rate = 31.0

    igtf_rate: float = 0.0
    try:
        igtf_rate = frappe.db.get_single_value(
            "Venezuela Account Settings", "igtf_rate", cache=True
        ) or 0.0
    except Exception:
        pass

    # Si HKA está activo, solo incluir documentos que HKA ya certificó.
    # La presencia de '"numeroControl"' en remarks indica que HKA
    # retornó exitosamente y asignó número de control fiscal.
    hka_filter_inv: str = ""
    hka_filter_nc: str = ""
    try:
        hka_enabled = frappe.db.get_single_value("TFHKA Settings", "enabled", cache=True)
        if hka_enabled:
            hka_filter_inv = "AND LOCATE('\"numeroControl\"', siv.remarks) > 0"
            hka_filter_nc = "AND LOCATE('\"numeroControl\"', nc.remarks) > 0"
    except Exception:
        pass

    # La consulta SQL es la parte principal de la optimización
    query_base: str = get_query()

    # Filtro opcional de sucursal: se inyecta en ambas fuentes del UNION ALL.
    branch: str = filters.get("branch") or ""
    branch_filter_inv: str = "AND siv.branch = %(branch)s" if branch else ""
    branch_filter_nc: str = "AND nc.branch = %(branch)s" if branch else ""

    # --- Datos del período principal ---
    # Dos placeholders independientes: {inv_cond} para tabSales Invoice (alias siv),
    # {nc_cond} para tabVE Sales Credit Note (alias nc).
    main_query = (
        query_base
        .replace("{inv_cond}", f"siv.posting_date BETWEEN %(from_date)s AND %(to_date)s {hka_filter_inv} {branch_filter_inv}")
        .replace("{nc_cond}", f"nc.posting_date BETWEEN %(from_date)s AND %(to_date)s {hka_filter_nc} {branch_filter_nc}")
    )
    main_query += """
        ORDER BY
            posting_date_sort ASC
    """
    main_query = main_query.replace(
        "{transaction_type_placeholder}",
        """CASE
                WHEN siv.is_void = 1 THEN '03-Anu'
                WHEN siv.is_return = 1 THEN '02-Comp'
                WHEN siv.is_debit_note = 1 THEN '02-Comp'
                ELSE '01-Reg'
            END AS transaction_type,"""
    )

    # --- Datos de ajuste de períodos anteriores ---
    adjustment_query = (
        query_base
        .replace("{inv_cond}", f"""
            siv.posting_date < %(from_date)s
            AND siv.withholding_date BETWEEN %(from_date)s AND %(to_date)s
            {hka_filter_inv}
            {branch_filter_inv}
        """)
        .replace("{nc_cond}", f"""
            nc.posting_date < %(from_date)s
            AND nc.withholding_date BETWEEN %(from_date)s AND %(to_date)s
            {hka_filter_nc}
            {branch_filter_nc}
        """)
    )
    adjustment_query += """
        ORDER BY
            withholding_date_sort ASC
    """
    adjustment_query = adjustment_query.replace(
        "{transaction_type_placeholder}",
        "'04-Ajus' AS transaction_type,"
    )

    sql_params: dict = {
        "company": filters.get("company"),
        "from_date": filters.get("from_date"),
        "to_date": filters.get("to_date"),
        "general_rate": general_rate,
        "reduced_rate": reduced_rate,
        "additional_rate": additional_rate,
        "company_currency": company_currency,
        "fiscal_cutoff": _FISCAL_CUTOFF_DATE,
    }
    if branch:
        sql_params["branch"] = branch

    main_data = frappe.db.sql(main_query, sql_params, as_dict=1)

    # Pre-check barato: evita correr la query pesada de ajuste cuando no hay
    # retenciones de períodos anteriores para el rango consultado (caso típico).
    # Se consultan ambas fuentes del UNION ALL para no omitir NCs con retención previa.
    has_prior_withholding = frappe.db.sql("""
        SELECT 1 FROM `tabSales Invoice`
        WHERE company = %(company)s
          AND withholding_date BETWEEN %(from_date)s AND %(to_date)s
          AND posting_date < %(from_date)s
          AND bill_no IS NOT NULL AND bill_no != ''
          AND bill_control IS NOT NULL AND bill_control != ''
        UNION ALL
        SELECT 1 FROM `tabVE Sales Credit Note`
        WHERE company = %(company)s
          AND withholding_date BETWEEN %(from_date)s AND %(to_date)s
          AND posting_date < %(from_date)s
          AND bill_no IS NOT NULL AND bill_no != ''
          AND bill_control IS NOT NULL AND bill_control != ''
        LIMIT 1
    """, sql_params)
    adjustment_data = (
        frappe.db.sql(adjustment_query, sql_params, as_dict=1)
        if has_prior_withholding else []
    )

    for row in main_data + adjustment_data:
        if row.get("base_amount_igtf") > 0 or row.get("total_igtf") > 0:
            row["igtf_rate"] = igtf_rate
        else:
            row["igtf_rate"] = 0

    return main_data, adjustment_data


_FISCAL_CUTOFF_DATE: str = '2026-04-15'
"""Fecha límite fiscal. Facturas con posting_date <= esta fecha se calculan con
la lógica legacy (tax_amount * conversion_rate) porque fueron declaradas al SENIAT.
Facturas posteriores usan base_* almacenados directamente."""


def _get_cte() -> str:
    """CTE InvoiceData: incluye base_net_total para el cálculo nuevo."""
    return """
        WITH InvoiceData AS (

            -- FUENTE A: Facturas de venta y Notas de Débito
            SELECT
                siv.name, siv.branch, siv.posting_date, siv.customer,
                siv.customer_name, siv.bill_no, siv.bill_control,
                siv.credit_note_no, siv.debit_note_no,
                siv.affected_invoice_number,
                siv.vat_withholding_voucher_number, siv.withholding_date,
                siv.is_void, siv.is_return, siv.is_debit_note,
                (CASE WHEN siv.currency != %(company_currency)s THEN siv.conversion_rate ELSE 1 END) AS conversion_rate,
                1 AS amount_sign,
                siv.base_net_total,
                siv.total_exempt,
                siv.base_amount_igtf,
                siv.total_igtf
            FROM `tabSales Invoice` siv
            WHERE siv.company = %(company)s
                AND siv.is_return = 0
                AND (siv.docstatus = 1 OR (siv.docstatus = 2 AND siv.is_void = 1))
                AND siv.bill_no IS NOT NULL AND siv.bill_no != ''
                AND siv.bill_control IS NOT NULL AND siv.bill_control != ''
                AND {inv_cond}

            UNION ALL

            -- FUENTE B: Notas de Crédito venezolanas
            SELECT
                nc.name, nc.branch, nc.posting_date, nc.customer,
                nc.customer_name, nc.bill_no, nc.bill_control,
                nc.bill_no AS credit_note_no,
                NULL AS debit_note_no,
                COALESCE(si_orig.bill_no, nc.return_against) AS affected_invoice_number,
                nc.vat_withholding_voucher_number, nc.withholding_date,
                0 AS is_void, 1 AS is_return, 0 AS is_debit_note,
                (CASE WHEN nc.currency != %(company_currency)s THEN nc.conversion_rate ELSE 1 END) AS conversion_rate,
                -1 AS amount_sign,
                nc.base_net_total,
                nc.total_exempt,
                0 AS base_amount_igtf,
                0 AS total_igtf
            FROM `tabVE Sales Credit Note` nc
            LEFT JOIN `tabSales Invoice` si_orig ON si_orig.name = nc.return_against
            WHERE nc.company = %(company)s
                AND nc.docstatus = 1
                AND nc.bill_no IS NOT NULL AND nc.bill_no != ''
                AND nc.bill_control IS NOT NULL AND nc.bill_control != ''
                AND {nc_cond}
        )
    """


def _get_common_columns() -> str:
    """Columnas compartidas por ambos SELECTs (no varían entre legacy y nuevo)."""
    return """
            {transaction_type_placeholder}
            siv.is_void,
            siv.is_return,
            siv.branch,
            DATE_FORMAT(siv.posting_date, '%%d/%%m/%%Y') AS posting_date,
            tc.tax_id AS customer_tax_id,
            siv.customer_name,
            siv.bill_no,
            siv.bill_control,
            MAX(vdbs.serie) AS fiscal_series,
            siv.credit_note_no,
            siv.debit_note_no,
            siv.affected_invoice_number,  
            siv.vat_withholding_voucher_number,
            DATE_FORMAT(siv.withholding_date, '%%d/%%m/%%Y') AS withholding_date,
            CASE
                WHEN tc.type_of_person = 'Domiciled legal entity' THEN 'PJD'
                WHEN tc.type_of_person = 'Non-domiciled legal entity' THEN 'PJND'
                WHEN tc.type_of_person = 'Natural person domiciled' THEN 'PND'
                WHEN tc.type_of_person = 'Non-domiciled natural person' THEN 'PNND'
                ELSE 'N/A'
            END AS customer_type,
    """


def _get_common_joins() -> str:
    """JOINs compartidos por ambos SELECTs."""
    return """
        FROM
            InvoiceData siv
        LEFT JOIN
            `tabCustomer` tc ON tc.name = siv.customer
        LEFT JOIN
            `tabSales Taxes and Charges` tstac
            ON tstac.parent = siv.name
            AND tstac.parenttype IN ('Sales Invoice', 'VE Sales Credit Note')
        LEFT JOIN
            `tabVE Digital Billing Series` vdbs
            ON CAST(SUBSTRING_INDEX(siv.bill_control, '-', -1) AS UNSIGNED)
                BETWEEN vdbs.range_from AND vdbs.range_to
                AND vdbs.company = %(company)s
    """


def _get_legacy_calc_columns() -> str:
    """Columnas de cálculo LEGACY (facturas declaradas al SENIAT hasta el corte).

    Usa tax_amount * conversion_rate — sin filtro charge_type='VAT' en bases,
    sin base_net_total. Incluye (1-is_void) para anular montos en facturas void.
    """
    return """
            -- LEGACY: tax_amount * conversion_rate (montos declarados al SENIAT)
            -- (1 - is_void): anula montos para facturas anuladas (SENIAT: fila presente, montos en cero)
            -- MAX(siv.*): compatibilidad con ONLY_FULL_GROUP_BY (GROUP BY siv.name = PK, 1 fila por grupo)
            (
                MAX(siv.total_exempt)
                + COALESCE(SUM(CASE WHEN tstac.charge_type = 'VAT' THEN tstac.tax_amount * (100.0 / NULLIF(tstac.rate, 0)) ELSE 0 END), 0)
                + COALESCE(SUM(CASE WHEN tstac.charge_type = 'VAT' THEN tstac.tax_amount ELSE 0 END), 0)
            ) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS grand_total,
            MAX(siv.total_exempt) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS total_exempt,
            MAX(siv.base_amount_igtf) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_amount_igtf,
            MAX(siv.total_igtf) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS total_igtf,

            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(general_rate)s THEN tstac.tax_amount * (100.0 / %(general_rate)s) ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_general_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(general_rate)s THEN tstac.tax_amount ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_general_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(reduced_rate)s THEN tstac.tax_amount * (100.0 / %(reduced_rate)s) ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_reduced_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(reduced_rate)s THEN tstac.tax_amount ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_reduced_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(additional_rate)s THEN tstac.tax_amount * (100.0 / %(additional_rate)s) ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_additional_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(additional_rate)s THEN tstac.tax_amount ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_additional_non_taxpayer,

            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(general_rate)s THEN tstac.tax_amount * (100.0 / %(general_rate)s) ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_general_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(general_rate)s THEN tstac.tax_amount ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_general_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(reduced_rate)s THEN tstac.tax_amount * (100.0 / %(reduced_rate)s) ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_reduced_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(reduced_rate)s THEN tstac.tax_amount ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_reduced_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(additional_rate)s THEN tstac.tax_amount * (100.0 / %(additional_rate)s) ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_additional_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(additional_rate)s THEN tstac.tax_amount ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_additional_taxpayer,
            MAX(CASE WHEN tstac.charge_type = 'VAT Withholding' THEN ABS(tstac.tax_amount) ELSE 0 END) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_retained,
            MAX(CASE WHEN tstac.charge_type = 'VAT Withholding' THEN tstac.rate ELSE 0 END) * (1 - MAX(siv.is_void)) AS vat_withholding_rate,
            MAX(siv.posting_date) AS posting_date_sort,
            MAX(siv.withholding_date) AS withholding_date_sort
    """


def _get_new_calc_columns() -> str:
    """Columnas de cálculo NUEVO (facturas posteriores al corte fiscal).

    Usa base_net_total y base_tax_amount directamente (fuente de verdad VEF).
    Incluye (1-is_void) para anular montos en facturas void.
    Filtra charge_type='VAT' en bases por alícuota.
    """
    return """
            -- NUEVO: base_* almacenados (fuente de verdad VEF)
            -- MAX(siv.*): compatibilidad con ONLY_FULL_GROUP_BY (GROUP BY siv.name = PK, 1 fila por grupo)
            (
                MAX(siv.base_net_total)
                + COALESCE(SUM(CASE WHEN tstac.charge_type = 'VAT' THEN tstac.base_tax_amount ELSE 0 END), 0)
            ) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS grand_total,
            MAX(siv.total_exempt) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS total_exempt,
            MAX(siv.base_amount_igtf) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_amount_igtf,
            MAX(siv.total_igtf) * MAX(siv.conversion_rate) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS total_igtf,

            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(general_rate)s AND tstac.charge_type = 'VAT' THEN MAX(siv.base_net_total) - MAX(siv.total_exempt) * MAX(siv.conversion_rate) ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_general_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(general_rate)s AND tstac.charge_type = 'VAT' THEN tstac.base_tax_amount ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_general_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(reduced_rate)s AND tstac.charge_type = 'VAT' THEN MAX(siv.base_net_total) - MAX(siv.total_exempt) * MAX(siv.conversion_rate) ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_reduced_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(reduced_rate)s AND tstac.charge_type = 'VAT' THEN tstac.base_tax_amount ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_reduced_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(additional_rate)s AND tstac.charge_type = 'VAT' THEN MAX(siv.base_net_total) - MAX(siv.total_exempt) * MAX(siv.conversion_rate) ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_additional_non_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 0 AND tstac.rate = %(additional_rate)s AND tstac.charge_type = 'VAT' THEN tstac.base_tax_amount ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_additional_non_taxpayer,

            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(general_rate)s AND tstac.charge_type = 'VAT' THEN MAX(siv.base_net_total) - MAX(siv.total_exempt) * MAX(siv.conversion_rate) ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_general_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(general_rate)s AND tstac.charge_type = 'VAT' THEN tstac.base_tax_amount ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_general_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(reduced_rate)s AND tstac.charge_type = 'VAT' THEN MAX(siv.base_net_total) - MAX(siv.total_exempt) * MAX(siv.conversion_rate) ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_reduced_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(reduced_rate)s AND tstac.charge_type = 'VAT' THEN tstac.base_tax_amount ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_reduced_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(additional_rate)s AND tstac.charge_type = 'VAT' THEN MAX(siv.base_net_total) - MAX(siv.total_exempt) * MAX(siv.conversion_rate) ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS base_additional_taxpayer,
            SUM(CASE WHEN tc.is_special_taxpayer = 1 AND tstac.rate = %(additional_rate)s AND tstac.charge_type = 'VAT' THEN tstac.base_tax_amount ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_additional_taxpayer,
            MAX(CASE WHEN tstac.charge_type = 'VAT Withholding' THEN ABS(tstac.base_tax_amount) ELSE 0 END) * MAX(siv.amount_sign) * (1 - MAX(siv.is_void)) AS iva_retained,
            MAX(CASE WHEN tstac.charge_type = 'VAT Withholding' THEN tstac.rate ELSE 0 END) * (1 - MAX(siv.is_void)) AS vat_withholding_rate,
            MAX(siv.posting_date) AS posting_date_sort,
            MAX(siv.withholding_date) AS withholding_date_sort
    """


def get_query() -> str:
    """Query con UNION ALL: legacy (<= corte fiscal) y nuevo (> corte fiscal)."""
    cte = _get_cte()
    common_cols = _get_common_columns()
    legacy_cols = _get_legacy_calc_columns()
    new_cols = _get_new_calc_columns()
    joins = _get_common_joins()

    return f"""
    {cte}

    SELECT {common_cols} {legacy_cols}
    {joins}
    WHERE siv.posting_date <= %(fiscal_cutoff)s
    GROUP BY siv.name

    UNION ALL

    SELECT {common_cols} {new_cols}
    {joins}
    WHERE siv.posting_date > %(fiscal_cutoff)s
    GROUP BY siv.name
    """


def get_total_row(data: list[dict]) -> dict:
    """
    Calcula los totales para las columnas relevantes y devuelve un diccionario,
    incluyendo el desglose de IVA retenido por alícuota.
    """
    if not data:
        return {}

    iva_retained_general = 0
    iva_retained_reduced = 0
    iva_retained_additional = 0

    totals = frappe._dict({
        "grand_total": 0,
        "total_exempt": 0,
        "base_general_non_taxpayer": 0,
        "iva_general_non_taxpayer": 0,
        "base_reduced_non_taxpayer": 0,
        "iva_reduced_non_taxpayer": 0,
        "base_additional_non_taxpayer": 0,
        "iva_additional_non_taxpayer": 0,
        "base_general_taxpayer": 0,
        "iva_general_taxpayer": 0,
        "base_reduced_taxpayer": 0,
        "iva_reduced_taxpayer": 0,
        "base_additional_taxpayer": 0,
        "iva_additional_taxpayer": 0,
        "iva_retained": 0,
        "total_igtf": 0,
        "base_amount_igtf": 0,
    })

    for row in data:
        # Las facturas anuladas y las Notas de Crédito se muestran en el
        # libro con sus montos originales, pero NO se incluyen en los
        # totales del reporte (requisito fiscal SENIAT).
        if row.get("is_void") or row.get("is_return"):
            continue

        for key in totals.keys():
            totals[key] += row.get(key, 0)

        ret_monto = row.get("iva_retained", 0)

        if ret_monto > 0:

            bases = {
                "general": row.get("base_general_taxpayer", 0) + row.get("base_general_non_taxpayer", 0),
                "reduced": row.get("base_reduced_taxpayer", 0) + row.get("base_reduced_non_taxpayer", 0),
                "additional": row.get("base_additional_taxpayer", 0) + row.get("base_additional_non_taxpayer", 0),
            }

            # Distribución proporcional del monto retenido según el peso
            # de cada base imponible. Evita atribuir el 100% a la alícuota
            # dominante en facturas con múltiples tasas de IVA.
            total_base: float = bases["general"] + bases["reduced"] + bases["additional"]
            if total_base > 0:
                iva_retained_general += ret_monto * (bases["general"] / total_base)
                iva_retained_reduced += ret_monto * (bases["reduced"] / total_base)
                iva_retained_additional += ret_monto * (bases["additional"] / total_base)
            else:
                iva_retained_general += ret_monto

    totals["iva_retained_general"] = iva_retained_general
    totals["iva_retained_reduced"] = iva_retained_reduced
    totals["iva_retained_additional"] = iva_retained_additional

    totals.bill_no = _("TOTALES")
    return totals


def get_report_summary(totals: dict) -> list[dict]:
    """
    Returns the summary data for the top of the report.
    """
    summary = [
        {
            "value": totals.get("grand_total", 0),
            "label": "Total Ventas Incl. IVA",
            "datatype": "Currency",
            "indicator": "Green"
        },

        {
            "value": totals.get("total_exempt", 0),
            "label": "Ventas No Gravadas",
            "datatype": "Currency",
            "indicator": "Green"
        },

        {
            "value": totals.get("base_general_taxpayer", 0)
            + totals.get("base_general_non_taxpayer", 0),
            "label": "Base Imponible General",
            "datatype": "Currency",
            "indicator": "Green"
        },

        {
            "value": totals.get("iva_general_taxpayer", 0)
            + totals.get("iva_general_non_taxpayer", 0),
            "label": "Impuesto General",
            "datatype": "Currency",
            "indicator": "Blue"
        },

        {
            "value": totals.get("base_reduced_taxpayer", 0)
            + totals.get("base_reduced_non_taxpayer", 0),
            "label": "Base Imponible Reducida",
            "datatype": "Currency",
            "indicator": "Green"
        },

        {
            "value": totals.get("iva_reduced_taxpayer", 0)
            + totals.get("iva_reduced_non_taxpayer", 0),
            "label": "Impuesto Reducido",
            "datatype": "Currency",
            "indicator": "Blue"
        },

        {
            "value": totals.get("base_additional_taxpayer", 0)
            + totals.get("base_additional_non_taxpayer", 0),
            "label": "Base Imponible Adicional",
            "datatype": "Currency",
            "indicator": "Green"
        },

        {
            "value": totals.get("iva_additional_taxpayer", 0)
            + totals.get("iva_additional_non_taxpayer", 0),
            "label": "Impuesto Adicional",
            "datatype": "Currency",
            "indicator": "Blue"
        },

        {
            "value": (
                totals.get("iva_general_taxpayer", 0)
                + totals.get("iva_general_non_taxpayer", 0)
                + totals.get("iva_reduced_taxpayer", 0)
                + totals.get("iva_reduced_non_taxpayer", 0)
                + totals.get("iva_additional_taxpayer", 0)
                + totals.get("iva_additional_non_taxpayer", 0)
            ),
            "label": "Total IVA",
            "datatype": "Currency",
            "indicator": "Green"
        },

        {
            "value": totals.get("iva_retained", 0),
            "label": "IVA Retenido",
            "datatype": "Currency",
            "indicator": "Blue"
        },

        {
            "value": totals.get("base_amount_igtf", 0),
            "label": "Base IGTF",
            "datatype": "Currency",
            "indicator": "Green"
        },

        {
            "value": totals.get("total_igtf", 0),
            "label": "Monto IGTF",
            "datatype": "Currency",
            "indicator": "Blue"
        },

    ]

    return summary
