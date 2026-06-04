import frappe

def run():
    logs = frappe.get_all("Error Log", filters={"creation": [">=", "2026-05-30"]}, fields=["name", "creation", "method", "error"], limit=20)
    print(f"FOUND {len(logs)} ERROR LOGS SINCE YESTERDAY:")
    for l in logs:
        if any(w in (l.method or "").lower() or w in (l.error or "").lower() for w in ["impression", "pdf", "custom", "download", "retencion", "retention"]):
            print(f"\n--- Error Log: {l.name} ({l.creation}) ---")
            print(f"Method: {l.method}")
            print(f"Traceback:\n{l.error}")
            print("-----------------------------------------")
