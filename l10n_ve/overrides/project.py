import frappe
from erpnext.projects.doctype.project.project import Project
from frappe.desk.form.assign_to import add as assign_to_user
import json
from frappe.share import add as share_doc
from frappe.utils import now

class CustomProject(Project):

    def before_insert(self):
        self.hour = frappe.utils.get_time(now()).strftime("%H:%M:%S")

    def after_insert(self):
        super().after_insert()
        
        self.assign_users_from_template()
        self.set_dates_from_sales_order()

    def set_dates_from_sales_order(self):
        if not self.sales_order:
            return

        try:
            so_dates = frappe.db.get_value(
                "Sales Order", 
                self.sales_order, 
                ["transaction_date", "delivery_date"], 
                as_dict=True
            )
            
            if not so_dates:
                return

            updates = {}
            if so_dates.get("transaction_date") and not self.expected_start_date:
                updates["expected_start_date"] = so_dates.transaction_date
            
            if so_dates.get("delivery_date") and not self.expected_end_date:
                updates["expected_end_date"] = so_dates.delivery_date

            if updates:
                frappe.db.set_value(self.doctype, self.name, updates)
                self.reload()
        except Exception:
            pass

    def assign_users_from_template(self):
        if not self.project_template:
            return
        
        # Asignar usuarios de la Plantilla de Proyecto al Proyecto
        assignments = frappe.get_all(
            "ToDo", 
            filters={
                "reference_type": "Project Template",
                "reference_name": self.project_template,
                "status": "Open"
            }, 
            fields=["allocated_to"]
        )

        for a in assignments:
            if a.allocated_to:
                self.assign_and_share("Project", self.name, a.allocated_to)

    def assign_and_share(self, doctype, name, user):
        # Asignar (Burbuja sidebar)
        if not frappe.db.exists("ToDo", {
            "reference_type": doctype,
            "reference_name": name,
            "allocated_to": user,
            "status": "Open"
        }):
            assign_to_user({
                "assign_to": [user],
                "doctype": doctype,
                "name": name,
                "description": "Responsable de Plantilla",
                "notify": 1
            })

        # Compartir (Permisos)
        if not frappe.db.exists("DocShare", {
            "share_doctype": doctype,
            "share_name": name,
            "user": user
        }):
            share_doc(
                doctype=doctype,
                name=name,
                user=user,
                read=1,
                write=1,
                share=0
            )



import json
import frappe
from frappe import _
from collections import defaultdict

@frappe.whitelist()
def get_events(doctype, start, end, filters=None, field_map=None, add_fields=None, style_field=None):
    if filters and isinstance(filters, str):
        filters = json.loads(filters)
    if not filters:
        filters = []

    if field_map and isinstance(field_map, str):
        field_map = json.loads(field_map)
    if not field_map:
        field_map = {"start": "expected_start_date", "end": "expected_end_date", "title": "project_name"}

    start_field = field_map.get("start")
    end_field = field_map.get("end")
    
    filters.extend([
        [doctype, start_field, "<=", end],
        [doctype, end_field, ">=", start]
    ])

    fields = [
        "name", "project_name", "expected_start_date", 
        "expected_end_date", "all_day", "status"
    ]

    events = frappe.get_list(doctype, fields=fields, filters=filters)

    project_names = [e.get("name") for e in events]
    
    if not project_names:
        return events

    # Obtiene todos los usuarios asignados en una sola consulta para evitar el problema N+1
    all_assigned_data = frappe.db.sql("""
        SELECT 
            t.reference_name,
            u.user_image as image, 
            u.full_name as name
        FROM `tabToDo` t
        JOIN `tabUser` u ON t.allocated_to = u.name
        WHERE t.reference_type = %s 
        AND t.reference_name IN %s
        AND t.status = 'Open'
    """, (doctype, tuple(project_names)), as_dict=True)

    # Agrupa las asignaciones por proyecto
    assignments_by_project = defaultdict(list)
    for d in all_assigned_data:
        assignments_by_project[d.reference_name].append({
            "image": d.image,
            "name": d.name,
            "initial": d.name[0].upper() if d.name else "?"
        })

    # Adjunta los usuarios a los eventos y corrige las fechas
    for event in events:
        if not event.get(start_field):
            event[start_field] = frappe.utils.today()
        if not event.get(end_field):
            event[end_field] = event[start_field]
        
        event["assigned_users"] = assignments_by_project.get(event.get("name"), [])
                
    return events