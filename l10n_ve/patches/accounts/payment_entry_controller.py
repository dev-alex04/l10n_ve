"""La clase de Payment Entry tiene que llevar la lógica de l10n_ve, también con hrms.

Frappe resuelve `override_doctype_class` con la ÚLTIMA app de la lista `installed_apps`
del sitio (el orden en que se instalaron, no el de apps.txt). hrms declara su propia clase
de Payment Entry, `EmployeePaymentEntry`, que hereda directo de ERPNext: en un sitio donde
hrms se instaló después de l10n_ve --domina.designet--, ganaba la de hrms y no corría nada
de `CustomPaymentEntry` (retenciones, IGTF, validaciones).

`combine_with_hrms` reemplaza la clase del módulo de hrms por una que hereda de las dos,
con l10n_ve PRIMERO en el orden de resolución: si ambas definen un método, manda
l10n_ve, y con `super()` sigue la de hrms (p. ej. las referencias válidas son las de hrms,
con los documentos de empleado, más las notas de débito de l10n_ve). Frappe toma la clase
con `getattr(módulo, nombre)` al resolver el hook, así que alcanza con reemplazar el
atributo; en un bench sin hrms no hace nada.

`check_controller` (after_migrate) deja un Error Log si la clase que resuelve el sitio no
lleva la lógica de l10n_ve o, con hrms instalado, la de hrms.
"""

import frappe

from l10n_ve.overrides.payment_entry import CustomPaymentEntry

try:
    from hrms.overrides import employee_payment_entry as hrms_module
except ImportError:
    hrms_module = None  # bench sin hrms

# La clase original de hrms, para comprobar que la del sitio la conserva.
HRMS_BASE = None

if hrms_module is not None:
    # Si el módulo se recarga, la clase de hrms ya es la combinada: se parte de la original.
    HRMS_BASE = getattr(
        hrms_module.EmployeePaymentEntry, "_hrms_base", hrms_module.EmployeePaymentEntry
    )

    # A nivel de módulo y no dentro de una función: Frappe guarda los documentos en Redis
    # con pickle, que solo serializa clases importables por su nombre. Definida dentro de
    # `combine_with_hrms`, cualquier `get_cached_doc` de un Payment Entry fallaba con
    # «Can't get local object».
    class VEEmployeePaymentEntry(CustomPaymentEntry, HRMS_BASE):
        """Payment Entry de l10n_ve con los documentos de empleado de hrms."""

        _hrms_base = HRMS_BASE


def combine_with_hrms() -> None:
    """Idempotente: deja la clase combinada en el módulo de hrms, donde apunta su hook."""
    if hrms_module is not None:
        hrms_module.EmployeePaymentEntry = VEEmployeePaymentEntry


def check_controller() -> None:
    """Error Log si la clase de Payment Entry del sitio pierde la lógica de l10n_ve o de hrms."""
    from frappe.model.base_document import import_controller

    controller = import_controller("Payment Entry")
    missing = []
    if not issubclass(controller, CustomPaymentEntry):
        missing.append("l10n_ve (CustomPaymentEntry)")
    if (
        "hrms" in frappe.get_installed_apps()
        and HRMS_BASE
        and not issubclass(controller, HRMS_BASE)
    ):
        missing.append("hrms (EmployeePaymentEntry)")

    if missing:
        frappe.log_error(
            title="Payment Entry sin la lógica de " + " y ".join(missing),
            message=(
                f"La clase que resuelve el sitio es {controller.__module__}.{controller.__name__} "
                f"y no hereda de: {', '.join(missing)}. Revisar el orden de `installed_apps` y "
                "las clases de `override_doctype_class` de Payment Entry."
            ),
        )
