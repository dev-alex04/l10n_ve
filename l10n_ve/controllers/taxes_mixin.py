import frappe
from frappe import _, _dict

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.utils.constants import DocumentTransactionType
from frappe.utils import flt


class TaxesMixin:
    def validate_tax_structure(self) -> None:

        has_taxable_items = any(not item.vat_exempt for item in self.items)

        if not has_taxable_items and self.taxes_and_charges:
            self.taxes_and_charges = None
            self.set("taxes", [])
            self.apply_tds = 0

        has_vat_charge = any(tax.charge_type == 'VAT' for tax in self.taxes or [])

        if not has_vat_charge and self.apply_tds == 1:
            self.set("taxes", [])
            self.apply_tds = 0

    def calculate_total_withholding(self) -> None:

        self.total_withholding = 0.0

        self.total_withholding = sum([
            tax.tax_amount
            for tax in self.taxes or []
            if tax.is_tax_withholding_account
        ])

    def _set_base_total_with_vat(self) -> None:
        """Asigna base_total_with_vat tomando base_total de la fila VAT.

        Negocio: el equipo financiero necesita ver el monto antes de
        retenciones (base imponible + IVA) en moneda de la compañía.
        Fallback a base_net_total si no hay fila VAT.
        """
        result: float = flt(self.base_net_total)

        for tax_row in self.taxes or []:
            if tax_row.charge_type == "VAT":
                result = flt(tax_row.base_total)
                break

        self.base_total_with_vat = result

    # Prioridad de ordenamiento para la tabla de impuestos.
    # Menor número = aparece primero.
    _TAX_SORT_PRIORITY: dict[str, int] = {
        "On Net Total": 0,
        "On Previous Row Amount": 0,
        "On Previous Row Total": 0,
        "On Item Quantity": 0,
        "VAT": 0,
        "Actual": 0,
        "VAT Withholding": 1,
        "ISLR": 2,
    }

    def _sort_and_reindex_taxes(self) -> None:
        """Ordena las filas de impuestos por prioridad fiscal y reindexar.

        Orden resultante:
        1. Impuestos base (VAT, On Net Total, etc.)
        2. Retención de IVA (VAT Withholding)
        3. Retención de ISLR (ISLR)
        """
        if not self.taxes:
            return

        self.taxes.sort(
            key=lambda tax: self._TAX_SORT_PRIORITY.get(tax.charge_type, 0)
        )

        for i, tax in enumerate(self.taxes, start=1):
            tax.idx = i

    def _ensure_tax_cost_centers(self) -> None:
        """Asigna cost_center a las filas de impuestos que no lo tengan.

        Prioridad:
        1. cost_center del documento (self.cost_center)
        2. cost_center por defecto de la compañía
        """
        if not self.taxes:
            return

        default_cost_center: str = (
            getattr(self, "cost_center", "")
            or frappe.get_cached_value("Company", self.company, "cost_center")
            or ""
        )

        for tax in self.taxes:
            if not tax.get("cost_center") and default_cost_center:
                tax.cost_center = default_cost_center

    # ------------------------------ OVERRIDES ------------------------------ #

    def set_taxes_and_charges(self) -> None:
        super().set_taxes_and_charges()

        self.set_tax_withholding_ve()
        self.set_islr_withholding_ve()
        self._sort_and_reindex_taxes()
        self._ensure_tax_cost_centers()

    def calculate_taxes_and_totals(self) -> None:
        taxes_and_totals_calculator = TaxesAndTotals(self)
        taxes_and_totals_calculator.calculate_total_exempt()

        self.calculate_total_withholding()

    def set_tax_withholding(self) -> None:
        """
        Se inactiva la funcion nativa para obtener las retenciones.
        La funcion set_tax_withholding_ve  se encargara de esto
        """
        return

    def set_tax_withholding_ve(self) -> None:
        self.taxes = [
            tax for tax in self.taxes or []
            if not tax.get('is_tax_withholding_account') or tax.get('charge_type') == 'ISLR'
        ]

        if self.doctype in ("Purchase Invoice", "Purchase Order", "Supplier Quotation"):
            if not bool(frappe.db.get_value('Company',
                                            self.company,
                                            'is_special_taxpayer')):
                return

            withholding_category_name = frappe.db.get_value("Supplier",
                                                        self.supplier,
                                                        "tax_withholding_category")
        else:
            if not bool(frappe.db.get_value('Customer',
                                        self.customer,
                                        'is_special_taxpayer')):
                return

            withholding_category_name: str = frappe.db.get_value(
                "Customer",
                self.customer,
                "tax_withholding_category")

        if not withholding_category_name:
            return

        withholding_category = frappe.get_cached_doc("Tax Withholding Category",
                                                      withholding_category_name)

        withholding: _dict = withholding_category.get_withholding(self.company,
                                                                  self.doctype)

        if self.doctype in DocumentTransactionType.__ALL_INVOICE_DOCTYPES__:
            affected = self.get("affected_invoice_number") or self.return_against
            if self.is_return:
                if not self.return_against:
                    return

                withholding['description'] = \
                    f'{withholding["description"]} por Nota de Crédito contra factura {affected}'

            elif self.is_debit_note:

                withholding['description'] = \
                    f'{withholding["description"]} por Nota de Débito contra factura {affected}'


        # Solo agregar retención de IVA si hay al menos una fila VAT.
        # Sin IVA no hay base sobre la cual calcular la retención.
        has_vat_charge: bool = any(
            tax.charge_type == "VAT" for tax in self.taxes or []
        )
        if not has_vat_charge:
            return

        self.append("taxes", withholding)

    def set_islr_withholding_ve(self) -> None:
        """Agrega retención ISLR a la tabla de impuestos.

        - Ventas: se asigna automáticamente desde Customer.tabulator_islr.
        - Compras: se asigna manualmente vía diálogo en el formulario.
          Aquí solo se preservan las filas ISLR existentes.
        """
        if self.doctype in DocumentTransactionType.__PURCHASE_DOCTYPES__:
            # En compras el ISLR se agrega manualmente; no limpiar ni auto-asignar
            return

        if self.doctype not in DocumentTransactionType.__SALES_INVOICE_DOCTYPES__:
            return

        self.taxes = [
            tax for tax in self.taxes or []
            if tax.get("charge_type") != "ISLR"
        ]

        tabulator_name: str = frappe.db.get_value(
            "Customer", self.customer, "tabulator_islr"
        ) or ""
        if not tabulator_name:
            return

        islr_account: str = frappe.get_cached_value(
            "Company", self.company, "sales_islr_account"
        ) or ""
        if not islr_account:
            return

        tabulator = frappe.get_cached_doc("Tabulator ISLR", tabulator_name)
        if not tabulator.aliquot:
            return
        aliquot_info = tabulator.aliquot[0]

        if not aliquot_info:
            return

        base_amount: float = flt(self.total)
        tax_base: float = flt(base_amount * flt(aliquot_info.percentage_base) / 100, 2)
        islr_amount: float = flt(
            (tax_base * flt(aliquot_info.aliquot) / 100) - flt(aliquot_info.subtracting), 2
        )

        if islr_amount <= 0:
            return

        description: str = f"ISLR {tabulator_name} {tabulator.descripcion} ({flt(aliquot_info.aliquot)}%)"
        if self.is_return and self.return_against:

            type_doctype: str = (
                "Sales" if self.doctype in DocumentTransactionType.__SALES_DOCTYPES__
                else "Purchase"
            )

            affected_invoice_number: str = frappe.get_cached_value(
                f"{type_doctype} Invoice",
                self.return_against,
                "bill_no"
            )

            description += f" por Nota de Crédito contra factura {affected_invoice_number}"

        self.append("taxes", _dict({
            "charge_type": "ISLR",
            "category": "Total",
            "add_deduct_tax": "Deduct",
            "description": description,
            "is_tax_withholding_account": True,
            "account_head": islr_account,
            "tax_amount": islr_amount,
            "base_tax_amount": islr_amount,
            "rate": flt(aliquot_info.aliquot),
            "percentage_base": flt(aliquot_info.percentage_base),
            "subtracting": flt(aliquot_info.subtracting),
        }))

    # ------------------------------------------------------------------ #
    # Exclusividad NC ↔ ND por factura                                     #
    # ------------------------------------------------------------------ #

    def _validate_unique_note_per_invoice(self) -> None:
        """
        Regla de negocio fiscal venezolana:
        Una Factura de Venta solo puede tener UNA Nota de Crédito o UNA Nota
        de Débito activa. No se permiten duplicados ni coexistencia NC + ND.
        """
        if not self.get("return_against"):
            return

        si_bill_no: str = frappe.get_cached_value(
            "Sales Invoice", self.return_against, "bill_no"
        ) or ""
        si_label: str = (
            f'<a href="/app/sales-invoice/{self.return_against}">'
            f'{si_bill_no or self.return_against}</a>'
        )

        existing_nc: dict | None = frappe.db.get_value(
            "VE Sales Credit Note",
            {
                "return_against": self.return_against,
                "docstatus": 1,
                "name": ("!=", self.name),
            },
            ["name", "bill_no"],
            as_dict=True,
        )
        if existing_nc:
            nc_bill: str = existing_nc.bill_no or existing_nc.name
            nc_label: str = (
                f'<a href="/app/ve-sales-credit-note/{existing_nc.name}">'
                f'{nc_bill}</a>'
            )
            if self.doctype == "VE Sales Credit Note":
                frappe.throw(
                    _(
                        "La Factura {0} ya tiene una Nota de Crédito activa: "
                        "{1}. Solo se permite una NC por factura."
                    ).format(si_label, nc_label)
                )
            else:
                frappe.throw(
                    _(
                        "La Factura {0} ya tiene una Nota de Crédito activa: "
                        "{1}. No se puede crear una Nota de Débito sobre "
                        "una factura con NC vigente."
                    ).format(si_label, nc_label)
                )

        existing_nd: dict | None = frappe.db.get_value(
            "VE Sales Debit Note",
            {
                "return_against": self.return_against,
                "docstatus": 1,
                "name": ("!=", self.name),
            },
            ["name", "bill_no"],
            as_dict=True,
        )
        if existing_nd:
            nd_bill: str = existing_nd.bill_no or existing_nd.name
            nd_label: str = (
                f'<a href="/app/ve-sales-debit-note/{existing_nd.name}">'
                f'{nd_bill}</a>'
            )
            if self.doctype == "VE Sales Debit Note":
                frappe.throw(
                    _(
                        "La Factura {0} ya tiene una Nota de Débito activa: "
                        "{1}. Solo se permite una ND por factura."
                    ).format(si_label, nd_label)
                )
            else:
                frappe.throw(
                    _(
                        "La Factura {0} ya tiene una Nota de Débito activa: "
                        "{1}. No se puede crear una Nota de Crédito sobre "
                        "una factura con ND vigente."
                    ).format(si_label, nd_label)
                )

    # ------------------------------------------------------------------ #
    # Actualización de status en la factura padre                          #
    # ------------------------------------------------------------------ #

    def _update_parent_invoice_status(self) -> None:
        """
        Fuerza la actualización del status de la factura de venta padre
        cuando una NC o ND es aprobada o cancelada.

        Esto permite que la SI refleje correctamente 'Credit Note Issued'
        o 'Debit Note Issued' sin necesidad de recargar manualmente.
        """
        if not self.get("return_against"):
            return

        parent_si = frappe.get_doc("Sales Invoice", self.return_against)
        parent_si.set_status(update=True)
