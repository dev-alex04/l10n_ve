# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt
import frappe
from frappe import _
from frappe.utils import flt, getdate

import base64
import re

from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring


def execute(filters=None):
    """Punto de entrada principal para el Reporte de Libro de Compras."""
    filters = filters or {}

    if not filters.get("company"):
        frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))

    columns: list[dict] = get_columns()
    data: list[dict] = get_query_data(filters)
    totals: dict = get_totals_from_data(data)
    report_summary: list[dict] = get_report_summary(totals)

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
        {"fieldname": "fecha_entrega", "label": "Fecha de Entrega", "fieldtype": "Data", "width": "auto"},
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
    from_date, to_date = _get_date_range_from_filters(filters)
    filters["from_date"] = from_date
    filters["to_date"] = to_date

    from frappe.utils import add_months
    loose_from_date = add_months(from_date, -3)
    filters["loose_from_date"] = loose_from_date

    query: str = get_query(filters)

    company_currency: str = frappe.get_cached_value(
        "Company", filters.get("company"), "default_currency"
    )

    general_rate, reduced_rate, additional_rate = _get_tax_rates()

    values: dict = {
        "from_date": from_date,
        "to_date": to_date,
        "loose_from_date": loose_from_date,
        "company_currency": company_currency,
        "general_rate": general_rate,
        "reduced_rate": reduced_rate,
        "additional_rate": additional_rate,
    }

    if filters.get("company"):
        values["company"] = filters.get("company")

    if filters.get("branch"):
        values["branch"] = filters.get("branch")

    return frappe.db.sql(query, values, as_dict=True)


