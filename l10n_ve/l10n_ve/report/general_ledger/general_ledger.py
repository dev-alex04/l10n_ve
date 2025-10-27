import copy
from collections import OrderedDict

import frappe
from frappe import _, _dict

import erpnext.accounts.report.general_ledger.general_ledger as general_ledger_report
from erpnext.accounts.report.general_ledger.general_ledger import (
	group_by_field as original_group_by_field,
)
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency


original_execute = general_ledger_report.execute


def custom_execute(filters=None) -> tuple:

    if not filters:
        return [], []

    columns, res = original_execute(filters)

    # Eliminar anchos fijos para que sean automáticos
    for col in columns:
        if 'width' in col:
            del col['width']

    # Insertar columnas personalizadas en la posición correcta
    set_bill_numbers_on_columns(columns)

    return columns, res


def set_bill_numbers_on_columns(columns: list[dict]) -> None:
    """Inserta las columnas 'bill_no' y 'bill_control' después de 'voucher_subtype'."""
    try:
        # Encontrar el índice de la columna 'voucher_subtype'
        insertion_point = next(i for i, col in enumerate(columns) if col.get("fieldname") == "voucher_subtype")

        # Insertar las nuevas columnas en la posición encontrada
        columns.insert(insertion_point + 1, {
            "label": _("Bill Control"),
            "fieldname": "bill_control",
            "fieldtype": "Data",
        })
        columns.insert(insertion_point + 2, {
            "label": _("Bill No"),
            "fieldname": "bill_no",
            "fieldtype": "Data",
        })
    except StopIteration:
        # Si no se encuentra 'voucher_subtype', no se hace nada.
        return

def initialize_gle_map(gl_entries, filters, totals_dict) -> OrderedDict:
    """Inicializa el mapa de asientos contables sin traducciones innecesarias."""
    gle_map = OrderedDict()
    group_by = original_group_by_field(filters.get("group_by"))

    for gle in gl_entries:
        gle_map.setdefault(gle.get(group_by), _dict(totals=copy.deepcopy(totals_dict), entries=[]))

    return gle_map

def custom_get_gl_entries(filters, accounting_dimensions):
    currency_map = get_currency(filters)
    select_fields = """, debit, credit, debit_in_account_currency,
        credit_in_account_currency """

    if filters.get("show_remarks"):
        if remarks_length := frappe.db.get_single_value("Accounts Settings",
                                                        "general_ledger_remarks_length"):

            select_fields += f",substr(remarks, 1, {remarks_length}) as 'remarks'"
        else:
            select_fields += """,remarks"""

    order_by_statement = "order by posting_date, account, creation"

    if filters.get("include_dimensions"):
        order_by_statement = "order by posting_date, creation"

    if filters.get("group_by") == "Group by Voucher":
        order_by_statement = "order by posting_date, voucher_type, voucher_no"
    if filters.get("group_by") == "Group by Account":
        order_by_statement = "order by account, posting_date, creation"

    if filters.get("include_default_book_entries"):
        filters["company_fb"] = frappe.get_cached_value(
            "Company", filters.get("company"), "default_finance_book")

    dimension_fields = ""
    if accounting_dimensions:
        dimension_fields = ", ".join(accounting_dimensions) + ","

    transaction_currency_fields = ""
    if filters.get("add_values_in_transaction_currency"):
        transaction_currency_fields = (
            "debit_in_transaction_currency, credit_in_transaction_currency, transaction_currency,"
        )

    gl_entries = frappe.db.sql(
        f"""
        select
            bill_control, bill_no,
            name as gl_entry, posting_date, account, party_type, party,
            voucher_type, voucher_subtype, voucher_no, {dimension_fields}
            cost_center, project, {transaction_currency_fields}
            against_voucher_type, against_voucher, account_currency,
            against, is_opening, creation {select_fields}
        from `tabGL Entry`
        where company=%(company)s {general_ledger_report.get_conditions(filters)}
        {order_by_statement}
    """,
        filters,
        as_dict=1,
    )

    if filters.get("presentation_currency"):
        return convert_to_presentation_currency(gl_entries, currency_map)
    else:
        return gl_entries


def custom_set_bill_no(gl_entries):
    """
    Obtenemos el bill_no en las facturas de compra y venta
    Por lo tanto descativamos esta funcion
    """
    return
    inv_details = general_ledger_report.get_supplier_invoice_details()
    for gl in gl_entries:
        gl["bill_no"] = inv_details.get(gl.get("against_voucher"), "")


# 4. Reemplaza la función original con la tuya
general_ledger_report.execute = custom_execute
general_ledger_report.get_gl_entries = custom_get_gl_entries
general_ledger_report.initialize_gle_map = initialize_gle_map
general_ledger_report.set_bill_no = custom_set_bill_no
