import frappe
from frappe.utils import now, nowdate
from erpnext.projects.doctype.task.task import Task
from frappe.desk.form.assign_to import add as assign_to_user
from frappe.share import add as share_doc

class CustomTask(Task):
    def after_insert(self):
        self.assign_users_from_template()

    def validate(self):
        super().validate()

        if self.status == "Completed":
            doc_before_save = self.get_doc_before_save()
            
            if not doc_before_save or doc_before_save.status != "Completed":
                
                self.hour = frappe.utils.get_time(now()).strftime("%H:%M:%S")

                if not self.completed_by:
                    self.completed_by = frappe.session.user

                self.completed_on = nowdate()

    def assign_users_from_template(self):
        if not self.project:
            return

        template_name = frappe.db.get_value("Project", self.project, "project_template")
        if not template_name:
            return

        template_task_name = frappe.db.get_value(
            "Project Template Task", 
            {"parent": template_name, "subject": self.subject},
            "task",
        )
        
        if not template_task_name:
            return

        self.copy_permissions_from_template_task(template_task_name)

    def copy_permissions_from_template_task(self, template_task_name):
        shares = frappe.get_all("DocShare", 
            filters={
                "share_doctype": "Task", 
                "share_name": template_task_name
            },
            fields=["user", "read", "write", "share"]
        )
        
        for share in shares:
            self.share_task_with_user(share.user, share.read, share.write, share.share)

        todos = frappe.get_all("ToDo",
            filters={
                "reference_type": "Task",
                "reference_name": template_task_name,
                "status": "Open"
            },
            fields=["allocated_to", "description"]
        )
        
        for todo in todos:
            self.assign_and_share_user(todo.allocated_to, description=todo.description)

    def assign_and_share_user(self, user, description=None):
        if not description:
            description = "Asignación desde Plantilla"

        if not frappe.db.exists("ToDo", {
            "reference_type": "Task",
            "reference_name": self.name,
            "allocated_to": user,
            "status": "Open"
        }):
            assign_to_user({
                "assign_to": [user],
                "doctype": "Task",
                "name": self.name,
                "description": description,
                "notify": 1
            })

        self.share_task_with_user(user, read=1, write=1, share=0)

    def share_task_with_user(self, user, read=1, write=1, share=0):
        if not frappe.db.exists("DocShare", {
            "share_doctype": "Task",
            "share_name": self.name,
            "user": user
        }):
            share_doc(
                doctype="Task",
                name=self.name,
                user=user,
                read=read,
                write=write,
                share=share,
                notify=1
            )

def sync_attachment_to_project(doc, method):
    if doc.attached_to_doctype != "Task" or not doc.attached_to_name:
        return

    project = frappe.db.get_value("Task", doc.attached_to_name, "project")
    
    if project:
        if not frappe.db.exists("File", {
            "file_url": doc.file_url,
            "attached_to_doctype": "Project",
            "attached_to_name": project
        }):
            new_file = frappe.copy_doc(doc)
            new_file.attached_to_doctype = "Project"
            new_file.attached_to_name = project
            new_file.insert(ignore_permissions=True)