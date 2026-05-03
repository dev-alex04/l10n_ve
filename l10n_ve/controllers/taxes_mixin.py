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

        if self.doctype in DocumentTransactionType.__PURCHASE_DOCTYPES__:
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

    # ------------------------------------------------------------------ #
    # ISLR Compras — Asignación manual de retención                        #
    # Usado por Purchase Invoice y VE Purchase Credit Note.                #
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def set_islr_concept(self, tabulator_name: str) -> None:
        """Calcula y agrega la retención de ISLR en la tabla de impuestos.

        Flujo:
        1. Valida prerequisitos (proveedor, cuenta ISLR)
        2. Busca la alícuota según tipo de persona del proveedor
        3. Calcula el monto de retención
        4. Agrega la fila ISLR como Deduct en Purchase Taxes and Charges
        """
        if not tabulator_name:
            frappe.throw(_("Debe seleccionar un concepto de ISLR."))

        type_of_person, islr_account = self._validate_islr_prerequisites()

        tabulator, aliquot_info = self._get_islr_aliquot(
            tabulator_name, type_of_person
        )

        self._validate_no_duplicate_islr(tabulator.codigo)

        islr_amount: float = self._calculate_islr_amount(aliquot_info)
        if islr_amount <= 0:
            frappe.msgprint(
                _("El monto de retención de ISLR calculado es cero o negativo. "
                  "No se agregó retención.")
            )
            return

        tax_row: dict = self._build_islr_tax_row(
            tabulator, aliquot_info, islr_amount, islr_account
        )
        self.append("taxes", tax_row)

        self._sort_and_reindex_taxes()
        self.calculate_taxes_and_totals()
        self.save()

        frappe.msgprint(
            _("Retención de ISLR agregada: {0} ({1})").format(
                frappe.format_value(islr_amount, {"fieldtype": "Currency"}),
                tax_row["description"]
            ),
            indicator="green",
            alert=True
        )

    @frappe.whitelist()
    def remove_islr_concept(self) -> None:
        """Elimina la retención de ISLR de la tabla de impuestos."""
        has_islr: bool = any(
            tax.get("charge_type") == "ISLR" for tax in self.taxes or []
        )

        if not has_islr:
            frappe.msgprint(
                _("No hay retención de ISLR para eliminar."),
                indicator="orange",
                alert=True
            )
            return

        self._remove_existing_islr_taxes()
        self._sort_and_reindex_taxes()
        self.calculate_taxes_and_totals()
        self.save()

        frappe.msgprint(
            _("Retención de ISLR eliminada exitosamente."),
            indicator="green",
            alert=True
        )

    # ------------------------------------------------------------------ #
    # Helpers privados para ISLR de compras                                #
    # ------------------------------------------------------------------ #

    def _validate_islr_prerequisites(self) -> tuple[str, str]:
        """Valida que el proveedor y la compañía tengan la configuración ISLR.

        Returns:
            tuple: (type_of_person, islr_account)
        """
        type_of_person: str = frappe.db.get_value(
            "Supplier", self.supplier, "type_of_person"
        ) or ""
        if not type_of_person:
            frappe.throw(
                _("El proveedor {0} no tiene configurado el Tipo de Persona.").format(
                    self.supplier
                )
            )

        islr_account: str = frappe.get_cached_value(
            "Company", self.company, "purchase_islr_account"
        ) or ""
        if not islr_account:
            frappe.throw(
                _("La cuenta de ISLR de compras no está configurada "
                  "en la Compañía {0}.").format(self.company)
            )

        return type_of_person, islr_account

    def _get_islr_aliquot(
        self, tabulator_name: str, type_of_person: str
    ) -> tuple:
        """Obtiene el tabulador y la alícuota correspondiente al tipo de persona.

        Returns:
            tuple: (tabulator_doc, aliquot_row)
        """
        tabulator = frappe.get_cached_doc("Tabulator ISLR", tabulator_name)
        if not tabulator.aliquot:
            frappe.throw(
                _("El tabulador {0} no tiene alícuotas configuradas.").format(
                    tabulator_name
                )
            )

        aliquot_info = next(
            (
                aq for aq in tabulator.aliquot
                if aq.types_of_person == type_of_person and flt(aq.aliquot) > 0
            ),
            None
        )
        if not aliquot_info:
            frappe.throw(
                _("No se encontró alícuota para el tipo de persona '{0}' "
                  "en el tabulador '{1}'.").format(type_of_person, tabulator_name)
            )

        return tabulator, aliquot_info

    def _calculate_islr_amount(self, aliquot_info) -> float:
        """Calcula el monto de retención ISLR sobre la base imponible.

        Fórmula: (total × %base / 100 × alícuota / 100) - sustraendo
        """
        base_amount: float = flt(self.total)
        tax_base: float = flt(
            base_amount * flt(aliquot_info.percentage_base) / 100, 2
        )
        return flt(
            (tax_base * flt(aliquot_info.aliquot) / 100)
            - flt(aliquot_info.subtracting), 2
        )

    def _build_islr_tax_row(
        self, tabulator, aliquot_info, islr_amount: float, islr_account: str
    ) -> dict:
        """Construye el diccionario para la fila ISLR en Purchase Taxes and Charges."""
        description: str = (
            f"ISLR {tabulator.codigo} {tabulator.descripcion}"
            f" ({flt(aliquot_info.aliquot)}%)"
        )

        return {
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
            "code": tabulator.codigo,
            "tabulator_islr": tabulator.name,
        }

    def _validate_no_duplicate_islr(self, codigo: str) -> None:
        """Valida que no exista ya una retención ISLR con el mismo código."""
        existing_codes: list[str] = [
            tax.get("code", "") for tax in self.taxes or []
            if tax.get("charge_type") == "ISLR"
        ]
        if codigo in existing_codes:
            frappe.throw(
                _("Ya existe una retención ISLR con el código '{0}' "
                  "en este documento.").format(codigo)
            )

    def _remove_existing_islr_taxes(self) -> None:
        """Elimina todas las filas ISLR existentes de la tabla de impuestos."""
        self.taxes = [
            tax for tax in self.taxes or []
            if tax.get("charge_type") != "ISLR"
        ]
