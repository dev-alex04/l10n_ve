import frappe

try:
    import l10n_ve.patches.reports.general_ledger

except ImportError:
    print(f"FAILURE!!!: Ocurrió cargando l10n_ve.patches.reports.general_ledger. Revise el log de errores")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.reports.general_ledger')

try:
    import l10n_ve.patches.model.document
except ImportError:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.model.document Revise el log de errores")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.model.document')

try:
    import l10n_ve.patches.utilities.transaction_base
except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.utilities.transaction_base. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.utilities.transaction_base')

try:
    import l10n_ve.patches.accounts.utils
except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.accounts.utils. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.accounts.utils')

try:
    import l10n_ve.patches.accounts.chart_of_accounts

except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.accounts.chart_of_accounts. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.accounts.chart_of_accounts')


try:
    import l10n_ve.patches.accounts.general_ledger

except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.accounts.general_ledger. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.accounts.general_ledger')


try:
    import l10n_ve.patches.setup.utils
except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.setup.utils. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.setup.utils')


try:
    import l10n_ve.patches.stock.utils
except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.stock.utils. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.stock.utils')


def apply_post_db_patches() -> None:
    try:
        import l10n_ve.patches.reports.accounts_receivable

    except ImportError as e:
        print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.patches.reports.accounts_receivable. Error: {e}")
        frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.patches.reports.accounts_receivable')
