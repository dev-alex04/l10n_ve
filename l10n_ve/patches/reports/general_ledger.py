import copy
from typing import Literal
from collections import OrderedDict

import frappe
from frappe import _, _dict

import erpnext.accounts.report.general_ledger.general_ledger as general_ledger_report
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency


original_execute = general_ledger_report.execute

# Comprobantes que el filtro "Solo facturas con N° de control y factura"
# evalúa. El resto (Payment Entry, Journal Entry…) nunca se toca.
INVOICE_VOUCHER_TYPES = frozenset({
    "Sales Invoice",
    "Purchase Invoice",
    "VE Sales Credit Note",
    "VE Sales Debit Note",
    "VE Purchase Credit Note",
    "VE Purchase Debit Note",
})

def custom_execute(filters=None) -> tuple:

    if not filters:
        return [], []

    columns, res = original_execute(filters)

    for i, column in enumerate(columns):

        # Se elimina la clave del ancho para que el ancho sea automático
        if 'width' in column:
            del column['width']

        # Renombramos la columna Remarks (Observaciones) a Descripción
        if column.get('fieldname') == 'remarks':
            column['label'] = _("Descripción")

        # Solo renombramos la etiqueta de voucher_type; el frontend JS
        # (general_ledger.js) se encarga de traducir los valores sin romper
        # los enlaces (Link). Mantener el tipo original preserva la navegación.
        if column.get('fieldname') == 'voucher_type':
            column['label'] = _("Tipo de Comprobante")

        set_bill_numbers_on_columns(i, column, columns)

    set_branch_on_entries(res)

    # NO traducir voucher_type en las filas: Frappe usa su valor para resolver el
    # DocType destino del Link voucher_no. La traducción del texto visible la hace
    # el frontend (general_ledger.js) sin romper la navegación.
    return columns, res


def set_bill_numbers_on_columns(i: int, column: dict, columns: list[dict]) -> None:

    if column['fieldname'] != 'voucher_subtype':
        return

    columns.insert(i + 1,
        {
            "label": _("Sucursal"),
            "fieldname": "branch",
            "fieldtype": "Link",
            "options": "VE Branch",
        },
    )

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


def set_branch_on_entries(res: list) -> None:
    if not res:
        return

    vouchers_by_type = {}
    for row in res:
        if not isinstance(row, dict):
            continue
        vt = row.get("voucher_type")
        vn = row.get("voucher_no")
        if vt and vn:
            vouchers_by_type.setdefault(vt, set()).add(vn)

    branch_map = {}
    for vt, names in vouchers_by_type.items():
        try:
            if not frappe.get_meta(vt).has_field("branch"):
                continue
            names_list = list(names)
            for chunk_start in range(0, len(names_list), 500):
                chunk = names_list[chunk_start:chunk_start + 500]
                docs = frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=["name", "branch"])
                for d in docs:
                    branch_map[(vt, d.name)] = d.get("branch") or ""
        except Exception:
            pass

    for row in res:
        if not isinstance(row, dict):
            continue
        vt = row.get("voucher_type")
        vn = row.get("voucher_no")
        if (vt, vn) in branch_map:
            row["branch"] = branch_map[(vt, vn)]
        else:
            row["branch"] = ""


def initialize_gle_map(gl_entries, filters, totals_dict) -> OrderedDict:

    gle_map = OrderedDict()
    group_by = group_by_field(filters.get("categorize_by") or filters.get("group_by"))

    for gle in gl_entries:

        # Se agrega la traducción (evitando traducir claves de DocType y registros para no romper el ruteo de enlaces)
        gle.against = gle.get('against') or ''
        gle.voucher_no = gle.get('voucher_no') or ''
        gle.party_type = gle.get('party_type') or ''
        gle.voucher_type = gle.get('voucher_type') or ''
        gle.voucher_subtype = _(gle.get('voucher_subtype'), '')
        gle.against_voucher_type = gle.get('against_voucher_type') or ''

        gle_map.setdefault(gle.get(group_by), _dict(totals=copy.deepcopy(totals_dict), entries=[]))
    return gle_map


