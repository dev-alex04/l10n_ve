import frappe
from frappe import _, msgprint
from frappe.utils import cstr, compare
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

        custom_message = _(
            "El Documento {0} del módulo {1} fue actualizado por otro usuario " \
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

def validate_value(self, fieldname, condition, val2, doc=None, raise_exception=None, source_doc_info=None):
    """Check that value of fieldname should be 'condition' val2
    else throw Exception."""
    if not doc:
        doc = self

    val1 = doc.get_value(fieldname)

    df = doc.meta.get_field(fieldname)
    val2 = doc.cast(val2, df)

    if not compare(val1, condition, val2):
        label = doc.meta.get_label(fieldname)
        current_value = doc.get_value(fieldname)

        if doc.get("parentfield"):
            msg = _("Valor incorrecto en la fila {0}: ").format(doc.idx)
        else:
            msg = _("")

        if condition == "in":
            msg += _("El campo '{0}' debe ser uno de: {1}.").format(frappe.bold(label), frappe.bold(val2))
        elif condition == "not in":
            msg += _("El campo '{0}' no debe ser ninguno de: {1}.").format(frappe.bold(label), frappe.bold(val2))
        elif condition == "^":
            msg += _("El campo '{0}' debe comenzar con '{1}'.").format(frappe.bold(label), frappe.bold(val2))
        elif condition == "=":
            source_info_msg = ""
            if source_doc_info and len(source_doc_info) == 2:
                source_doctype, source_name = source_doc_info
                if source_doctype and source_name:
                    source_link = frappe.utils.get_link_to_form(source_doctype, source_name)
                    source_info_msg = _(" proveniente de {0} {1}").format(_(source_doctype), source_link)

            msg += _(
            "El valor del campo '{0}' no coincide con el del documento de origen{1}.<br>" \
            "<b>Valor esperado:</b> {2}<br>" \
            "<b>Valor actual:</b> {3}<br>" \
            "Por favor, corrija para poder continuar."
            ).format(frappe.bold(_(label)),
                     source_info_msg,
                     frappe.bold(val2),
                     frappe.bold(current_value))
        else:
            msg += _("{0} must be {1} {2}").format(label, condition, val2)

        msgprint(msg, raise_exception=raise_exception or True, title=_("Error de Validación"))

# Reemplazar el método original con nuestra función personalizada.
Document.check_if_latest = check_if_latest
Document.validate_value = validate_value
