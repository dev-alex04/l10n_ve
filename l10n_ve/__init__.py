__version__ = "v2.28.0"

import frappe

try:

    import l10n_ve.patches.monkey_patches

except ImportError:
    print(f"FAILURE!!!: Ocurrió cargando l10n_ve.patches.monkey_patches. Revise el log de errores")
    frappe.log_error(frappe.get_traceback(), 'cargando l10n_ve.monkey_patches')