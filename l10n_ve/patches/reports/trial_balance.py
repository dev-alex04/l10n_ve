import erpnext.accounts.report.trial_balance.trial_balance as tb
from erpnext.accounts.utils import get_zero_cutoff
from frappe import _
from frappe.utils import flt

original_prepare_data = tb.prepare_data

VALUE_FIELDS = (
    "opening_debit",
    "opening_credit",
    "debit",
    "credit",
    "closing_debit",
    "closing_credit",
)


def hide_group_accounts(data):
    if hasattr(tb, "hide_group_accounts"):
        return tb.hide_group_accounts(data)
    non_group_accounts_data = []
    for d in data:
        if not d.get("is_group_account"):
            d.update(indent=0)
            non_group_accounts_data.append(d)
    return non_group_accounts_data


def custom_prepare_data(accounts, filters, parent_children_map, company_currency):
    """
    En la normativa contable venezolana (VEN-NIF / Balance de Comprobacion de Sumas y Saldos):
    - Las cuentas hijas (detalle) muestran sus saldos iniciales y finales netos.
    - Las cuentas de grupo y los totales generales NO deben netear Debe contra Haber
      (por ejemplo, la Depreciacion Acumulada o Devoluciones no deben restarse del
      Debe del grupo sino sumarse a la columna Haber correspondiente).
    """
    data = []

    value_fields = getattr(tb, "value_fields", VALUE_FIELDS)
    cutoff_func = getattr(tb, "get_zero_cutoff", get_zero_cutoff)

    for d in accounts:
        # En el estandar de ERPNext, la llamada a prepare_opening_closing(d) netea los grupos.
        # Al omitirla para grupos, preservamos las sumas independientes de Debe y Haber por columna.
        has_value = False
        row = {
            "account": d.name,
            "parent_account": d.parent_account,
            "indent": d.indent,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "currency": company_currency,
            "is_group_account": d.is_group,
            "account_name": (
                f"{d.account_number} - {d.account_name}" if d.account_number else d.account_name
            ),
        }

        for key in value_fields:
            row[key] = flt(d.get(key, 0.0))

            if abs(row[key]) >= cutoff_func(company_currency):
                has_value = True

        row["has_value"] = has_value
        data.append(row)

    total_row = tb.calculate_total_row(accounts, company_currency)

    if not filters.get("show_group_accounts"):
        data = hide_group_accounts(data)

    data.extend([{}, total_row])

    return data


tb.prepare_data = custom_prepare_data

