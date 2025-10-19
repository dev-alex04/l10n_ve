import copy
from typing import Literal
from collections import OrderedDict

from frappe import _, _dict
import erpnext.accounts.report.general_ledger.general_ledger as general_ledger_report


original_execute = general_ledger_report.execute
original_group_by_field = general_ledger_report.group_by_field
original_initialize_gle_map = general_ledger_report.initialize_gle_map


def custom_execute(filters=None) -> tuple:

    if not filters:
        return [], []

    columns, res = original_execute(filters)

    for column in columns:

        # Se limina la clave del ancho para que el ancho sea
        if 'width' in column:
            del column['width']

    return columns, res


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

# 4. Reemplaza la función original con la tuya
general_ledger_report.execute = custom_execute
general_ledger_report.group_by_field = group_by_field
general_ledger_report.initialize_gle_map = initialize_gle_map