def get_query(filters: dict) -> str:
    """Construye la query SQL del Libro de Compras."""
    conditions: str = "AND tPI.docstatus = 1"
    conditions += " AND tPI.is_return = 0"
    conditions += " AND tPI.posting_date BETWEEN %(loose_from_date)s AND %(to_date)s"
    conditions += """ AND COALESCE(
        (SELECT wv.delivery_date 
         FROM `tabVAT Withholding Voucher Item` wvi
         INNER JOIN `tabVAT Withholding Voucher` wv 
            ON wvi.parent = wv.name AND wv.docstatus = 1
         WHERE wvi.purchase_invoice = tPI.name 
         LIMIT 1),
        tPI.posting_date
    ) BETWEEN %(from_date)s AND %(to_date)s"""

    if filters.get("company"):
        conditions += " AND tPI.company = %(company)s"

    # Filtro opcional de sucursal
    branch: str = filters.get("branch") or ""
    if branch:
        conditions += " AND tPI.branch = %(branch)s"

    query: str = """
        WITH InvoiceData AS (
            -- Facturas de compra (Purchase Invoice)
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

            UNION ALL

            -- Notas de crédito de compra (VE Purchase Credit Note)
            SELECT
                nc.name,
                nc.posting_date,
                nc.supplier,
                nc.supplier_name,
                1 AS is_return,
                nc.bill_no,
                nc.bill_control,
                nc.bill_no AS credit_note_no,
                NULL AS debit_note_no,
                nc.affected_invoice_number,
                nc.total_igtf,
                nc.bill_date,
                0 AS is_debit_note,
                nc.base_grand_total,
                nc.base_total,
                nc.total_exempt,
                (CASE WHEN nc.currency != %(company_currency)s
                    THEN nc.conversion_rate ELSE 1 END) AS conversion_rate
            FROM `tabVE Purchase Credit Note` AS nc
            WHERE nc.docstatus = 1
                AND nc.posting_date BETWEEN %(loose_from_date)s AND %(to_date)s
                AND COALESCE(
                    (SELECT wv.delivery_date 
                     FROM `tabVAT Withholding Voucher Item` wvi
                     INNER JOIN `tabVAT Withholding Voucher` wv 
                        ON wvi.parent = wv.name AND wv.docstatus = 1
                     WHERE wvi.purchase_invoice = nc.name 
                     LIMIT 1),
                    nc.posting_date
                ) BETWEEN %(from_date)s AND %(to_date)s
                {nc_company_condition}
                {nc_branch_condition}

            UNION ALL

            -- Notas de débito de compra (VE Purchase Debit Note)
            SELECT
                nd.name,
                nd.posting_date,
                nd.supplier,
                nd.supplier_name,
                0 AS is_return,
                nd.bill_no,
                nd.bill_control,
                NULL AS credit_note_no,
                nd.bill_no AS debit_note_no,
                nd.affected_invoice_number,
                nd.total_igtf,
                nd.bill_date,
                1 AS is_debit_note,
                nd.base_grand_total,
                nd.base_total,
                nd.total_exempt,
                (CASE WHEN nd.currency != %(company_currency)s
                    THEN nd.conversion_rate ELSE 1 END) AS conversion_rate
            FROM `tabVE Purchase Debit Note` AS nd
            WHERE nd.docstatus = 1
                AND nd.posting_date BETWEEN %(loose_from_date)s AND %(to_date)s
                AND COALESCE(
                    (SELECT wv.delivery_date 
                     FROM `tabVAT Withholding Voucher Item` wvi
                     INNER JOIN `tabVAT Withholding Voucher` wv 
                        ON wvi.parent = wv.name AND wv.docstatus = 1
                     WHERE wvi.purchase_invoice = nd.name 
                     LIMIT 1),
                    nd.posting_date
                ) BETWEEN %(from_date)s AND %(to_date)s
                {nd_company_condition}
                {nd_branch_condition}
        )
        SELECT
            inv.name AS nro_factura,
            inv.posting_date,
            supp.tax_id,
            inv.supplier_name,
            inv.is_return AS tipo,
            inv.bill_no,
            inv.bill_control,
            (inv.base_grand_total + ABS(COALESCE(
                (SELECT SUM(base_tax_amount) FROM `tabPurchase Taxes and Charges` 
                 WHERE parent = inv.name AND add_deduct_tax = 'Deduct'), 0))
            ) AS grand_total,
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
            COALESCE(islr_ref.islr_amount, 0) AS ret_islr_monto,
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
        -- Subquery: ISLR desde comprobantes de retención (monto + flag)
        LEFT JOIN (
            SELECT
                islr_item.purchase_invoice,
                1 AS has_islr,
                SUM(islr_item.islr_amount) AS islr_amount
            FROM `tabISLR Withholding Voucher Item` islr_item
            INNER JOIN `tabISLR Withholding Voucher` islr_v
                ON islr_item.parent = islr_v.name AND islr_v.docstatus = 1
            GROUP BY islr_item.purchase_invoice
        ) AS islr_ref ON islr_ref.purchase_invoice = inv.name

        GROUP BY inv.name
        ORDER BY inv.bill_date ASC
    """
    query = query.replace("{conditions}", conditions)

    # Condición de compañía para NCs (misma lógica que PIs)
    nc_company_condition: str = "AND nc.company = %(company)s" if filters.get("company") else ""
    query = query.replace("{nc_company_condition}", nc_company_condition)

    # Condición de compañía para NDs
    nd_company_condition: str = "AND nd.company = %(company)s" if filters.get("company") else ""
    query = query.replace("{nd_company_condition}", nd_company_condition)

    # Condición de sucursal para NCs y NDs
    nc_branch_condition: str = "AND nc.branch = %(branch)s" if branch else ""
    query = query.replace("{nc_branch_condition}", nc_branch_condition)
    nd_branch_condition: str = "AND nd.branch = %(branch)s" if branch else ""
    query = query.replace("{nd_branch_condition}", nd_branch_condition)

    return query


_SUMMABLE_FIELDS: list[str] = [
    "grand_total", "total_exempt", "base_reducida", "impuesto_reducida",
    "base_general", "impuesto_general", "base_adicional", "impuesto_adicional",
    "total_igtf",
]

_SUMMARY_LABELS: list[tuple[str, str]] = [
    ("grand_total", "Total Compras"),
    ("total_exempt", "Total Compras Sin Crédito"),
    ("base_reducida", "Total Base Reducida"),
    ("impuesto_reducida", "Total Impuesto Reducido"),
    ("base_general", "Total Base General"),
    ("impuesto_general", "Total Impuesto 16%"),
    ("base_adicional", "Total Base Adicional"),
    ("impuesto_adicional", "Total Impuesto 31%"),
    ("taxes_and_charges_deducted", "Total IVA Retenido"),
    ("iva_retenido_terceros", "IVA Retenido (a terceros)"),
    ("anticipo_iva_importacion", "Anticipo de IVA (Importación)"),
    ("total_igtf", "Total IGTF Pagado"),
]


