import frappe

def log_patch_error(patch_name: str, error: Exception) -> None:
    """Registra el error solo si no es un RuntimeError (DB no vinculada) o si la DB está lista."""
    if isinstance(error, RuntimeError):
        return
    
    print(f"ERROR!!!: No se pudo cargar el parche {patch_name}. Error: {error}")
    if frappe.local and getattr(frappe.local, "db", None):
        try:
            frappe.log_error(frappe.get_traceback(), f'Error al cargar el parche: {patch_name}')
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

    # Capa 1: red de seguridad — resetea cualquier prepared_report que quedó en DB
    try:
        from l10n_ve.tasks import reset_all_prepared_reports
        reset_all_prepared_reports()
    except Exception as e:
        log_patch_error('reset_all_prepared_reports', e)

    # Capa 2: suprime el timer de Frappe que activa prepared_report en BD
    try:
        from l10n_ve.patches.frappe.report_session_patch import apply as apply_session_patch
        apply_session_patch()
    except Exception as e:
        log_patch_error('report_session_patch', e)


    # Capa 3: aplica el monkeypatch de get_user_permissions
    try:
        import l10n_ve.patches.frappe.user_permissions_patch
    except Exception as e:
        log_patch_error('user_permissions_patch', e)

# Attempt to apply patches immediately.
try:
    apply_post_db_patches()
except Exception:
    pass
