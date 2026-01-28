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
            so_dates = frappe.db.get_value("Sales Order", self.sales_order, 
                                           ["transaction_date", "delivery_date"], as_dict=True)
            
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
        except frappe.DoesNotExistError:
            frappe.log_error(
                f"La Orden de Venta {self.sales_order} no fue encontrada para el Proyecto {self.name}",
                "Sincronización de Fechas de Proyecto"
            )

    def assign_users_from_template(self):
        if not self.project_template:
            return
        
        assignments = frappe.get_all("ToDo", 
            filters={
                "reference_type": "Project Template",
                "reference_name": self.project_template,
                "status": "Open"
            }, 
            fields=["allocated_to", "description"]
        )

        project_tasks = frappe.get_all("Task", filters={"project": self.name}, pluck="name")

        for a in assignments:
            if not a.allocated_to:
                continue

            self.assign_and_share("Project", self.name, a.allocated_to)

            for task_name in project_tasks:
                self.assign_and_share("Task", task_name, a.allocated_to)

    def assign_and_share(self, doctype, name, user):
        exists = frappe.db.exists("ToDo", {
            "reference_type": doctype,
            "reference_name": name,
            "allocated_to": user,
            "status": "Open"
        })

        if not exists:
            assign_to_user({
                "assign_to": [user],
                "doctype": doctype,
                "name": name,
                "description": f"Copiado de Plantilla: {self.project_template}",
                "notify": 1
            })

        share_doc(
            doctype=doctype,
            name=name,
            user=user,
            read=1,
            write=1,
            share=0
        )
