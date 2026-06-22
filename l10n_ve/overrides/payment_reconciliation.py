"""Shim de compatibilidad — el motor de conciliación se migró a `mint`.

Toda la lógica vive ahora en `mint.apis.reconciliation`. Este módulo solo re-exporta
esos símbolos para no romper imports legacy (domina_isp y el JS que llama por la ruta
vieja `l10n_ve.overrides.payment_reconciliation.*`) durante la transición. Se eliminará
cuando esos consumidores apunten directo a mint (fase de limpieza).

Los HOOKS ya NO viven aquí: se movieron a mint/hooks.py (no se pueden re-exportar sin
dispararse doble). En sites SIN mint instalado (p. ej. designet) este import falla en
silencio a propósito: ahí no hay conciliación y nada importa este módulo.
"""
try:
    from mint.apis.reconciliation import (  # noqa: F401
        RECON_PENDING,
        RECON_DONE,
        RECON_REVIEW,
        REVIEW_OTHER_BANK,
        REVIEW_DUPLICATE_REFERENCE,
        CASH_LIKE_TYPES,
        DEPOSIT_COVERAGE_TOLERANCE,
        DEPOSIT_FIELDS,
        _is_bank_receive,
        _is_cash_like_receive,
        deposit_covers_payment,
        _cobro_bank_account,
        _deposit_base_filters,
        _first_deposit,
        find_matching_deposit,
        find_deposit_other_bank,
        find_duplicate_deposits,
        _apply_deposit_amount,
        reconcile_and_approve,
        _link_deposit_to_payment,
        before_submit_receive_payment,
        on_submit_receive_payment,
        validate_bank_transaction_duplicate,
        reconcile_drafts_for_deposit,
        reconcile_drafts_job,
        apply_format_rule,
    )
except ImportError:
    # mint no instalado en este site: sin motor de conciliación aquí.
    pass
