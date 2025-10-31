import frappe
from frappe import _
from frappe.utils import cstr
from frappe.model.document import Document

original_check_if_latest = Document.check_if_latest


def check_if_latest(self) -> None:
    """
    Versión personalizada de `check_if_latest` con un mensaje de error modificado.
    Esta función reemplaza a la original de Frappe.
    """

    self.load_doc_before_save(raise_exception=True)

    self._action = "save"
    previous = self._doc_before_save

    # previous is None for new document insert
    if not previous:
        self.check_docstatus_transition(0)
        return

    if cstr(previous.modified) != cstr(self._original_modified):

        custom_message = _("El Documento {0} del módulo {1} fue actualizado por otro usuario " \
                            "y no se pueden guardar sus cambios actuales. Por favor," \
                            "refrescar la página y volver a cargar los datos.").format(
                            frappe.bold(self.name), frappe.bold(_(self.doctype))
                            )

        frappe.msgprint(
            custom_message,
            title=_("Aviso de Sincronización"),
            raise_exception=frappe.TimestampMismatchError,
            indicator='yellow'
        )

    if not self.meta.issingle:
        self.check_docstatus_transition(previous.docstatus)

# Reemplazar el método original con nuestra función personalizada.
Document.check_if_latest = check_if_latest