def group_by_field(group_by) -> Literal['party'] | Literal['account'] | Literal['voucher_no']:

    if group_by in ("Categorize by Party", "Group by Party"):
        return "party"
    elif group_by in ("Categorize by Voucher (Consolidated)", "Categorize by Account",
                      "Group by Voucher (Consolidated)", "Group by Account"):
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

    categorize_by = filters.get("categorize_by") or filters.get("group_by", "")

    if categorize_by in ("Categorize by Voucher", "Group by Voucher"):
        order_by_statement = "order by posting_date, voucher_type, voucher_no"
    if categorize_by in ("Categorize by Account", "Group by Account"):
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

    if filters.get("ve_branch"):
        selected_branch = filters.get("ve_branch")
        vouchers_by_type = {}
        for row in gl_entries:
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            if vt and vn:
                vouchers_by_type.setdefault(vt, set()).add(vn)
        
        branch_map = {}
        for vt, names in vouchers_by_type.items():
            try:
                if not frappe.get_meta(vt).has_field("branch"):
                    continue
                names_list = list(names)
                for chunk_start in range(0, len(names_list), 500):
                    chunk = names_list[chunk_start:chunk_start + 500]
                    docs = frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=["name", "branch"])
                    for d in docs:
                        branch_map[(vt, d.name)] = d.get("branch") or ""
            except Exception:
                pass
        
        filtered_entries = []
        for row in gl_entries:
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            if branch_map.get((vt, vn)) == selected_branch:
                filtered_entries.append(row)
        gl_entries = filtered_entries

    if filters.get("only_invoices_with_bill_no_control"):
        cstr = frappe.utils.cstr

        # 1. Identificar comprobantes que requieren búsqueda en el documento cabecera
        missing_by_type = {}
        for entry in gl_entries:
            vt = entry.get("voucher_type")
            vn = entry.get("voucher_no")
            if vt in INVOICE_VOUCHER_TYPES and vn:
                bno = str(entry.get("bill_no") or "").strip()
                bctrl = str(entry.get("bill_control") or "").strip()
                if not bno or not bctrl:
                    missing_by_type.setdefault(vt, set()).add(vn)

        doc_map = {}
        unresolved_types = set()
        for vt, names in missing_by_type.items():
            try:
                meta = frappe.get_meta(vt)
                fields = ["name"]
                if meta.has_field("bill_no"):
                    fields.append("bill_no")
                if meta.has_field("bill_control"):
                    fields.append("bill_control")

                names_list = list(names)
                for chunk_start in range(0, len(names_list), 500):
                    chunk = names_list[chunk_start:chunk_start + 500]
                    docs = frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=fields)
                    for d in docs:
                        doc_map[(vt, d.name)] = (d.get("bill_no") or "", d.get("bill_control") or "")
            except Exception as e:
                # Falla abierto: no se ocultan registros si ocurre una excepción de BD/Metadata
                frappe.log_error(f"general_ledger: no se pudo resolver bill_no/bill_control de {vt}: {e}")
                unresolved_types.add(vt)

        # 2. Rellenar campos bill_no y bill_control en las entradas que los tenían vacíos
        for entry in gl_entries:
            vt = entry.get("voucher_type")
            vn = entry.get("voucher_no")
            if vt in INVOICE_VOUCHER_TYPES and (vt, vn) in doc_map:
                doc_bno, doc_bctrl = doc_map[(vt, vn)]
                if not entry.get("bill_no") and doc_bno:
                    entry["bill_no"] = doc_bno
                if not entry.get("bill_control") and doc_bctrl:
                    entry["bill_control"] = doc_bctrl

        # 3. Evaluar comprobantes COMPLETOS a excluir.
        # NUNCA excluir entradas de apertura (is_opening=='Yes') ni anteriores a from_date (preserva Apertura y Partida Doble)
        from_date = frappe.utils.getdate(filters.get("from_date")) if filters.get("from_date") else None

        incomplete_vouchers = set()
        for entry in gl_entries:
            vt = entry.get("voucher_type")
            vn = entry.get("voucher_no")
            is_opening = cstr(entry.get("is_opening")) == "Yes"
            posting_date = frappe.utils.getdate(entry.get("posting_date")) if entry.get("posting_date") else None

            # Entradas de Apertura o anteriores a from_date NUNCA se marcan para descarte
            if is_opening or (from_date and posting_date and posting_date < from_date):
                continue

            if vt in INVOICE_VOUCHER_TYPES and vt not in unresolved_types:
                bno = str(entry.get("bill_no") or "").strip()
                bctrl = str(entry.get("bill_control") or "").strip()
                if not bno or not bctrl:
                    incomplete_vouchers.add((vt, vn))

        # 4. Filtrar por COMPROBANTE COMPLETO (Todas las líneas del comprobante o ninguna)
        filtered_entries = []
        for entry in gl_entries:
            vt = entry.get("voucher_type")
            vn = entry.get("voucher_no")
            if (vt, vn) in incomplete_vouchers:
                continue
            filtered_entries.append(entry)

        gl_entries = filtered_entries

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