def get_totals_from_data(data: list[dict]) -> dict:
    """Acumula totales de todas las filas del reporte."""
    totals: dict = {f: 0.0 for f in _SUMMABLE_FIELDS}
    totals.update({
        "taxes_and_charges_deducted": 0.0,
        "iva_retenido_terceros": 0.0,
        "anticipo_iva_importacion": 0.0,
        "retencion_general": 0.0,
        "retencion_adicional": 0.0,
        "retencion_reducida": 0.0,
    })

    for row in data:
        for field in _SUMMABLE_FIELDS:
            totals[field] += flt(row.get(field))

        # Retención IVA: solo si tiene comprobante asociado
        ret_monto: float = flt(row.get("taxes_and_charges_deducted"))
        if not row.get("nro_comprobante_retencion") or ret_monto == 0:
            continue

        totals["taxes_and_charges_deducted"] += ret_monto
        totals["iva_retenido_terceros"] += flt(row.get("iva_retenido_terceros"))
        totals["anticipo_iva_importacion"] += flt(row.get("anticipo_iva_importacion"))

        # Clasificar retención por la base imponible más alta
        bases: dict = {
            "general": flt(row.get("base_general")),
            "adicional": flt(row.get("base_adicional")),
            "reducida": flt(row.get("base_reducida")),
        }
        max_base: str = max(bases, key=bases.get)
        if bases[max_base] > 0:
            totals[f"retencion_{max_base}"] += ret_monto
        else:
            totals["retencion_general"] += ret_monto

    return totals


def get_report_summary(totals: dict) -> list[dict]:
    """Genera el resumen inferior del reporte a partir de los totales."""
    return [
        {"value": totals.get(field), "label": label, "datatype": "Currency"}
        for field, label in _SUMMARY_LABELS
    ]


def _get_date_range_from_filters(filters: dict) -> tuple[str, str]:
    """Extrae y valida el rango de fechas desde los filtros del reporte."""
    from_date: str | None = filters.get("from_date")
    to_date: str | None = filters.get("to_date")

    if not from_date or not to_date:
        frappe.throw(_("Por favor, seleccione un rango de fechas para generar el reporte."))

    if getdate(from_date) > getdate(to_date):
        frappe.throw(_("La Fecha Desde no puede ser posterior a la Fecha Hasta."))

    return from_date, to_date


#: Largo máximo que acepta el portal del SENIAT en cada campo de la declaración
#: de ISLR.
_XML_MAX_FACTURA_DIGITS = 10
_XML_MAX_CONTROL_DIGITS = 10


def _clean_xml_doc_number(val: str | None, max_digits: int) -> tuple[str | None, bool]:
    """Dígitos del número de un documento para la declaración XML de ISLR del SENIAT.

    El SENIAT solo acepta dígitos y tope de largo por campo. Los números llegan
    con serie (``MSO-01-0000028078``, ``B-9523``) o con relleno a la izquierda
    (``00-03367729``), así que se toma la porción a la derecha del último guion
    y se descartan los caracteres no numéricos.

    Si el número sobrepasa ``max_digits`` después de quitarle el relleno, se
    recortan los dígitos sobrantes por la izquierda para no omitir el registro
    y se marca ``was_truncated = True`` para notificar como advertencia.
    """
    if not val:
        return None, False

    val_str: str = str(val).strip()
    num_part: str = val_str.rsplit("-", 1)[-1] if "-" in val_str else val_str
    digits: str = re.sub(r"\D", "", num_part)
    if not digits:
        # La porción tras el guion no traía dígitos (p. ej. "0001234-A"):
        # se reintenta sobre el valor completo.
        digits = re.sub(r"\D", "", val_str)
    if not digits:
        return None, False

    was_truncated: bool = False
    if len(digits) > max_digits:
        digits_no_zero = digits.lstrip("0")
        if digits_no_zero and len(digits_no_zero) <= max_digits:
            digits = digits_no_zero
        else:
            # Recortar dígitos sobrantes por la izquierda para no omitir la retención
            digits = (digits_no_zero if digits_no_zero else digits)[-max_digits:]
            was_truncated = True

    return digits, was_truncated


def _clean_xml_rif(val: str | None) -> str | None:
    """RIF para el XML de ISLR: letra y dígitos en mayúsculas, sin separadores.

    ``J-30909786-5`` queda como ``J309097865``. Devuelve ``None`` si no queda
    nada declarable, para que el llamador reporte la fila en lugar de mandar un
    RIF de relleno que el portal aceptaría como válido.
    """
    if not val:
        return None
    cleaned: str = re.sub(r"[^A-Za-z0-9]", "", str(val)).upper()
    return cleaned or None


