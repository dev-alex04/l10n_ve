import frappe


# Se importa para que se carguen en memoria los patch
try:
    import l10n_ve.l10n_ve.report.general_ledger.general_ledger

except ImportError:
    print(f"FAILURE!!!: Ocurrió cargando l10n_ve.l10n_ve.report.general_ledger.general_ledger. Revise el log de errores")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.l10n_ve.report.general_ledger.general_ledger')

try:
    import l10n_ve.l10n_ve.report.document.document
except ImportError:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.l10n_ve.report.document.document Revise el log de errores")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.l10n_ve.report.document.document')

try:
    import l10n_ve.l10n_ve.report.transaction_base.transaction_base
except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.l10n_ve.report.transaction_base.transaction_base. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.l10n_ve.report.transaction_base.transaction_base')

try:
    import l10n_ve.utils.utils
except ImportError as e:
    print(f"FAILURE!!!: Ocurrió cargando el parche l10n_ve.utils.utils. Error: {e}")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.l10n_ve.report.transaction_base.transaction_base')
