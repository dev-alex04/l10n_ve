import json
import os

import frappe
from erpnext.setup.doctype.company.company import Company
from frappe import _
from l10n_ve import numbering
from l10n_ve.l10n_ve.doctype.ve_branch.ve_branch import ensure_main_branch
from l10n_ve.setup import (
    create_municipality_taxes_for_municipality,
    create_sales_taxes_and_charges_template,
    create_vat_withholding,
    set_chart_of_accounts,
    set_mode_of_payments,
    set_reference_currency,
)
from l10n_ve.utils.utils import (
    validate_tax_id_format,
    validate_taxpayer_and_person_type_consistency,
)
from l10n_ve.whitelisted.account.chart_of_accounts import get_app_charts_path

_allied_charts_cache = None


def get_allied_charts() -> dict:
    """Construye y cachea un diccionario {nombre_plan: es_aliado} desde los JSONs."""
    global _allied_charts_cache
    if _allied_charts_cache is not None:
        return _allied_charts_cache

    _allied_charts_cache = {}
    charts_path = get_app_charts_path()
    if not os.path.exists(charts_path):
        return _allied_charts_cache

    for fname in os.listdir(charts_path):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(charts_path, fname), "r", encoding="utf-8") as f:
                content = json.load(f)
                chart_name = content.get("name")
                if chart_name:
                    _allied_charts_cache[chart_name] = bool(content.get("is_allied_client_chart"))
        except (IOError, json.JSONDecodeError, KeyError) as e:
            frappe.log_error(
                message=f"Error al cargar plan de cuentas {fname}: {e}",
                title="Error en Plan de Cuentas"
            )
    return _allied_charts_cache


def is_allied_chart(chart_name: str) -> bool:
    """Verifica si el plan de cuentas seleccionado es de un cliente aliado
    leyendo el flag 'is_allied_client_chart' del JSON correspondiente."""
    return get_allied_charts().get(chart_name, False)