@frappe.whitelist()
def generate_xml_islr_file(filters: dict | str | None = None) -> dict | None:
    """
    Genera un XML de retenciones ISLR para el SENIAT basado en ISLR Withholding Voucher.

    Lee directamente desde ISLR Withholding Voucher Item (fuente de verdad),
    eliminando la dependencia legacy de Payment Entry Reference.

    Returns:
        dict con filename y filecontent (base64) para descarga, o None si no hay datos.
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

        company_doc = frappe.get_cached_doc("Company", filters.get("company"))
        company_rif: str = (company_doc.tax_id or "").replace('-', '')
        if not company_rif:
            frappe.throw(_("El RIF de la compañía es obligatorio para generar el XML de ISLR."))

        periodo: str = getdate(from_date).strftime("%Y%m")

        retentions: list[dict] = frappe.db.sql("""
            SELECT
                REPLACE(supp.tax_id, '-', '') AS supplier_rif,
                item.doc_no AS bill_no,
                item.bill_control,
                voucher.posting_date AS fecha_operacion,
                item.code AS codigo_concepto,
                item.rate AS porcentaje_retencion,
                item.islr_base_amount AS monto_operacion,
                supp.type_of_person,
                voucher.name AS voucher_name
            FROM `tabISLR Withholding Voucher Item` AS item
            INNER JOIN `tabISLR Withholding Voucher` AS voucher
                ON item.parent = voucher.name AND voucher.docstatus = 1
            INNER JOIN `tabSupplier` AS supp
                ON voucher.supplier = supp.name
            WHERE
                voucher.empresa = %(company)s
                AND voucher.posting_date BETWEEN %(from_date)s AND %(to_date)s
        """, filters, as_dict=True)

        if not retentions:
            frappe.msgprint(_("No se encontraron retenciones de ISLR para los filtros seleccionados."))
            return None

        root = Element("RelacionRetencionesISLR", {"RifAgente": company_rif, "Periodo": periodo})
        processing_errors: list[str] = []

        for ret in retentions:
            if not ret.codigo_concepto or ret.porcentaje_retencion is None:
                error_msg: str = _("Falta código de concepto o alícuota para la factura '{0}'"
                    " (tipo persona: '{1}').").format(ret.bill_no or 'N/A', ret.type_of_person or 'N/A')

                if error_msg not in processing_errors:
                    processing_errors.append(error_msg)
                continue

            rif_retenido: str | None = _clean_xml_rif(ret.supplier_rif)
            numero_factura, factura_truncated = _clean_xml_doc_number(ret.bill_no, _XML_MAX_FACTURA_DIGITS)
            numero_control, control_truncated = _clean_xml_doc_number(ret.bill_control, _XML_MAX_CONTROL_DIGITS)

            if not rif_retenido or not numero_factura or not numero_control:
                invalid_fields: list[str] = [
                    _("{0} '{1}'").format(label, raw or "")
                    for label, raw, value in (
                        (_("RIF"), ret.supplier_rif, rif_retenido),
                        (_("Nro. de Factura"), ret.bill_no, numero_factura),
                        (_("Nro. de Control"), ret.bill_control, numero_control),
                    )
                    if value is None
                ]
                error_msg = _("Retención '{0}' omitida: {1} no contiene dígitos válidos.").format(
                    ret.voucher_name or ret.bill_no or 'N/A', "; ".join(invalid_fields))

                if error_msg not in processing_errors:
                    processing_errors.append(error_msg)
                continue

            if factura_truncated:
                warning_msg = _("Retención '{0}': Nro. de Factura '{1}' excedía {2} dígitos y fue recortado a '{3}'.").format(
                    ret.voucher_name or ret.bill_no or 'N/A', ret.bill_no, _XML_MAX_FACTURA_DIGITS, numero_factura)
                if warning_msg not in processing_errors:
                    processing_errors.append(warning_msg)

            if control_truncated:
                warning_msg = _("Retención '{0}': Nro. de Control '{1}' excedía {2} dígitos y fue recortado a '{3}'.").format(
                    ret.voucher_name or ret.bill_no or 'N/A', ret.bill_control, _XML_MAX_CONTROL_DIGITS, numero_control)
                if warning_msg not in processing_errors:
                    processing_errors.append(warning_msg)

            detalle = SubElement(root, "DetalleRetencion")
            SubElement(detalle, "RifRetenido").text = rif_retenido
            SubElement(detalle, "NumeroFactura").text = numero_factura
            SubElement(detalle, "NumeroControl").text = numero_control
            SubElement(detalle, "FechaOperacion").text = getdate(ret.fecha_operacion).strftime("%d/%m/%Y")
            SubElement(detalle, "CodigoConcepto").text = ret.codigo_concepto
            SubElement(detalle, "MontoOperacion").text = f"{flt(ret.monto_operacion):.2f}"
            SubElement(detalle, "PorcentajeRetencion").text = f"{flt(ret.porcentaje_retencion)}"

        if processing_errors:
            frappe.msgprint(_("Observaciones al procesar las retenciones (se incluyeron recortadas):<br>")
                            + "<br>".join(processing_errors),
                            title=_("Advertencias de Procesamiento"),
                            indicator="orange")

        rough_string: bytes = tostring(root, "utf-8")
        reparsed = minidom.parseString(rough_string)
        pretty_xml: str = reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode()

        encoded_content: str = base64.b64encode(pretty_xml.encode('utf-8')).decode('utf-8')

        return {
            "type": "download",
            "filename": f"ISLR_Retenciones_XML-{company_doc.abbr}-{periodo}.xml",
            "filecontent": encoded_content,
        }

    except frappe.ValidationError:
        raise
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en generate_xml_islr_file")
        frappe.throw(_("Ocurrió un error al generar el archivo XML de ISLR: {0}").format(e))

@frappe.whitelist()
def generate_txt_file(filters: dict | str) -> dict:
    """Genera archivo TXT de retenciones IVA para el SENIAT (Libro de Compras)."""

    try:
        if isinstance(filters, str):
            filters = frappe.parse_json(filters)

        from_date: str
        to_date: str
        from_date, to_date = _get_date_range_from_filters(filters)
        filters["from_date"] = from_date
        filters["to_date"] = to_date

        company_doc = frappe.get_cached_doc("Company", filters.get("company"))
        company_rif: str = (company_doc.tax_id or "").replace('-', '')

        if not company_rif:
            frappe.throw(_("El RIF de la compañía no está configurado."))

        periodo = getdate(from_date).strftime('%Y%m')
        data: list[dict] = get_query_data(filters)
        invoices_with_voucher: list[dict] = [row for row in data if row.get("nro_comprobante_retencion")]

        if not invoices_with_voucher:
            # Si no hay facturas con comprobante, crea una línea con valores por defecto
            line_data = [
                company_rif,
                periodo,
            ] + ["0"] * 14

            content = "\t".join(line_data) + "\n"
            encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        else:

            content_lines = []
            for row in invoices_with_voucher:

                # Determinar alícuota IVA aplicada a la factura
                tax_rate: str = "0"  # Exento o sin base imponible
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

                # Calcular MontoDocumento = Base + IVA_completo + Exento
                # (SENIAT requiere el total ANTES de retenciones;
                #  base_grand_total de ERPNext ya tiene la retención IVA descontada)
                taxable_base: float = abs(flt(row.get('taxable_base') or 0))
                total_exempt: float = abs(flt(row.get('total_exempt') or 0))
                # Sumar IVA desglosado por alícuota (multi-alícuota safe)
                iva_full: float = (
                    abs(flt(row.get("impuesto_general") or 0))
                    + abs(flt(row.get("impuesto_reducida") or 0))
                    + abs(flt(row.get("impuesto_adicional") or 0))
                )
                monto_documento: float = taxable_base + iva_full + total_exempt

                line_data = [
                    str(company_rif),
                    str(periodo),
                    getdate(row.get("posting_date")).strftime("%Y-%m-%d") if row.get("posting_date") else "",
                    "C",
                    transaction_code,
                    (row.get("tax_id") or "0").replace('-', ''),
                    document_number,
                    row.get("bill_control") or "0",
                    f"{monto_documento:.2f}",
                    f"{taxable_base:.2f}",
                    f"{abs(flt(row.get('taxes_and_charges_deducted') or 0)):.2f}",
                    row.get("affected_invoice_number") or "0",
                    row.get("nro_comprobante_retencion") or "0",
                    f"{total_exempt:.2f}",
                    f"{abs(flt(tax_rate)):.2f}",
                    "0",  # Campo 16: IVA percibido (no aplica en compras, reservado)
                ]
                content_lines.append("\t".join(line_data))

            content = "\n".join(content_lines) + "\n"
            encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        return {
            "type": "download",
            "filename": f"IVA_Compras_TXT-{company_doc.abbr}-{periodo}.txt",
            "filecontent": encoded_content
        }

    except frappe.ValidationError:
        raise
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en generate_txt_file")
        frappe.throw(_("Ocurrió un error al generar el archivo TXT: {0}").format(e))
