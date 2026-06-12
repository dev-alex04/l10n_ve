import frappe

def log_patch_error(patch_name: str, error: Exception) -> None:
    """Log the error only if it is not a RuntimeError (DB not connected) or if DB is ready."""
    if isinstance(error, RuntimeError):
        return
    
    print(f"ERROR!!!: Failed to load patch {patch_name}. Error: {error}")
    if frappe.local and getattr(frappe.local, "db", None):
        try:
            frappe.log_error(frappe.get_traceback(), f'Error loading patch: {patch_name}')
        except Exception:
            pass

try:
    import l10n_ve.patches.model.document
except Exception as e:
    log_patch_error('l10n_ve.patches.model.document', e)

try:
    import l10n_ve.patches.utilities.transaction_base
except Exception as e:
    log_patch_error('l10n_ve.patches.utilities.transaction_base', e)

try:
    import l10n_ve.patches.accounts.utils
except Exception as e:
    log_patch_error('l10n_ve.patches.accounts.utils', e)

try:
    import l10n_ve.patches.accounts.chart_of_accounts
except Exception as e:
    log_patch_error('l10n_ve.patches.accounts.chart_of_accounts', e)

try:
    import l10n_ve.patches.accounts.general_ledger
except Exception as e:
    log_patch_error('l10n_ve.patches.accounts.general_ledger', e)

try:
    import l10n_ve.patches.accounts.payment_entry
except Exception as e:
    log_patch_error('l10n_ve.patches.accounts.payment_entry', e)

try:
    import l10n_ve.patches.setup.utils
except Exception as e:
    log_patch_error('l10n_ve.patches.setup.utils', e)

try:
    import l10n_ve.patches.stock.utils
except Exception as e:
    log_patch_error('l10n_ve.patches.stock.utils', e)

def apply_post_db_patches() -> None:
    try:
        import l10n_ve.patches.reports.general_ledger
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.general_ledger', e)

    try:
        import l10n_ve.patches.reports.trial_balance_for_party
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.trial_balance_for_party', e)

    try:
        import l10n_ve.patches.reports.gross_profit
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.gross_profit', e)

    try:
        import l10n_ve.patches.reports.payment_period_based_on_invoice_date
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.payment_period_based_on_invoice_date', e)

    try:
        import l10n_ve.patches.reports.address_and_contacts
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.address_and_contacts', e)

    try:
        import l10n_ve.patches.reports.balance_sheet
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.balance_sheet', e)

    try:
        import l10n_ve.patches.reports.party_ledger_summary
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.party_ledger_summary', e)

    try:
        import l10n_ve.patches.reports.receivable_payable
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.receivable_payable', e)

    try:
        import l10n_ve.patches.reports.accounts_receivable
    except Exception as e:
        log_patch_error('l10n_ve.patches.reports.accounts_receivable', e)

    # Layer 1: Safety net - reset any prepared_report stuck in the database
    try:
        from l10n_ve.tasks import reset_all_prepared_reports
        reset_all_prepared_reports()
    except Exception as e:
        log_patch_error('reset_all_prepared_reports', e)

    # Layer 2: Suppress Frappe's timer that activates prepared_report
    try:
        from l10n_ve.patches.frappe.report_session_patch import apply as apply_session_patch
        apply_session_patch()
    except Exception as e:
        log_patch_error('report_session_patch', e)

    # Layer 5: Apply monkeypatch for Excel report export with professional styling
    try:
        from l10n_ve.patches.frappe.report_export_patch import apply as apply_export_patch
        apply_export_patch()
    except Exception as e:
        log_patch_error('report_export_patch', e)


    # Layer 3: Apply monkeypatch for get_user_permissions
    try:
        import l10n_ve.patches.frappe.user_permissions_patch
    except Exception as e:
        log_patch_error('user_permissions_patch', e)

    # Layer 4: Apply global monkeypatch for report_to_pdf to prevent HostNotFoundError
    try:
        from frappe.utils import print_format
        from l10n_ve.utils.pdf_utils import custom_report_to_pdf
        print_format.report_to_pdf = custom_report_to_pdf
    except Exception as e:
        log_patch_error('custom_report_to_pdf_patch', e)

_post_db_patches_applied = False


def ensure_post_db_patches() -> None:
    """Aplica los patches post-DB una sola vez por proceso (hook before_request/before_job).

    El import del paquete l10n_ve puede ocurrir antes de que exista conexión
    a la BD (workers web/RQ recién levantados), o no ocurrir nunca en jobs
    que no tocan código de l10n_ve (p.ej. el envío de Auto Email Reports).
    En ambos casos los workers ejecutaban los reportes core sin parchear:
    de ahí el IndexError diario de "Payment Period Based On Invoice Date",
    cuyo parche existe desde abril pero no se cargaba. Este hook garantiza
    que los patches queden aplicados en cuanto haya BD disponible, sin
    re-aplicarlos en cada request/job.
    """
    global _post_db_patches_applied
    if _post_db_patches_applied:
        return

    if not getattr(frappe.local, "db", None):
        # Sin BD todavía (import temprano del paquete): se reintenta en el
        # siguiente before_request/before_job, ya con conexión.
        return

    _post_db_patches_applied = True
    apply_post_db_patches()


# Attempt to apply patches immediately (solo surte efecto si ya hay BD).
try:
    ensure_post_db_patches()
except Exception:
    pass
