from erpnext.accounts import general_ledger


def process_gl_map(gl_map, merge_entries=True, precision=None, from_repost=False):
    if not gl_map:
        return []

    if gl_map[0].voucher_type != "Period Closing Voucher":
        gl_map = general_ledger.distribute_gl_based_on_cost_center_allocation(gl_map, precision, from_repost)

    # Desactivamos el merge de los asientos contables
    # if merge_entries:
    #     gl_map = general_ledger.merge_similar_entries(gl_map, precision)

    gl_map = general_ledger.toggle_debit_credit_if_negative(gl_map)

    return gl_map

general_ledger.process_gl_map = process_gl_map
