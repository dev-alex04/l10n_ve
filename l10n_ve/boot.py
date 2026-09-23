import frappe
from frappe.utils import flt, getdate, nowdate

from l10n_ve.l10n_ve.doctype.ve_branch.ve_branch import get_main_branches_for_user


def get_boot_info(bootinfo: dict) -> None:
    """
    Inyecta datos de l10n_ve en el boot de Frappe.
    Se ejecuta una sola vez al iniciar sesión — sin consultas por refresh.
    """
    try:
        bootinfo.tfhka_enabled = bool(
            frappe.get_cached_value("TFHKA Settings", "TFHKA Settings", "enabled")
        )
    except Exception:
        bootinfo.tfhka_enabled = False

    # Empresas que emiten el documento 04. En la nota de entrega y el traslado, solo en ellas
    # aparecen el bloque del 04 (tipo, motivo, vehículo), la propuesta de tipo y «Enviar a
    # HKA»; y sin ninguna, la lista no muestra sus filtros. Anular uno ya emitido no depende
    # de esto: el documento existe en HKA.
    try:
        from l10n_ve.digital_invoice.dispatch_note_integration import (
            dispatch_note_companies,
        )
        bootinfo.dispatch_note_companies = dispatch_note_companies()
    except Exception:  # noqa: BLE001 - el boot no puede romper el inicio de sesión
        bootinfo.dispatch_note_companies = []

    try:
        bootinfo.tax_calculation_method = frappe.get_cached_value(
            "Venezuela Account Settings", "Venezuela Account Settings",
            "tax_calculation_method",
        ) or ""
    except Exception:
        bootinfo.tax_calculation_method = ""

    try:
        from l10n_ve.utils.utils import get_exchange_rate
        bootinfo.today_exchange_rate = get_exchange_rate(nowdate(), "USD")
    except Exception:
        bootinfo.today_exchange_rate = 0.0

    # Calcular referencias USD por tarjeta usando tasa de cada transacción
    try:
        bootinfo.card_usd_refs = _calculate_card_usd_references()
    except Exception:
        bootinfo.card_usd_refs = {}

    # Sucursal principal por compañía, para proponerla en los documentos nuevos
    # (public/js/utils/ve_main_branch_default.js). Vacío si el usuario tiene sucursal.
    # El boot no puede romper el inicio de sesión: entre el deploy y el migrate, por
    # ejemplo, la columna is_main todavía no existe.
    try:
        bootinfo.ve_main_branches = get_main_branches_for_user(frappe.session.user)
    except Exception:  # noqa: BLE001
        bootinfo.ve_main_branches = {}


def _calculate_card_usd_references() -> dict:
    """Calcula los totales USD de referencia para las 4 tarjetas del workspace
    de contabilidad, usando la tasa de cambio de cada transacción individual.

    Para transacciones en USD: usa conversion_rate de la transacción.
    Para transacciones en VES: busca la tasa BCV del posting_date.
    """
    company = frappe.defaults.get_user_default("Company")
    if not company:
        return {}

    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    if company_currency not in ("VES", "VEF"):
        return {}

    today = getdate(nowdate())
    year_start = f"{today.year}-01-01"

    results = {}

    # ── Total Outgoing Bills (Sales Invoice → base_net_total) ────────
    results["Total Outgoing Bills"] = _calc_invoice_usd_ref(
        "Sales Invoice", "base_net_total", company, year_start
    )

    # ── Total Incoming Bills (Purchase Invoice → base_net_total) ─────
    results["Total Incoming Bills"] = _calc_invoice_usd_ref(
        "Purchase Invoice", "base_net_total", company, year_start
    )

    # ── Total Incoming Payment (Payment Entry Receive → base_received_amount)
    results["Total Incoming Payment"] = _calc_payment_usd_ref(
        company, year_start, "Receive", "base_received_amount"
    )

    # ── Total Outgoing Payment (Payment Entry Pay → base_paid_amount)
    results["Total Outgoing Payment"] = _calc_payment_usd_ref(
        company, year_start, "Pay", "base_paid_amount"
    )

    return results


def _calc_invoice_usd_ref(doctype: str, agg_field: str, company: str, year_start: str) -> dict:
    """Calcula el total USD para Sales/Purchase Invoice
    usando la tasa de cada transacción."""
    from l10n_ve.utils.utils import get_exchange_rate

    docs = frappe.get_all(
        doctype,
        filters={
            "docstatus": 1,
            "company": company,
            "posting_date": [">=", year_start],
        },
        fields=[agg_field, "conversion_rate", "currency", "posting_date"],
    )

    if not docs:
        return {"usd_total": 0, "avg_rate": 0}

    # Recopilar fechas para transacciones no-USD
    dates_needing_rate: set = set()
    for doc in docs:
        if doc.get("currency") != "USD":
            dates_needing_rate.add(str(doc.posting_date))

    date_rates: dict = {}
    for d in dates_needing_rate:
        date_rates[d] = get_exchange_rate(d, "USD")

    usd_total: float = 0
    total_ves: float = 0

    for doc in docs:
        base_value = flt(doc.get(agg_field))
        total_ves += base_value
        rate = flt(doc.get("conversion_rate"))

        if doc.get("currency") == "USD" and rate > 0:
            usd_total += base_value / rate
        else:
            day_rate = date_rates.get(str(doc.posting_date), 0)
            if day_rate > 0:
                usd_total += base_value / day_rate

    avg_rate = total_ves / usd_total if usd_total > 0 else 0

    return {
        "usd_total": flt(usd_total, 2),
        "avg_rate": flt(avg_rate, 2),
    }


def _calc_payment_usd_ref(
    company: str, year_start: str, payment_type: str, agg_field: str
) -> dict:
    """Calcula el total USD para Payment Entry
    usando la tasa de cada transacción."""
    from l10n_ve.utils.utils import get_exchange_rate

    docs = frappe.get_all(
        "Payment Entry",
        filters={
            "docstatus": 1,
            "company": company,
            "posting_date": [">=", year_start],
            "payment_type": payment_type,
        },
        fields=[
            agg_field, "posting_date",
            "paid_from_account_currency", "paid_to_account_currency",
            "source_exchange_rate", "target_exchange_rate",
        ],
    )

    if not docs:
        return {"usd_total": 0, "avg_rate": 0}

    dates_needing_rate: set = set()
    for doc in docs:
        if doc.get("paid_from_account_currency") != "USD" and doc.get("paid_to_account_currency") != "USD":
            dates_needing_rate.add(str(doc.posting_date))

    date_rates: dict = {}
    for d in dates_needing_rate:
        date_rates[d] = get_exchange_rate(d, "USD")

    usd_total: float = 0
    total_ves: float = 0

    for doc in docs:
        base_value = flt(doc.get(agg_field))
        total_ves += base_value

        from_curr = doc.get("paid_from_account_currency")
        to_curr = doc.get("paid_to_account_currency")
        src_rate = flt(doc.get("source_exchange_rate"))
        tgt_rate = flt(doc.get("target_exchange_rate"))

        if from_curr == "USD" and src_rate > 0:
            usd_total += base_value / src_rate
        elif to_curr == "USD" and tgt_rate > 0:
            usd_total += base_value / tgt_rate
        else:
            day_rate = date_rates.get(str(doc.posting_date), 0)
            if day_rate > 0:
                usd_total += base_value / day_rate

    avg_rate = total_ves / usd_total if usd_total > 0 else 0

    return {
        "usd_total": flt(usd_total, 2),
        "avg_rate": flt(avg_rate, 2),
    }
