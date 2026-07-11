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
        REVIEW_ALREADY_RECONCILED,
        REVIEW_DEPOSIT_NOT_SUBMITTED,
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
        find_consumed_deposit,
        find_unsubmitted_deposit,
        find_duplicate_deposits,
        find_consumed_deposit,
        find_unsubmitted_deposit,
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
    # Las constantes DEBEN coincidir exactamente con mint.apis.reconciliation: son
    # los literales del Select `custom_reconciliation_status` (opciones en español).
    # Un literal divergente nunca casaría contra la BD (estados fantasma). Ver el
    # test de paridad en l10n_ve/tests/test_reconciliation_shim_parity.py.
    RECON_PENDING = "Conciliación Pendiente"
    RECON_DONE = "Conciliado"
    RECON_REVIEW = "Revisar"
    REVIEW_OTHER_BANK = "other_bank"
    REVIEW_DUPLICATE_REFERENCE = "duplicate_reference"
    REVIEW_ALREADY_RECONCILED = "already_reconciled"
    REVIEW_DEPOSIT_NOT_SUBMITTED = "deposit_not_submitted"
    CASH_LIKE_TYPES = ("Cash", "Gateway", "Gangway")
    DEPOSIT_COVERAGE_TOLERANCE = 1.0
    DEPOSIT_FIELDS = ["name", "deposit", "unallocated_amount", "currency", "bank_account"]
    _is_bank_receive = lambda *a, **k: None
    _is_cash_like_receive = lambda *a, **k: None
    deposit_covers_payment = lambda *a, **k: None
    _cobro_bank_account = lambda *a, **k: None
    _deposit_base_filters = lambda *a, **k: None
    _first_deposit = lambda *a, **k: None
    find_matching_deposit = lambda *a, **k: None
    find_deposit_other_bank = lambda *a, **k: None
    find_consumed_deposit = lambda *a, **k: None
    find_unsubmitted_deposit = lambda *a, **k: None
    find_duplicate_deposits = lambda *a, **k: None
    find_consumed_deposit = lambda *a, **k: None
    find_unsubmitted_deposit = lambda *a, **k: None
    _apply_deposit_amount = lambda *a, **k: None
    reconcile_and_approve = lambda *a, **k: None
    _link_deposit_to_payment = lambda *a, **k: None
    before_submit_receive_payment = lambda *a, **k: None
    on_submit_receive_payment = lambda *a, **k: None
    validate_bank_transaction_duplicate = lambda *a, **k: None
    reconcile_drafts_for_deposit = lambda *a, **k: None
    reconcile_drafts_job = lambda *a, **k: None
    apply_format_rule = lambda *a, **k: None

