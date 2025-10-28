import frappe

from erpnext.utilities.utils import get_link_to_form
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.controllers.taxes_mixin import TaxesMixin

class CustomSalesOrder(TaxesMixin, SalesOrder):

    def calculate_taxes_and_totals(self) -> None:

        taxes_and_totals_calculator = TaxesAndTotals(self)

        self.calculate_commission()
        self.calculate_contribution()

        taxes_and_totals_calculator.calculate_total_exempt()
        self.calculate_total_withholding()

    def on_trash(self) -> None:
        """
        Evita la eliminación de documentos que han sido anulados.
        """
        if self.is_void:
            frappe.throw(_("No se puede eliminar un documento que ha sido anulado."))

@frappe.whitelist()
def upload_voucher_data(docname,
                        voucher_number,
                        withholding_date,
                        file_url=None)-> dict:
    """
    Actualiza la Sales Invoice (Factura de Venta) con los datos del
    comprobante de retención.
    """
    try:
        doc = frappe.get_doc("Sales Invoice", docname)

        doc.db_set('vat_withholding_voucher_number', voucher_number)
        doc.db_set('withholding_date', withholding_date)
        doc.db_set('voucher_image', file_url)

        doc.add_comment(
            "Comment",
            f"Comprobante de Retención cargado. Número: {voucher_number}. Fecha: {withholding_date}.",

        )

        return {
            "status": "success",
            "msg": "Factura de Venta actualizada con los datos del comprobante."
        }

    except frappe.DoesNotExistError:
        frappe.log_error(f"Sales Invoice {docname} no encontrada.",
                         "Error en upload_voucher_data")
        return {
            "status": "error",
            "msg": f"Factura de Venta con ID {docname} no encontrada."
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en upload_voucher_data")
        return {
            "status": "error",
            "msg": f"Error inesperado al guardar los datos: {str(e)}"
        }

@frappe.whitelist()
def upload_islr_voucher_data(docname,
                             islr_date,
                             islr_receipt_number=None,
                             file_url=None)-> dict:
    """
    Actualiza la Sales Invoice (Factura de Venta)
    con los datos del comprobante de retención de ISLR.
    """
    try:
        # Validación en el backend
        if not islr_date or not file_url:
            frappe.throw(_("La fecha y el archivo del comprobante de ISLR son obligatorios."))

        doc = frappe.get_doc("Sales Invoice", docname)

        doc.db_set('islr_receipt_number', islr_receipt_number)
        doc.db_set('islr_date', islr_date)
        doc.db_set('voucher_image_islr', file_url)

        # Construir el comentario dinámicamente
        comment_text = f"Comprobante de Retención de ISLR cargado. Fecha: {islr_date}."
        if islr_receipt_number:
            comment_text = f"Comprobante de Retención de ISLR cargado. Número: {islr_receipt_number}. Fecha: {islr_date}."
        else:
            comment_text = f"Comprobante de Retención de ISLR cargado (sin número). Fecha: {islr_date}."

        doc.add_comment(
            "Comment",
            comment_text,
        )

        return {
            "status": "success",
            "msg": "Factura de Venta actualizada con los datos del comprobante de ISLR."
        }

    except frappe.DoesNotExistError:
        frappe.log_error(f"Sales Invoice {docname} no encontrada.", "Error en upload_islr_voucher_data")
        return {"status": "error", "msg": f"Factura de Venta con ID {docname} no encontrada."}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en upload_islr_voucher_data")
        return {"status": "error", "msg": f"Error inesperado al guardar los datos: {str(e)}"}

@frappe.whitelist()
def void_document(doctype, name):
    """
    Marca el documento como anulado (is_void = 1).
    Solo se permite en documentos cancelados (docstatus = 2).
    """

    doc = frappe.get_doc(doctype, name)
    if doc.docstatus != 2:
        frappe.throw(_("Solo se pueden anular documentos que ya están cancelados."))

    def _check_for_duplicate_before_void(field_name,
                                         value_to_check,
                                         label)-> None:
        if not value_to_check:
            return

        filters = {
            field_name: value_to_check,
            "company": doc.company,
            "name": ["!=", doc.name],
        }

        # Busca en borradores (0), enviados (1) o anulados (is_void=1)
        duplicated_doc_name = (
            frappe.db.get_value(doctype, {**filters, "docstatus": ["in", [0, 1]]}, "name") or
            frappe.db.get_value(doctype, {**filters, "is_void": 1}, "name")
        )

        if duplicated_doc_name:
            link = get_link_to_form(doctype, duplicated_doc_name)
            message = _(
                "No se puede anular este documento porque el {label} '{value}' "
                "ya está siendo utilizado por el documento {link}. "
                "Este número debe ser liberado primero."
            ).format(label=label, value=frappe.bold(value_to_check), link=link)
            frappe.throw(message, title=_("Anulación Bloqueada por Duplicado"))

    if doc.is_return:
        _check_for_duplicate_before_void("credit_note_no",
                                         doc.credit_note_no,
                                         _("número de nota de crédito"))
    elif doc.is_debit_note:
        _check_for_duplicate_before_void("debit_note_no",
                                          doc.debit_note_no,
                                            _("número de nota de débito"))
    else:
        _check_for_duplicate_before_void("bill_no",
                                         doc.bill_no,
                                         _("número de factura"))

    _check_for_duplicate_before_void("bill_control",
                                     doc.bill_control,
                                       _("número de control"))

    frappe.db.set_value(doctype, name, "is_void", True)
    doc.add_comment("Comment", _("Documento marcado como Anulado."))

    frappe.clear_document_cache(doctype, name)
    doc.reload()
