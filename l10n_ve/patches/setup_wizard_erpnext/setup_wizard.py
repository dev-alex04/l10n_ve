import frappe
from frappe import _
import erpnext.setup.setup_wizard.setup_wizard as erpnext_setup_wizard

original_setup_company = erpnext_setup_wizard.setup_company


def setup_company(args):
  """
  Esta es nuestra función personalizada que "envuelve" a la original.
  Primero ejecuta la creación de la compañía estándar y luego
  le añade nuestro campo personalizado (tax_id).
  """
  original_setup_company(args)

  tax_id = args.get("tax_id")
  company_name = args.get("company_name")

  if tax_id and company_name and frappe.db.exists("Company", company_name):
    try:
      frappe.db.set_value("Company", company_name, "tax_id", tax_id)
      print(f"L10N VE Patch: Guardado tax_id '{tax_id}' para la compañía '{company_name}'.")
    except Exception as e:
      frappe.log_error(f"L10N VE Patch: No se pudo guardar el tax_id: {e}", "Setup Wizard Customization")

erpnext_setup_wizard.setup_company = setup_company
