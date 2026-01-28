import frappe
from erpnext.projects.doctype.project.project import Project
from frappe.desk.form.assign_to import add as assign_to_user
from frappe.share import add as share_doc

class CustomProject(Project):
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