def custom_get_accountwise_gle(filters, accounting_dimensions, gl_entries, gle_map, totals):
    entries = []
    consolidated_gle = OrderedDict()
    group_by = group_by_field(filters.get("categorize_by") or filters.get("group_by"))
    group_by_voucher_consolidated = (filters.get("categorize_by") or filters.get("group_by")) == "Categorize by Voucher (Consolidated)"

    if filters.get("show_net_values_in_party_account"):
        account_type_map = general_ledger_report.get_account_type_map(filters.get("company"))

    immutable_ledger = frappe.db.get_single_value("Accounts Settings", "enable_immutable_ledger")
    cstr = frappe.utils.cstr

    def update_value_in_dict(data, key, gle, show_net_values=False):
        data[key].debit += gle.debit
        data[key].credit += gle.credit

        data[key].debit_in_account_currency += gle.debit_in_account_currency
        data[key].credit_in_account_currency += gle.credit_in_account_currency

        if filters.get("add_values_in_transaction_currency") and key not in ["opening", "closing", "total"]:
            data[key].debit_in_transaction_currency += gle.debit_in_transaction_currency
            data[key].credit_in_transaction_currency += gle.credit_in_transaction_currency

        if (
            filters.get("show_net_values_in_party_account")
            and account_type_map.get(data[key].account)
            in (
                "Receivable",
                "Payable",
            )
        ) or show_net_values:
            net_value = data[key].debit - data[key].credit
            net_value_in_account_currency = (
                data[key].debit_in_account_currency - data[key].credit_in_account_currency
            )

            if net_value < 0:
                dr_or_cr = "credit"
                rev_dr_or_cr = "debit"
            else:
                dr_or_cr = "debit"
                rev_dr_or_cr = "credit"

            data[key][dr_or_cr] = abs(net_value)
            data[key][dr_or_cr + "_in_account_currency"] = abs(net_value_in_account_currency)
            data[key][rev_dr_or_cr] = 0
            data[key][rev_dr_or_cr + "_in_account_currency"] = 0

        if data[key].against_voucher and gle.against_voucher:
            data[key].against_voucher += ", " + gle.against_voucher

    from_date, to_date = frappe.utils.getdate(filters.get("from_date")), frappe.utils.getdate(filters.get("to_date"))
    show_opening_entries = filters.get("show_opening_entries")

    for gle in gl_entries:
        group_by_value = gle.get(group_by)

        if gle.posting_date < from_date or (cstr(gle.is_opening) == "Yes" and not show_opening_entries):
            if not group_by_voucher_consolidated:
                update_value_in_dict(gle_map[group_by_value].totals, "opening", gle, True)
                update_value_in_dict(gle_map[group_by_value].totals, "closing", gle, True)

            update_value_in_dict(totals, "opening", gle, True)
            update_value_in_dict(totals, "closing", gle, True)

        elif gle.posting_date <= to_date or (cstr(gle.is_opening) == "Yes" and show_opening_entries):
            if not group_by_voucher_consolidated:
                update_value_in_dict(gle_map[group_by_value].totals, "total", gle)
                update_value_in_dict(gle_map[group_by_value].totals, "closing", gle)
                update_value_in_dict(totals, "total", gle)
                update_value_in_dict(totals, "closing", gle)

                gle_map[group_by_value].entries.append(gle)

            elif group_by_voucher_consolidated:
                keylist = [
                    gle.get("posting_date"),
                    gle.get("voucher_type"),
                    gle.get("voucher_no"),
                    gle.get("account"),
                    gle.get("party_type"),
                    gle.get("party"),
                    gle.get("gl_entry"), # Evita la consolidación de movimientos separados de la misma cuenta
                ]

                if immutable_ledger:
                    keylist.append(gle.get("creation"))

                if filters.get("include_dimensions"):
                    for dim in accounting_dimensions:
                        keylist.append(gle.get(dim))
                    keylist.append(gle.get("cost_center"))
                    keylist.append(gle.get("project"))

                key = tuple(keylist)
                if key not in consolidated_gle:
                    consolidated_gle[key] = copy.copy(gle)
                else:
                    update_value_in_dict(consolidated_gle, key, gle)

        if filters.get("include_dimensions"):
            dimensions = [*accounting_dimensions, "cost_center", "project"]

            for dimension in dimensions:
                if val := gle.get(dimension):
                    gle[dimension] = _(val)

    for value in consolidated_gle.values():
        update_value_in_dict(totals, "total", value)
        update_value_in_dict(totals, "closing", value)
        entries.append(value)

    return totals, entries


general_ledger_report.execute = custom_execute
general_ledger_report.group_by_field = group_by_field
general_ledger_report.get_gl_entries = custom_get_gl_entries
general_ledger_report.initialize_gle_map = initialize_gle_map
general_ledger_report.set_bill_no = custom_set_bill_no
general_ledger_report.get_accountwise_gle = custom_get_accountwise_gle

