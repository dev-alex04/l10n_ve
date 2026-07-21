import frappe
from l10n_ve.setup import create_retention_reminder_email_template

def execute() -> None:
    """Ejecuta el parche reutilizando la función oficial del setup."""
    print("Ejecutando parche: Creando/actualizando plantilla de correo predeterminada para recordatorio de retención...")
    create_retention_reminder_email_template()
