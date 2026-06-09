import frappe


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

    try:
        from l10n_ve.utils.utils import get_exchange_rate
        from frappe.utils import nowdate
        bootinfo.today_exchange_rate = get_exchange_rate(nowdate(), "USD")
    except Exception:
        bootinfo.today_exchange_rate = 0.0
