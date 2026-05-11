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

    # ------------------------------ OVERRIDES ------------------------------ #

    def set_taxes_and_charges(self) -> None:
        super().set_taxes_and_charges()

        self.set_tax_withholding_ve()
        self.set_islr_withholding_ve()

        for i, tax in enumerate(self.taxes or [], start=1):
            tax.idx = i

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
        """Agrega retención ISLR a la tabla de impuestos para documentos de venta."""
        if self.doctype not in DocumentTransactionType.__SALES_INVOICE_DOCTYPES__:
            return

        self.taxes = [
            tax for tax in self.taxes or []
            if tax.get("charge_type") != "ISLR"
        ]

        islr_row: _dict | None = self._build_islr_tax_row()
        if islr_row:
            self.append("taxes", islr_row)

    def _build_islr_tax_row(self) -> _dict | None:
        """Construye la fila de retención ISLR o retorna None si no aplica."""
        from l10n_ve.utils.islr import get_islr_aliquot, calculate_islr_amount

        result = get_islr_aliquot(self.customer, self.company)
        if not result:
            return None

        aliquot_info, tabulator = result

        islr_account: str = frappe.get_cached_value(
            "Company", self.company, "sales_islr_account"
        ) or ""
        if not islr_account:
            return None

        islr_amount: float = calculate_islr_amount(flt(self.total), aliquot_info)
        if islr_amount <= 0:
            return None

        return _dict({
            "charge_type": "ISLR",
            "category": "Total",
            "add_deduct_tax": "Deduct",
            "description": self._build_islr_description(tabulator, aliquot_info),
            "is_tax_withholding_account": True,
            "account_head": islr_account,
            "tax_amount": islr_amount,
            "base_tax_amount": islr_amount,
            "rate": flt(aliquot_info.aliquot),
            "percentage_base": flt(aliquot_info.percentage_base),
            "subtracting": flt(aliquot_info.subtracting),
        })

    def _build_islr_description(self, tabulator, aliquot_info) -> str:
        """Genera la descripción del concepto ISLR incluyendo NC/ND si aplica."""
        description: str = (
            f"ISLR {tabulator.name} {tabulator.descripcion}"
            f" ({flt(aliquot_info.aliquot)}%)"
        )

        if self.is_return and self.return_against:
            type_doctype: str = (
                "Sales" if self.doctype in DocumentTransactionType.__SALES_DOCTYPES__
                else "Purchase"
            )
            bill_no: str = frappe.get_cached_value(
                f"{type_doctype} Invoice",
                self.return_against,
                "bill_no"
            ) or self.return_against
            description += f" por Nota de Crédito contra factura {bill_no}"

        elif getattr(self, "is_debit_note", 0) and self.return_against:
            bill_no: str = frappe.get_cached_value(
                "Sales Invoice", self.return_against, "bill_no"
            ) or self.return_against
            description += f" por Nota de Débito contra factura {bill_no}"

        return description

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