class CustomCompany(Company):

    def validate(self):
        super().validate()
        if self.is_new():
            self.flags.is_new_company = True
        validate_tax_id_format(self)
        validate_taxpayer_and_person_type_consistency(self)


    def on_update(self) -> None:
        """
        Sobrescribe el método on_update para ejecutar la configuración de la
        localización después de que la configuración estándar de la compañía
        se haya completado.
        """
        super().on_update()
        if self.flags.get("is_new_company"):
            if is_allied_chart(self.chart_of_accounts):
                frappe.msgprint(_("Plan de cuentas de cliente aliado cargado. Las configuraciones de impuestos automáticas fueron omitidas."))
            else:
                set_chart_of_accounts(company_name=self.name)
                create_vat_withholding(company_name=self.name)
                create_sales_taxes_and_charges_template(company_name=self.name)
                set_mode_of_payments(company_name=self.name)
                set_reference_currency(company_name=self.name)
                frappe.msgprint(_("Plan de cuentas Venezolano cargado. Por favor refrescar la vista."))

            # La compañía nace con su sucursal principal. Va después de los modos de pago,
            # que VE Branch exige: con un plan aliado puede no haberlos, y entonces no se crea.
            created, branch = ensure_main_branch(self.name)
            if created:
                frappe.msgprint(_("Se creó la sucursal principal {0}.").format(frappe.bold(branch)))

        if self.municipality:
            create_municipality_taxes_for_municipality(self.municipality)

    # --- Numeración ------------------------------------------------------------
    # `get_*` MIRA: formatea el correlativo que hoy tiene el documento en memoria, sin
    # tocar la base. Sirve para vistas previas y se puede llamar sobre una Company sin
    # guardar.
    #
    # `take_*` TOMA: bloquea la fila, formatea, comprueba que el número esté libre y
    # avanza el correlativo, todo en la misma transacción. Reemplaza al par
    # `get_* + increment_*`, que leía en memoria y escribía sin bloqueo: dos facturas
    # validadas a la vez sacaban el mismo número. La lógica vive en `l10n_ve.numbering`,
    # compartida con la serie digital y con los comprobantes de retención.

    def get_invoice_number(self) -> str:
        invoice_format = self.sales_invoice_number_format or numbering.DEFAULT_FORMAT
        next_invoice_num = self.sales_invoice_number_correlative or 1
        return self.format_number(invoice_format, next_invoice_num)

    def get_credit_note_number(self) -> str:
        credit_note_format = self.sales_credit_note_number_format or numbering.DEFAULT_FORMAT
        next_credit_note_num = self.sales_credit_note_number_correlative or 1
        return self.format_number(credit_note_format, next_credit_note_num)

    def get_debit_note_number(self) -> str:
        debit_note_format = self.sales_debit_note_number_format or numbering.DEFAULT_FORMAT
        next_debit_note_num = self.sales_debit_note_number_correlative or 1
        return self.format_number(debit_note_format, next_debit_note_num)

    def get_control_number(self) -> str:
        control_format = self.sales_invoice_control_number_format or numbering.DEFAULT_FORMAT
        next_control_num = self.sales_invoice_control_number_correlative or 1
        return self.format_number(control_format, next_control_num)

    def take_invoice_number(self, is_free=None) -> str:
        return numbering.take_next_number(
            "Company", self.name, "sales_invoice_number_correlative",
            format_field="sales_invoice_number_format", is_free=is_free,
        )

    def take_credit_note_number(self, is_free=None) -> str:
        return numbering.take_next_number(
            "Company", self.name, "sales_credit_note_number_correlative",
            format_field="sales_credit_note_number_format", is_free=is_free,
        )

    def take_debit_note_number(self, is_free=None) -> str:
        return numbering.take_next_number(
            "Company", self.name, "sales_debit_note_number_correlative",
            format_field="sales_debit_note_number_format", is_free=is_free,
        )

    def take_control_number(self, is_free=None) -> str:
        return numbering.take_next_number(
            "Company", self.name, "sales_invoice_control_number_correlative",
            format_field="sales_invoice_control_number_format", is_free=is_free,
        )

    def format_number(self, number_format: str | None, number: int) -> str:
        """Formatea el número. La implementación vive en `l10n_ve.numbering`."""
        return numbering.format_number(number_format, number)

    def before_save(self):

        if self.custom_company_primary_address and (not self.phone_no or not self.email):
            try:
                address = frappe.get_doc("Address",
                                          self.custom_company_primary_address)

                if not self.phone_no and address.phone:
                    self.phone_no = address.phone

                if not self.email and address.email_id:
                    self.email = address.email_id

            except frappe.DoesNotExistError:
                frappe.log_error(f"Address {self.custom_company_primary_address}"
                                 f"not found for Company {self.name}")
                pass

        if not self.vat_withholding_format:

            self.vat_withholding_format = "##############"

        if not self.vat_withholding_correlative:
            self.vat_withholding_correlative = 1

        self.set_municipality_from_primary_address()

    def set_municipality_from_primary_address(self) -> None:
        """
        Establece el campo 'municipality' de la Compañía en función de su
        'custom_company_primary_address'.
        """

        if not self.custom_company_primary_address:
            return

        try:
            address_doc = frappe.get_doc("Address", self.custom_company_primary_address)
            if address_doc.county:
                self.municipality = address_doc.county
        except frappe.DoesNotExistError:
            frappe.log_error(
                message=f"La dirección principal '{self.custom_company_primary_address}'"
                        f" no fue encontrada para la Compañía '{self.name}'.",
                title="Error de Vínculo de Dirección en Compañía"
            )
        except Exception as e:
            frappe.log_error(
                message=f"Error al obtener el municipio desde la dirección '"
                f"{self.custom_company_primary_address}' para la Compañía '{self.name}': {e}",
                title="Error de Actualización de Municipio en Compañía"
            )
