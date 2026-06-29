#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/alexander/frappe-bench/apps/frappe')
sys.path.insert(0, '/home/alexander/frappe-bench/apps/erpnext')
sys.path.insert(0, '/home/alexander/frappe-bench/apps/l10n_ve')

import frappe
frappe.init(site='api.local', sites_path='/home/alexander/frappe-bench/sites')
frappe.connect()

rows = frappe.db.sql(
    'SELECT name, islr_withholding_correlative, vat_withholding_correlative FROM `tabCompany`',
    as_dict=True
)
for r in rows:
    print(f"Empresa: {r.name}")
    print(f"  ISLR correlativo: {r.islr_withholding_correlative}")
    print(f"  IVA  correlativo: {r.vat_withholding_correlative}")
    print()

frappe.db.close()
