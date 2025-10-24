import copy
from typing import Literal
from collections import OrderedDict

import frappe
from frappe import _, _dict

import erpnext.accounts.report.general_ledger.general_ledger as general_ledger_report
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency


original_execute = general_ledger_report.execute


def custom_execute(filters=None) -> tuple:

    if not filters:
        return [], []

    columns, res = original_execute(filters)

    for i, column in enumerate(columns):

        # Se elimina la clave del ancho para que el ancho sea
        if 'width' in column:
            del column['width']

        set_bill_numbers_on_columns(i, column, columns)

    return columns, res


def set_bill_numbers_on_columns(i: int, column: dict, columns: list[dict]) -> None:

    if column['fieldname'] != 'voucher_subtype':
        return

    columns.insert(i + 1,
        {
            "label": _("Bill control"),
            "fieldname": "bill_control",
            "fieldtype": "Data",
        },
    )

    columns.insert(i + 1,
        {
            "label": _("Bill no"),
            "fieldname": "bill_no",
            "fieldtype": "Data",
        },
    )


def initialize_gle_map(gl_entries, filters, totals_dict) -> OrderedDict:

    gle_map = OrderedDict()
    group_by = group_by_field(filters.get("group_by"))

    for gle in gl_entries:

        # Se agrega la traducción
        gle.against = _(gle.get('against'), '')
        gle.voucher_no = _(gle.get('voucher_no'), '')
        gle.party_type = _(gle.get('party_type'), '')
        gle.voucher_type = _(gle.get('voucher_type'), '')
        gle.voucher_subtype = _(gle.get('voucher_subtype'), '')
        gle.against_voucher_type = _(gle.get('against_voucher_type'), '')

        gle_map.setdefault(gle.get(group_by), _dict(totals=copy.deepcopy(totals_dict), entries=[]))
    return gle_map


def group_by_field(group_by) -> Literal['party'] | Literal['account'] | Literal['voucher_no']:

    if group_by == "Group by Party":
        return "party"
    elif group_by in ["Group by Voucher (Consolidated)", "Group by Account"]:
        return "account"
    else:
        return "voucher_no"


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
    inv_details = get_supplier_invoice_details()
    for gl in gl_entries:
        gl["bill_no"] = inv_details.get(gl.get("against_voucher"), "")



# 4. Reemplaza la función original con la tuya
general_ledger_report.execute = custom_execute
general_ledger_report.group_by_field = group_by_field
general_ledger_report.get_gl_entries = custom_get_gl_entries
general_ledger_report.initialize_gle_map = initialize_gle_map
general_ledger_report.set_bill_no = custom_set_bill_no
