import json, os, glob

base = "/home/alexander/frappe-bench/apps/l10n_ve/l10n_ve/l10n_ve/doctype"
doctypes = ["islr_withholding_voucher", "vat_withholding_voucher"]

for dt in doctypes:
    path = f"{base}/{dt}/{dt}.json"
    if not os.path.exists(path):
        print(f"NOT FOUND: {path}")
        continue
    with open(path) as f:
        d = json.load(f)
    print(f"\n=== {dt} ===")
    print(f"  is_submittable: {d.get('is_submittable')}")
    print(f"  autoname: {d.get('autoname')}")
    print(f"  naming_series: {d.get('naming_series')}")
    print("  Fields of interest:")
    for field in d.get("fields", []):
        fn = field.get("fieldname", "")
        label = field.get("label", "")
        ft = field.get("fieldtype", "")
        if any(k in fn.lower() for k in ["number", "correlat", "serie", "naming", "seq", "no_", "numero", "voucher_no", "consecutivo"]):
            print(f"    {fn} | {ft} | {label}")

# Check hooks.py for doc_events
hooks_path = "/home/alexander/frappe-bench/apps/l10n_ve/l10n_ve/hooks.py"
with open(hooks_path) as f:
    content = f.read()

print("\n\n=== hooks.py doc_events for withholding ===")
in_doc_events = False
for line in content.splitlines():
    if "doc_events" in line:
        in_doc_events = True
    if in_doc_events:
        if "withholding" in line.lower() or "islr" in line.lower() or "vat" in line.lower():
            print(line)
        if in_doc_events and line.strip() == "}" and not line.strip().startswith("#"):
            in_doc_events = False

# Check python files for on_trash / before_delete
print("\n=== on_trash / before_delete in withholding py files ===")
for dt in doctypes:
    py_path = f"{base}/{dt}/{dt}.py"
    if os.path.exists(py_path):
        with open(py_path) as f:
            py = f.read()
        if "on_trash" in py or "before_delete" in py:
            print(f"  FOUND in {dt}.py")
        else:
            print(f"  NOT found in {dt}.py")

# Check for purchase invoice override for on_trash
override_path = "/home/alexander/frappe-bench/apps/l10n_ve/l10n_ve/overrides/purchase_invoice.py"
with open(override_path) as f:
    ov = f.read()
if "on_trash" in ov or "before_delete" in ov:
    print("  FOUND on_trash/before_delete in purchase_invoice.py override")
else:
    print("  NOT found on_trash/before_delete in purchase_invoice.py override")
