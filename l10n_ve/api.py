import frappe

@frappe.whitelist()
def get_portal_banks() -> list[str]:
    cache_key = "l10n_ve:portal_banks"
    portal_banks = frappe.cache().get_value(cache_key)

    if portal_banks:
        return portal_banks

    portal_banks = frappe.db.get_all(
        "Bank",
        fields=["name"],
        ignore_permissions=True,
    )

    frappe.cache().set_value(
        cache_key,
        portal_banks,
        expires_in_sec=3600
    )
    return portal_banks
