import frappe
from erpnext.projects.doctype.project.project import Project
from frappe.desk.form.assign_to import add as assign_to_user

class CustomProject(Project):
    def after_insert(self):
        super().after_insert()
        
        self.assign_users_from_template()

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
            if a.allocated_to:
                exists = frappe.db.exists("ToDo", {
                    "reference_type": "Project",
                    "reference_name": self.name,
                    "allocated_to": a.allocated_to,
                    "status": "Open"
                })

                if not exists:
                    assign_to_user({
                        "assign_to": [a.allocated_to],
                        "doctype": "Project",
                        "name": self.name,
                        "description": f"Copiado de Plantilla: {self.project_template}",
                        "notify": 1 
                    })

                for task_name in project_tasks:
                    exists_task = frappe.db.exists("ToDo", {
                        "reference_type": "Task",
                        "reference_name": task_name,
                        "allocated_to": a.allocated_to,
                        "status": "Open"
                    })
                    
                    if not exists_task:
                        assign_to_user({
                            "assign_to": [a.allocated_to],
                            "doctype": "Task",
                            "name": task_name,
                            "description": f"Copiado de Plantilla: {self.project_template}",
                            "notify": 1
                        })
