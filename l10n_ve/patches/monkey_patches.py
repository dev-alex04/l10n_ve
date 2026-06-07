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

# Attempt to apply patches immediately.
try:
    apply_post_db_patches()
except Exception:
    pass
