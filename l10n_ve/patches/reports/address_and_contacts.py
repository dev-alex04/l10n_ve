import frappe
from frappe import _
import erpnext.selling.report.address_and_contacts.address_and_contacts as ac

if "county" not in ac.field_map["Address"]:
    city_idx = ac.field_map["Address"].index("city")
    ac.field_map["Address"].insert(city_idx + 1, "county")

original_execute = ac.execute

def custom_execute(filters=None):
    columns, data = original_execute(filters)
    
    if len(columns) > 6:
        columns[4] = "City"
        columns.insert(5, "Municipio")
        columns[6] = "State"
        columns[7] = "Postal Code"

    for i in range(len(columns)):
        col = columns[i]
        if isinstance(col, str):
            parts = col.split(":")
            label = parts[0]
            translated_label = _(label)
            parts[0] = str(translated_label)
            columns[i] = ":".join(parts)
        elif isinstance(col, dict):
            col["label"] = str(_(col.get("label", "")))

    city_ids = set()
    county_ids = set()
    state_ids = set()
    
    for row in data:
        if len(row) > 7:
            c = row[5]
            m = row[6]
            s = row[7]
            if c: city_ids.add(c)
            if m: county_ids.add(m)
            if s: state_ids.add(s)

    city_map = {}
    if city_ids:
        try:
            cities = frappe.get_all("VE City", filters={"name": ("in", list(city_ids))}, fields=["name", "city"])
            for c in cities:
                city_map[c.name] = c.city
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("Error fetching VE City names"))

    county_map = {}
    if county_ids:
        try:
            counties = frappe.get_all("VE Municipality", filters={"name": ("in", list(county_ids))}, fields=["name", "municipality"])
            for m in counties:
                county_map[m.name] = m.municipality
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("Error fetching VE Municipality names"))
            
    state_map = {}
    if state_ids:
        try:
            states = frappe.get_all("VE State", filters={"name": ("in", list(state_ids))}, fields=["name", "state"])
            for s in states:
                state_map[s.name] = s.state
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("Error fetching VE State names"))
            
    for row in data:
        if len(row) > 6:
            c = row[4]
            m = row[5]
            s = row[6]
            if c and c in city_map:
                row[4] = city_map[c]
            if m and m in county_map:
                row[5] = county_map[m]
            if s and s in state_map:
                row[6] = state_map[s]

            if len(row) > 7 and row[7]:
                row[7] = _(row[7])

    if len(columns) > 3:
        columns.pop(3)
        for row in data:
            if len(row) > 3 and isinstance(row, list):
                row.pop(3)

    return columns, data

ac.execute = custom_execute
