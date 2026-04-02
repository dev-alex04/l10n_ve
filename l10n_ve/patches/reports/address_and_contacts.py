import frappe
from frappe import _
import erpnext.selling.report.address_and_contacts.address_and_contacts as ac

if "county" not in ac.field_map["Address"]:
    city_idx = ac.field_map["Address"].index("city")
    ac.field_map["Address"].insert(city_idx + 1, "county")

original_execute = ac.execute

def custom_execute(filters=None):
    columns, data = original_execute(filters)
    
    if len(columns) > 8:
        new_columns = [
            columns[0],
            columns[1], 
            columns[2],
            columns[3], 
            _("City"),      
            _("Municipio"),
            _("State"),     
            _("Postal Code"),
            _("Country"),   
        ]
        new_columns.extend(columns[9:])
        columns[:] = new_columns
    
    # Translate labels correctly
    for i in range(len(columns)):
        col = columns[i]
        if isinstance(col, str):
            parts = col.split(":")
            label = parts[0]
            parts[0] = str(_(label))
            columns[i] = ":".join(parts)
        elif isinstance(col, dict):
            col["label"] = str(_(col.get("label", "")))

    city_ids = set()
    county_ids = set()
    state_ids = set()
    
    for row in data:
        if len(row) > 7:
            # Original structure: 5:City, 6:County, 7:State, 8:Postal
            if row[5]: city_ids.add(row[5])
            if row[6]: county_ids.add(row[6])
            if row[7]: state_ids.add(row[7])

    city_map = {}
    if city_ids:
        try:
            cities = frappe.get_all("VE City", filters={"name": ("in", list(city_ids))}, fields=["name", "city"])
            for c in cities: city_map[c.name] = c.city
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("Error fetching VE City names"))

    county_map = {}
    if county_ids:
        try:
            counties = frappe.get_all("VE Municipality", filters={"name": ("in", list(county_ids))}, fields=["name", "municipality"])
            for m in counties: county_map[m.name] = m.municipality
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("Error fetching VE Municipality names"))
            
    state_map = {}
    if state_ids:
        try:
            states = frappe.get_all("VE State", filters={"name": ("in", list(state_ids))}, fields=["name", "state"])
            for s in states: state_map[s.name] = s.state
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("Error fetching VE State names"))
            
    for i, row in enumerate(data):
        if isinstance(row, list) and len(row) > 9:
            # Rebuild row to match new_columns exactly
            new_row = [
                row[0], # Customer
                row[1], # Group
                row[2], # Address ID (Hidden)
                row[3], # Address Line 1 (Dirección Principal)
                city_map.get(row[5], row[5]),    # index 4: City
                county_map.get(row[6], row[6]),  # index 5: Municipio
                state_map.get(row[7], row[7]),    # index 6: State
                row[8], # index 7: Postal Code
                row[9], # index 8: Country
            ]
            new_row.extend(row[10:]) # Append Contact columns
            data[i] = new_row

    return columns, data

ac.execute = custom_execute
