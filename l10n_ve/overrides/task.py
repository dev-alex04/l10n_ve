import frappe
from frappe.utils import now, nowdate
from erpnext.projects.doctype.task.task import Task

class CustomTask(Task):
    def validate(self):
        super().validate()

        if self.status == "Completed":
            doc_before_save = self.get_doc_before_save()
            
            if not doc_before_save or doc_before_save.status != "Completed":
                
                self.hour = frappe.utils.get_time(now()).strftime("%H:%M:%S")

                if not self.completed_by:
                    self.completed_by = frappe.session.user

                self.completed_on = nowdate()

def sync_attachment_to_project(doc, method):
    """
    Sincroniza los adjuntos de la Tarea al Proyecto relacionado.
    Se ejecuta cuando se inserta un nuevo archivo (File).
    """
    if doc.attached_to_doctype != "Task" or not doc.attached_to_name:
        return

    project = frappe.db.get_value("Task", doc.attached_to_name, "project")
    
    if not project:
        return

    if frappe.db.exists("File", {
        "file_url": doc.file_url,
        "attached_to_doctype": "Project",
        "attached_to_name": project
    }):
        return

    new_file = frappe.copy_doc(doc)
    new_file.attached_to_doctype = "Project"
    new_file.attached_to_name = project
    new_file.insert(ignore_permissions=True)