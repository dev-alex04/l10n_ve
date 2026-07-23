import frappe

def execute():
    # Force reset and reload the Administración workspace from the JSON file
    # This prevents any blank or corrupted state on testing/production environments.
    workspace_name = "Administración"

    # Clean database child table references for this workspace
    frappe.db.delete("Workspace Link", {"parent": workspace_name})
    frappe.db.delete("Workspace Shortcut", {"parent": workspace_name})
    frappe.db.delete("Workspace Chart", {"parent": workspace_name})
    frappe.db.delete("Workspace Custom Block", {"parent": workspace_name})
    frappe.db.delete("Workspace Number Card", {"parent": workspace_name})
    frappe.db.delete("Workspace Quick List", {"parent": workspace_name})

    # Delete the main workspace record
    frappe.db.delete("Workspace", {"name": workspace_name})

    # Reload from the app workspace JSON configuration file
    frappe.reload_doc("l10n_ve", "workspace", "administración", force=True)

    # Clear workspace cache to force UI refresh
    frappe.clear_cache(doctype="Workspace")
