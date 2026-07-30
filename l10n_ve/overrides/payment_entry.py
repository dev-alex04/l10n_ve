import json
from collections import defaultdict

import frappe
from frappe import _, _dict
from frappe.utils import cint, flt
from frappe.model.document import Document

from erpnext.accounts.doctype.payment_entry.payment_entry import (
    get_outstanding_reference_documents as original_get_outstanding_reference_documents,
    PaymentEntry,
    get_payment_entry as _original_get_payment_entry,
    validate_inclusive_tax,
)

from erpnext.controllers.accounts_controller import validate_taxes_and_charges

from erpnext.accounts.general_ledger import (
    process_gl_map,
    make_gl_entries,
)

from erpnext.accounts.utils import (
    cancel_exchange_gain_loss_journal,
    get_account_currency,
)


class CustomPaymentEntry(PaymentEntry):

    @frappe.whitelist()
    def allocate_amount_to_references(self, paid_amount=None, received_amount=None, allocate_payment_amount=None, **kwargs):
        if paid_amount is None:
            paid_amount = flt(self.paid_amount)
        if received_amount is None:
            received_amount = flt(self.received_amount)
        return super().allocate_amount_to_references(paid_amount, received_amount, allocate_payment_amount)

    def get_valid_reference_doctypes(self) -> tuple:
        """Extiende los doctypes de referencia válidos para incluir ND."""
        valid: tuple = super().get_valid_reference_doctypes() or ()
        ve_doctypes: tuple = ("VE Sales Debit Note",)
        return valid + tuple(dt for dt in ve_doctypes if dt not in valid)

    def calculate_igtf_taxes(self) -> None:
        # Poblar la moneda de la compañía si viene vacía: este método corre antes
        # de que Frappe rellene los campos fetch_from, y sin ella el IGTF y la tasa
        # de cambio no se calculan (sobre todo en pagos creados a mano).
        if not self.default_company_currency and self.company:
            self.default_company_currency = frappe.get_cached_value(
                "Company", self.company, "default_currency"
            )

        # Si no es en divisas, o no hay cuenta de IGTF, no hacemos nada
        if not self.paid_on_currency or not self.default_company_currency:
            return


        if self.default_company_currency == self.paid_on_currency:
            # Si es la misma moneda, remover el IGTF de la tabla de impuestos
            self.set('taxes', [t for t in self.taxes or [] if t.charge_type != 'IGTF'])
            self.igtf_amount = 0.0
            self.total_with_igtf = 0.0
            return

        # Obtener tasa y cuenta si no están definidas
        if not self.igtf_account or not self.igtf_rate:
            igtf_field = 'purchase_igtf_account' if self.payment_type == 'Pay' else 'sales_igtf_account'
            self.igtf_account = frappe.db.get_value('Company', self.company, igtf_field)
            self.igtf_rate = flt(frappe.db.get_single_value('Venezuela Account Settings', 'igtf_rate'))

        if not self.igtf_account or not self.igtf_rate:
            return

        # Recalcular igtf_amount a partir del monto pagado si no está establecido
        paid_currency_amount = flt(self.paid_amount) / flt(self.exchange_rate) if flt(self.exchange_rate) else flt(self.paid_amount)
        if not self.igtf_amount:
            self.igtf_amount = flt(paid_currency_amount * self.igtf_rate / 100.0)

        self.total_with_igtf = paid_currency_amount + flt(self.igtf_amount)

        # El monto del impuesto en base local (VEF)
        tax_amount_vef = flt(self.igtf_amount) * flt(self.exchange_rate)

        # Buscar si ya existe la fila de IGTF en la tabla de impuestos
        igtf_row = next((t for t in self.taxes or [] if t.charge_type == 'IGTF'), None)
        if igtf_row:
            igtf_row.tax_amount = tax_amount_vef
            igtf_row.base_tax_amount = tax_amount_vef
            igtf_row.rate = self.igtf_rate
            igtf_row.account_head = self.igtf_account
        else:
            self.append('taxes', {
                'charge_type': 'IGTF',
                'description': 'IGTF',
                'add_deduct_tax': 'Add',
                'rate': self.igtf_rate,
                'tax_amount': tax_amount_vef,
                'base_tax_amount': tax_amount_vef,
                'account_head': self.igtf_account
            })

    # --- Retenciones de entes gubernamentales (timbre / ISAE / Responsabilidad Social) ---
    # Directiva contable 21-jul: TODAS se contabilizan como GASTO a la cuenta única
    # Company.government_withholding_account (no anticipo, no crédito). Se capturan al PAGO y
    # se reflejan como filas en Payment Entry.deductions (Debe gasto / Haber CxC del cliente).
    GOV_WITHHOLDING_MARKER = "Retención Gubernamental:"

    def calculate_government_withholdings(self) -> None:
        """Pobla las retenciones gubernamentales del cobro.

        Solo aplica a cobros (Receive) de clientes Government con retenciones configuradas en su
        ficha (Customer.government_withholdings). El monto sugerido = base × tarifa% es de solo
        lectura; el monto real del comprobante manda si se captura. Idempotente: preserva los
        comprobantes ya cargados y no duplica filas al re-guardar.
        """
        if self.docstatus == 2:
            return
        if self.payment_type != "Receive" or self.party_type != "Customer" or not self.party:
            self._clear_government_withholdings()
            return

        config_rows = self._get_customer_withholding_config()
        if not config_rows:
            self._clear_government_withholdings()
            return

        account = frappe.db.get_value("Company", self.company, "government_withholding_account")
        base_amount = self._government_withholding_base()

        # Preservar comprobante / monto real ya capturados (guard anti-borrado)
        prev_by_key = {
            (w.withholding_type, w.jurisdiction): w
            for w in (self.get("government_withholdings") or [])
        }

        new_rows = []
        for cfg in config_rows:
            rate, jurisdiction = self._resolve_withholding_rate(cfg, base_amount)
            if rate is None:
                continue
            suggested = flt(base_amount * flt(rate) / 100.0, 2)
            prev = prev_by_key.get((cfg["withholding_type"], jurisdiction))
            new_rows.append({
                "withholding_type": cfg["withholding_type"],
                "jurisdiction": jurisdiction,
                "rate": flt(rate),
                "base_amount": base_amount,
                "suggested_amount": suggested,
                "actual_amount": flt(prev.actual_amount) if prev else 0.0,
                "not_withheld": (cint(prev.get("not_withheld")) if prev else 0),
                "voucher_number": (prev.voucher_number if prev else None),
                "voucher_attachment": (prev.voucher_attachment if prev else None),
                "account": account,
            })

        self.set("government_withholdings", new_rows)
        self._sync_withholdings_to_deductions(account)

    def _get_customer_withholding_config(self) -> list:
        """Filas opt-in habilitadas del ente (solo si el cliente es Government)."""
        nature = frappe.db.get_value("Customer", self.party, "nature_of_the_taxpayer")
        if nature != "Government":
            return []
        return frappe.get_all(
            "VE Government Withholding",
            filters={"parent": self.party, "parenttype": "Customer", "enabled": 1},
            fields=["withholding_type", "state", "municipality"],
        )

    def _government_withholding_base(self) -> float:
        """Base bruta del cobro (lo que el ente liquida antes de retener), en moneda de la compañía.

        Se calcula desde campos disponibles ANTES de super().validate() (que todavía no pobló los
        base_*): la suma de lo asignado a facturas, o el monto pagado, por la tasa de la fuente.
        (v1 asume entes en VEF = moneda de la compañía, tasa 1.)
        """
        allocated = sum(flt(r.allocated_amount) for r in (self.get("references") or []))
        base = allocated or flt(self.paid_amount) or flt(self.received_amount)
        rate = flt(getattr(self, "source_exchange_rate", 0)) or flt(getattr(self, "exchange_rate", 0)) or 1.0
        return flt(base * rate, 2)

    def _resolve_withholding_rate(self, cfg: dict, base_amount: float):
        """(rate%, etiqueta_jurisdicción) para una fila de config; (None, _) si no aplica (skip)."""
        wtype = cfg.get("withholding_type")

        if wtype == "Timbre Fiscal":
            state = cfg.get("state")
            if not state:
                return None, ""
            state_label = frappe.db.get_value("VE State", state, "state") or state
            settings = frappe.get_cached_doc("Venezuela Account Settings")
            row = next((r for r in settings.stamp_tax_rates if r.state == state and r.enabled), None)
            if not row or not flt(row.rate):
                return None, state_label
            if flt(row.threshold) > 0 and base_amount < self._threshold_in_currency(row):
                return None, state_label
            return flt(row.rate), state_label

        if wtype == "ISAE":
            municipality = cfg.get("municipality")
            if not municipality:
                return None, ""
            muni_label = frappe.db.get_value("VE Municipality", municipality, "municipality") or municipality
            # La alícuota ISAE varía por municipio Y por rubro. Solo sugerimos un número si el
            # municipio tiene una única alícuota; si hay varias, dejamos 0 y el monto real del
            # comprobante manda (no arriesgamos una sugerencia errada). Fuente: verificación 21-jul.
            aliquots = [flt(a) for a in frappe.get_all(
                "VE Municipality Taxes", filters={"municipality": municipality}, pluck="aliquot"
            ) if flt(a)]
            if not aliquots:
                return None, muni_label
            distinct = sorted(set(aliquots))
            return (distinct[0] if len(distinct) == 1 else 0.0), muni_label

        if wtype == "Responsabilidad Social":
            rate = flt(frappe.db.get_single_value("Venezuela Account Settings", "responsibility_social_rate"))
            return (rate, "Nacional") if rate else (None, "Nacional")

        return None, ""

    def _threshold_in_currency(self, rate_row) -> float:
        """Umbral de la tarifa en moneda de la compañía (U.T. -> VEF; VEF directo).

        Fail-closed: si el umbral está en U.T. pero no hay una Unidad Tributaria activa, el valor
        sería 0 y el umbral colapsaría a 0 -> el timbre se aplicaría SIEMPRE (incluso bajo el mínimo
        legal exento). En vez de eso, se bloquea con un mensaje accionable para que se configure la U.T.
        """
        unit = (rate_row.threshold_unit or "").strip()
        threshold = flt(rate_row.threshold)
        if unit == "U.T.":
            ut_value = self._current_tax_unit_value()
            if ut_value <= 0:
                frappe.throw(_(
                    "No se puede evaluar el umbral del timbre fiscal ({0} U.T.): no hay una Unidad "
                    "Tributaria (Tax Unit) activa configurada. Configure el valor vigente de la U.T. "
                    "antes de registrar retenciones de timbre con umbral."
                ).format(threshold))
            return threshold * ut_value
        return threshold

    def _current_tax_unit_value(self) -> float:
        """Valor vigente de la Unidad Tributaria (Tax Unit) en VEF; 0 si no hay dato."""
        return flt(frappe.db.get_value(
            "Tax Unit", {"is_active": 1}, "value", order_by="effective_date desc"
        ))

    def _sync_withholdings_to_deductions(self, account: str) -> None:
        """Refleja las retenciones capturadas como filas en deductions (Debe gasto / Haber CxC).

        Reconstruye SOLO nuestras filas (marcadas por descripción); respeta otras deducciones.
        Fail-closed: si hay retención a aplicar y no hay cuenta configurada -> throw.
        """
        others = [
            d for d in (self.get("deductions") or [])
            if not (d.description or "").startswith(self.GOV_WITHHOLDING_MARKER)
        ]

        cost_center = self._withholding_cost_center()
        gov_deductions = []
        for w in self.get("government_withholdings") or []:
            # "No retenido": el ente no practicó ESTA retención en este cobro -> sin deducción.
            # (Distingue el 0 explícito del campo vacío, que sí cae al sugerido por el `or`.)
            if cint(w.get("not_withheld")):
                continue
            amount = flt(w.actual_amount) or flt(w.suggested_amount)
            if amount <= 0:
                continue
            # Cota superior: una retención no puede exceder la base bruta del cobro. Atrapa
            # un monto real mal tecleado (typo) que inflaría el gasto y sobre-acreditaría al cliente.
            base = flt(w.base_amount)
            if base > 0 and amount > base + 0.01:
                frappe.throw(_(
                    "La retención gubernamental ({0}) no puede exceder la base del cobro: "
                    "{1} > {2}."
                ).format(w.withholding_type, amount, base))
            if not account:
                frappe.throw(_(
                    "No se puede aplicar la retención gubernamental ({0}): falta configurar la "
                    "cuenta de Retenciones Gubernamentales en la compañía {1}."
                ).format(w.withholding_type, self.company))
            gov_deductions.append({
                "account": account,
                "cost_center": cost_center,
                "amount": amount,
                "description": "{0} {1} - {2}".format(
                    self.GOV_WITHHOLDING_MARKER, w.withholding_type, w.jurisdiction or ""
                ).strip(),
            })

        self.set("deductions", others + gov_deductions)

    def _withholding_cost_center(self) -> str:
        """Cost center de la retención = el de la SUCURSAL del pago (para atribución por sucursal
        en los reportes/dashboard, que agregan por branch). Cae a self.cost_center o al de la
        compañía si el pago no trae sucursal.
        """
        branch = getattr(self, "branch", None)
        if branch:
            branch_cc = frappe.db.get_value("VE Branch", branch, "cost_center")
            if branch_cc:
                return branch_cc
        return self.cost_center or frappe.get_cached_value("Company", self.company, "cost_center")

    def _clear_government_withholdings(self) -> None:
        """Quita nuestras filas de captura y de deductions (cuando ya no aplica)."""
        if self.get("government_withholdings"):
            self.set("government_withholdings", [])
        if self.get("deductions"):
            self.set("deductions", [
                d for d in self.deductions
                if not (d.description or "").startswith(self.GOV_WITHHOLDING_MARKER)
            ])

    def validate(self) -> None:
        self.calculate_igtf_taxes()
        self.calculate_government_withholdings()
        super().validate()

        self.validate_reference_no()
        self.validate_payment_mode_currency()

    def validate_payment_mode_currency(self) -> None:
        """La moneda del pago (paid_on_currency) debe coincidir con la del modo de
        pago (Mode of Payment.currency)."""
        if not self.mode_of_payment or not self.paid_on_currency:
            return

        mop_currency = frappe.get_cached_value(
            "Mode of Payment", self.mode_of_payment, "currency"
        )
        if mop_currency and mop_currency != self.paid_on_currency:
            frappe.throw(
                _(
                    "La moneda del pago ({0}) no coincide con la del modo de pago "
                    "{1} ({2}). Use un modo de pago en {0} o cambie la moneda del pago."
                ).format(
                    self.paid_on_currency,
                    frappe.bold(self.mode_of_payment),
                    mop_currency,
                )
            )


    def validate_transaction_reference(self) -> None:
        """Desactivada: no requerimos referencia obligatoria para cuentas bancarias."""
        return

    def on_submit(self) -> None:
        self.custom_clear_unallocated_reference_document_rows()

        super().on_submit()

        self._show_unallocated_amount_message()
        self.set_igtf_on_invoices()

    def before_cancel(self) -> None:
        self._block_cancel_if_invoice_sent_to_hka()
        super().before_cancel()

    def on_cancel(self) -> None:
        super().on_cancel()

        self.set_igtf_on_invoices(is_cancelled=True)

    def _block_cancel_if_invoice_sent_to_hka(self) -> None:
        """
        Bloquea la cancelación del Payment Entry si alguna de sus
        referencias es una Sales Invoice que ya fue enviada a la
        imprenta digital (TFHKA/HKA) siempre que este pago tenga IGTF.

        Regla de negocio: sin IGTF, cancelar el pago no altera lo ya
        reportado a HKA/SENIAT (el total de la factura legal sigue
        coincidiendo con el sistema; el cobro pasa a ser un tema de
        tesorería). Con IGTF, cancelar dejaría un monto de IGTF
        distinto al ya registrado por HKA, por lo que la reversión
        debe hacerse mediante Nota de Crédito.

        Excepción: Si la factura tiene una Nota de Crédito o de Débito
        aprobada (docstatus = 1), se permite la cancelación del pago.

        Discriminador: el campo remarks contiene JSON de respuesta HKA
        con la clave 'imprentaDigital'. Facturas con numeración interna
        (bill_no asignado manualmente) NO son bloqueadas.
        """

        has_igtf_in_payment = False
        if self.get("taxes"):
            for tax in self.get("taxes"):
                if tax.charge_type == "IGTF" and flt(tax.tax_amount) > 0:
                    has_igtf_in_payment = True
                    break

        if not has_igtf_in_payment:
            return

        si_refs: list[str] = [
            ref.reference_name for ref in self.get("references") or []
            if ref.reference_doctype == "Sales Invoice"
        ]
        if not si_refs:
            return

        hka_invoices: list[dict] = frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", si_refs]},
            fields=["name", "bill_no", "bill_control", "remarks"],
            ignore_permissions=True,
        )

        for si_data in hka_invoices:
            if not si_data.remarks or "imprentaDigital" not in si_data.remarks:
                continue
            
            # Si no tiene bill_no, significa que la factura quedó 'Por Emitir' a pesar de los remarks
            if not si_data.bill_no:
                continue

            # Nueva excepción: Permitir cancelación si existe una Nota de Crédito o de Débito aprobada
            # o si existe una factura de devolución estándar de ERPNext
            has_approved_note = (
                frappe.db.exists("VE Sales Credit Note", {"return_against": si_data.name, "docstatus": 1})
                or frappe.db.exists("VE Sales Debit Note", {"return_against": si_data.name, "docstatus": 1})
                or frappe.db.exists("Sales Invoice", {"return_against": si_data.name, "is_return": 1, "docstatus": 1})
            )
            if has_approved_note:
                continue


            si_link: str = frappe.utils.get_link_to_form(
                "Sales Invoice",
                si_data.name,
                label=si_data.bill_no or si_data.name,
            )
            frappe.throw(
                _(
                    "No se puede cancelar este pago porque la factura {0} "
                    "(Control: <b>{1}</b>) ya fue enviada a la imprenta "
                    "digital (TFHKA) y tiene IGTF asociado. Cancelar el pago dejaría "
                    "un monto de IGTF distinto al reportado al SENIAT.<br><br>"
                    "Para revertir, emita una <b>Nota de Crédito</b>."
                ).format(si_link, si_data.bill_control or "—"),
                title=_("Cancelación Bloqueada — Factura Digital"),
            )

    def _show_unallocated_amount_message(self) -> None:

        if flt(self.unallocated_amount) <= 0:
            return

        if self.payment_type == 'Pay':
            currency = self.paid_from_account_currency
            frappe.msgprint(
                _("Se ha aprobado un pago que excede el monto de la factura por {0}.").format(
                    frappe.utils.fmt_money(self.unallocated_amount, currency=currency)
                ),
                title=_("Advertencia de Sobrepago"),
                indicator='orange'
            )
        elif self.payment_type == 'Receive':
            currency = self.paid_to_account_currency
            frappe.msgprint(
                _("Se ha generado un anticipo por un monto de {0}.").format(
                    frappe.utils.fmt_money(self.unallocated_amount, currency=currency)
                )
            )

    def apply_taxes(self) -> None:

        self.initialize_taxes()
        self.determine_exclusive_rate()
        self.calculate_taxes()

    def set_tax_withholding(self) -> None:
        """
        Se inactiva la funcion nativa para que no se carguen retenciones
        que no sean ISLR ni IGTF
        """
        return

    def initialize_taxes(self) -> None:

        for tax in self.get("taxes"):
            validate_taxes_and_charges(tax)
            validate_inclusive_tax(tax, self)

            tax_fields = [
                "total",
                "tax_fraction_for_current_item",
                "grand_total_fraction_for_current_item"
            ]

            for fieldname in tax_fields:
                tax.set(fieldname, 0.0)

        self.paid_amount_after_tax = self.base_paid_amount

    @frappe.whitelist()
    def set_islr_concept(self, islr_concepts: list) -> str:

        party_type = "Supplier" if self.party_type == "Supplier" else "Company"
        party = self.party if self.party_type == "Supplier" else self.company
        account_field = "purchase_islr_account" if self.party_type == "Supplier" else "sales_islr_account"

        type_of_person = frappe.db.get_value(party_type,
                                             party,
                                             "type_of_person")

        account_head = frappe.db.get_value("Company",
                                           self.company,
                                           account_field)

        self.taxes = [tax for tax in self.taxes or []
                      if tax.charge_type != "ISLR"]

        concepts_by_tabulator = defaultdict(list)
        for concept in islr_concepts:
            concepts_by_tabulator[concept['concept_islr']].append(concept)

        references_map = {ref.reference_name: ref
                          for ref in self.references or []}

        for tabulator_name, concepts_in_group in concepts_by_tabulator.items():
            tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

            aliquot_info = next((aq for aq in tabulator.aliquot
                                 if aq.types_of_person == type_of_person
                                 and aq.aliquot > 0), None)

            if not aliquot_info:
                continue

            total_base_for_concept = sum(c['base_amount']
                                         for c in concepts_in_group)

            total_tax_base = (total_base_for_concept * aliquot_info.percentage_base) / 100
            total_tax_amount = ((total_tax_base * aliquot_info.aliquot) / 100) - aliquot_info.subtracting

            if total_tax_amount <= 0:
                continue

            self.append("taxes", {
                "charge_type": "ISLR",
                "code": tabulator.codigo,
                "add_deduct_tax": "Deduct",
                "rate": aliquot_info.aliquot,
                "account_head": account_head,
                "tax_amount": total_tax_amount,
                "is_tax_withholding_account": True,
                "description": tabulator.descripcion,
                "subtracting": aliquot_info.subtracting,
                "base_tax_amount": total_tax_amount,
            })

            for concept_detail in concepts_in_group:
                reference_doc = references_map.get(concept_detail['reference_name'])
                if not reference_doc:
                    continue

                individual_base = concept_detail['base_amount']
                individual_tax_base = (individual_base * aliquot_info.percentage_base) / 100
                individual_tax_amount = ((individual_tax_base * aliquot_info.aliquot) / 100) - aliquot_info.subtracting

                if individual_tax_amount <= 0:
                    continue

                reference_doc.islr_amount = individual_tax_amount
                reference_doc.islr_base_amount = individual_base
                reference_doc.islr_concept = tabulator_name

                if flt(reference_doc.allocated_amount) < flt(reference_doc.outstanding_amount):
                     reference_doc.allocated_amount = reference_doc.outstanding_amount
                elif flt(reference_doc.allocated_amount) == 0:
                    reference_doc.allocated_amount = reference_doc.outstanding_amount

        self.total_taxes_and_charges = sum([flt(t.tax_amount) for t in self.taxes])
        self.save()

        return self.name

    # ------------------------- CALCULO DE IMPUESTOS ------------------------- #

    def calculate_taxes(self) -> None:
        self.total_taxes_and_charges = 0.0
        self.base_total_taxes_and_charges = 0.0

        actual_tax_dict = dict(
            [
                [tax.idx, flt(tax.tax_amount, tax.precision("tax_amount"))]
                for tax in self.get("taxes")
                if tax.charge_type == "Actual"
            ]
        )

        for i, tax in enumerate(self.get("taxes")):
            current_tax_amount = self.get_current_tax_amount(tax)

            if tax.charge_type == "Actual":
                actual_tax_dict[tax.idx] -= current_tax_amount
                if i == len(self.get("taxes")) - 1:
                    current_tax_amount += actual_tax_dict[tax.idx]

            tax.tax_amount = current_tax_amount
            tax.base_tax_amount = current_tax_amount

            if tax.add_deduct_tax == "Deduct":
                current_tax_amount *= -1.0
            else:
                current_tax_amount *= 1.0

            if tax.charge_type == 'IGTF':
                amount_for_total = 0 # El IGTF no debe modificar el total del pago
            else:
                amount_for_total = current_tax_amount

            if i == 0:
                tax.total = flt(self.paid_amount_after_tax + amount_for_total, self.precision("total", tax))
            else:
                tax.total = flt(
                    self.get("taxes")[i - 1].total + amount_for_total, self.precision("total", tax)
                )

            tax.base_total = tax.total

            if self.payment_type == "Pay":
                if tax.currency != self.paid_to_account_currency:
                    self.total_taxes_and_charges += flt(current_tax_amount / self.target_exchange_rate)
                else:
                    self.total_taxes_and_charges += current_tax_amount
            elif self.payment_type == "Receive":
                if tax.currency != self.paid_from_account_currency:
                    self.total_taxes_and_charges += flt(current_tax_amount / self.source_exchange_rate)
                else:
                    self.total_taxes_and_charges += current_tax_amount

            self.base_total_taxes_and_charges += tax.base_tax_amount

        if self.get("taxes"):
            self.paid_amount_after_tax = self.get("taxes")[-1].base_total

    def get_current_tax_amount(self, tax) -> float:
        return tax.tax_amount

    def set_igtf_on_invoices(self, is_cancelled=False) -> None:

        igtf = next((tax for tax in self.taxes or []
                     if tax.charge_type == 'IGTF'), None)

        if not igtf or flt(igtf.tax_amount) <= 0:
            return

        for reference in self.references or []:

            if not reference.allocated_amount:
                continue

            reference_base_amount_igtf = flt(reference.allocated_amount)
            reference_total_igtf = \
                (reference_base_amount_igtf * self.igtf_rate) / 100

            invoice_igtf_data: dict = frappe.db.get_value(
                reference.reference_doctype,
                reference.reference_name,
                [
                    'total_igtf',
                    'base_amount_igtf'
                ],
                as_dict=True) or {}

            current_total_igtf = flt(invoice_igtf_data.get('total_igtf'))
            current_base_amount_igtf = flt(invoice_igtf_data.get('base_amount_igtf'))

            if is_cancelled:
                total_igtf = current_total_igtf - reference_total_igtf
                base_amount_igtf = current_base_amount_igtf - reference_base_amount_igtf
            else:
                total_igtf = current_total_igtf + reference_total_igtf
                base_amount_igtf = current_base_amount_igtf + reference_base_amount_igtf

            update_values = {
                'total_igtf': total_igtf,
                'base_amount_igtf': base_amount_igtf,
            }

            if frappe.get_meta(reference.reference_doctype).has_field('igtf_rate'):
                update_values['igtf_rate'] = self.igtf_rate

            frappe.db.set_value(reference.reference_doctype,
                                reference.reference_name,
                                update_values)

    def validate_reference_no(self) -> None:
        """
        Valida que el número de referencia tenga al menos 4 dígitos y sea numérico.
        """

        if frappe.db.has_column('Payment Entry', 'is_bdv_payment'):
            if self.is_bdv_payment == True:
                return

        if self.reference_no and not self.reference_no.isalnum():
            frappe.throw(_("El número de referencia debe contener solo letras y números."))

        if self.reference_no and len(self.reference_no) < 4:
            frappe.throw(_("El número de referencia debe tener al menos 4 caracteres."))

# ----------------------------- OVERRIDE METHODS ----------------------------- #

    def clear_unallocated_reference_document_rows(self) -> None:
        """
        Se desactiva esta funcion en el validate para que no se eliminen las
        lineas de referencia sin monto aplicado.
        Esto sucederá sólo en el on_submit en la funcion
        custom_clear_unallocated_reference_document_rows
        """
        return

    def custom_clear_unallocated_reference_document_rows(self) -> None:

        self.set("references",
        self.get("references", {"allocated_amount": ["not in", [0, None, ""]]}))

        frappe.db.sql(
            """delete from `tabPayment Entry Reference`
            where parent = %s and allocated_amount = 0""",
            self.name,
        )
# --------------------------- GESTIÓN DE ASIENTOS --------------------------- #

    def make_gl_entries(self, cancel=0, adv_adj=0) -> None:
        gl_entries = self.build_gl_map()
        gl_entries = process_gl_map(gl_entries, merge_entries=False)
        make_gl_entries(gl_entries, cancel=cancel, adv_adj=adv_adj)
        if cancel:
            cancel_exchange_gain_loss_journal(frappe._dict(doctype=self.doctype, name=self.name))
        else:
            self.make_exchange_gain_loss_journal()

        self.make_advance_gl_entries(cancel=cancel)

    def add_tax_gl_entries(self, gl_entries: list) -> None:

        for d in self.get("taxes"):

            if not d.tax_amount or d.charge_type in ["VAT Withholding", "ISLR"]:
                continue

            account_currency = get_account_currency(d.account_head)
            if account_currency != self.company_currency:
                frappe.throw(_("Currency for {0} must be {1}"
                               ).format(d.account_head, self.company_currency))

            if self.payment_type in ("Pay", "Internal Transfer"):
                dr_or_cr = "debit" if d.add_deduct_tax == "Add" else "credit"
                rev_dr_or_cr = "credit" if dr_or_cr == "debit" else "debit"
                against = self.party or self.paid_from
            elif self.payment_type == "Receive":
                dr_or_cr = "credit" if d.add_deduct_tax == "Add" else "debit"
                rev_dr_or_cr = "credit" if dr_or_cr == "debit" else "debit"
                against = self.party or self.paid_to

            payment_account = self.get_party_account_for_taxes()

            tax_amount = d.tax_amount
            base_tax_amount = d.base_tax_amount

            gl_entries.append(
                self.get_gl_dict(
                    {
                        "account": d.account_head,
                        "against": against,
                        dr_or_cr: tax_amount,
                        dr_or_cr + "_in_account_currency": base_tax_amount
                        if account_currency == self.company_currency
                        else d.tax_amount,
                        dr_or_cr + "_in_transaction_currency": base_tax_amount
                        / self.transaction_exchange_rate,
                        "cost_center": d.cost_center,
                        "post_net_value": True,
                    },
                    account_currency,
                    item=d))

            if not d.included_in_paid_amount:
                if get_account_currency(payment_account) != self.company_currency:
                    if self.payment_type == "Receive":
                        exchange_rate = self.target_exchange_rate
                    elif self.payment_type in ["Pay", "Internal Transfer"]:
                        exchange_rate = self.source_exchange_rate
                    base_tax_amount = flt((tax_amount / exchange_rate), self.precision("paid_amount"))

                if d.add_deduct_tax == 'Deduct':
                    party = self.party
                    party_type = self.party_type
                    payment_account = self.party_account
                else:
                    party = None
                    party_type = None

                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account": payment_account,
                            "against": against,
                            "party_type": party_type,
                            "party": party,
                            rev_dr_or_cr: tax_amount,
                            rev_dr_or_cr + "_in_account_currency": base_tax_amount
                            if account_currency == self.company_currency
                            else d.tax_amount,
                            rev_dr_or_cr + "_in_transaction_currency": base_tax_amount
                            / self.transaction_exchange_rate,
                            "cost_center": self.cost_center,
                            "post_net_value": True,
                        },
                        account_currency,
                        item=d))

    def add_party_gl_entries(self, gl_entries) -> None:
        if not self.party_account:
            return

        advance_payment_doctypes: _dict = frappe.get_hooks("advance_payment_doctypes")

        if self.payment_type == "Receive":
            against_account = self.paid_to
        else:
            against_account = self.paid_from

        party_account_type = \
            frappe.db.get_value("Party Type", self.party_type, "account_type")

        party_gl_dict: _dict = self.get_gl_dict(
            {
                "account": self.party_account,
                "party_type": self.party_type,
                "party": self.party,
                "against": against_account,
                "account_currency": self.party_account_currency,
                "cost_center": self.cost_center,
            },
            item=self,
        )

        for d in self.get("references"):
            # re-defining dr_or_cr for every reference in order to avoid the last value affecting calculation of reverse
            dr_or_cr = \
                "credit" if self.payment_type == "Receive" else "debit"

            cost_center = self.cost_center
            if d.reference_doctype == "Sales Invoice" and not cost_center:
                cost_center = \
                    frappe.db.get_value(d.reference_doctype,
                                        d.reference_name,
                                        "cost_center")

            gle = party_gl_dict.copy()

            allocated_amount_in_company_currency: float = \
                self.calculate_base_allocated_amount_for_reference(d)

            if (
                d.reference_doctype in ["Sales Invoice", "Purchase Invoice"]
                and d.allocated_amount < 0
                and (
                    (party_account_type == "Receivable" and self.payment_type == "Pay")
                    or (party_account_type == "Payable" and self.payment_type == "Receive")
                )
            ):
                # reversing dr_cr because because it will get reversed in gl processing due to negative amount
                dr_or_cr = \
                    "debit" if dr_or_cr == "credit" else "credit"

            gle.update(
                self.get_gl_dict(
                    {
                        "account": self.party_account,
                        "party_type": self.party_type,
                        "party": self.party,
                        "against": against_account,
                        "account_currency": self.party_account_currency,
                        "cost_center": cost_center,
                        dr_or_cr + "_in_account_currency": d.allocated_amount,
                        dr_or_cr: allocated_amount_in_company_currency,
                        dr_or_cr + "_in_transaction_currency": d.allocated_amount
                        if self.transaction_currency == self.party_account_currency
                        else allocated_amount_in_company_currency / self.transaction_exchange_rate,
                    },
                    item=self,
                )
            )

            if self.book_advance_payments_in_separate_party_account:
                if d.reference_doctype in advance_payment_doctypes:
                    # Upon reconciliation, whole ledger will be reposted. So, reference to SO/PO is fine
                    gle.update(
                        {
                            "against_voucher_type": d.reference_doctype,
                            "against_voucher": d.reference_name,
                        }
                    )
                else:
                    # Do not reference Invoices while Advance is in separate party account
                    gle.update({"against_voucher_type": self.doctype, "against_voucher": self.name})
            else:
                gle.update(
                    {
                        "against_voucher_type": d.reference_doctype,
                        "against_voucher": d.reference_name,
                    }
                )

            gl_entries.append(gle)
            self.add_party_withholding_gl_entries(
                d,
                'islr_amount',
                'ISLR',
                party_gl_dict,
                gl_entries)

            self.add_party_withholding_gl_entries(
                d,
                'vat_withholding_amount',
                'VAT Withholding',
                party_gl_dict,
                gl_entries)

        if self.unallocated_amount:
            dr_or_cr \
                = "credit" if self.payment_type == "Receive" else "debit"

            # La cuenta de anticipo se decide por TIPO DE ENTIDAD, no por direccion del
            # pago. Elegirla por payment_type coincide en los casos normales (Recibo de
            # cliente / Pago a proveedor) pero manda el REEMBOLSO a un cliente
            # (payment_type="Pay", party_type="Customer") a la cuenta de anticipo de
            # PROVEEDORES: el anticipo del cliente nunca baja y queda un activo espurio
            # a su nombre. Mismo criterio que ERPNext en accounts/party.py.
            accountfield: str = \
                "default_advance_received_account" if self.party_type == "Customer" \
                    else "default_advance_paid_account"

            account: str = frappe.db.get_value(
                "Company",
                self.company,
                accountfield
            )

            exchange_rate = self.get_exchange_rate()
            base_unallocated_amount = self.unallocated_amount * exchange_rate

            gle: _dict = party_gl_dict.copy()

            gle.update(
                self.get_gl_dict(
                    {
                        "account": account,
                        "party_type": self.party_type,
                        "party": self.party,
                        "against": against_account,
                        "account_currency": self.party_account_currency,
                        "cost_center": self.cost_center,
                        dr_or_cr + "_in_account_currency": self.unallocated_amount,
                        dr_or_cr + "_in_transaction_currency": self.unallocated_amount
                        if self.party_account_currency == self.transaction_currency
                        else base_unallocated_amount / self.transaction_exchange_rate,
                        dr_or_cr: base_unallocated_amount,
                    },
                    item=self,
                )
            )
            if self.book_advance_payments_in_separate_party_account:
                gle.update(
                    {
                        "against_voucher_type": "Payment Entry",
                        "against_voucher": self.name,
                    }
                )
            gl_entries.append(gle)

    def get_tax_account(self, charge_type) -> str | None:

        tax_account = None

        for tax in self.taxes:
            if tax.charge_type == charge_type:
                tax_account = tax.account_head
                break

        return tax_account

    def add_party_withholding_gl_entries(
        self,
        item: Document,
        amount_fieldname: str,
        charge_type: str,
        party_gl_dict: _dict,
        gl_entries: list
    ) -> None:

        tax_account = self.get_tax_account(charge_type)
        tax_amount = item.get(amount_fieldname)

        if not tax_account or not tax_amount:
            return

        party_account_type = \
            frappe.db.get_value("Party Type", self.party_type, "account_type")

        # re-defining dr_or_cr for every reference in order to avoid the last value affecting calculation of reverse
        dr_or_cr = \
            "credit" if self.payment_type == "Receive" else "debit"
        tax_dr_or_cr = \
            "debit" if self.payment_type == "Receive" else "credit"

        cost_center = self.cost_center
        if item.reference_doctype == "Sales Invoice" and not cost_center:
            cost_center = \
                frappe.db.get_value(item.reference_doctype,
                                    item.reference_name,
                                    "cost_center")

        gle = party_gl_dict.copy()

        if (
            item.reference_doctype in ["Sales Invoice", "Purchase Invoice"]
            and item.allocated_amount < 0
            and (
                (party_account_type == "Receivable" and self.payment_type == "Pay")
                or (party_account_type == "Payable" and self.payment_type == "Receive")
            )
        ):
            # reversing dr_cr because because it will get reversed in gl processing due to negative amount
            dr_or_cr = \
                "debit" if dr_or_cr == "credit" else "credit"
            tax_dr_or_cr = \
                "credit" if tax_dr_or_cr == "debit" else "debit"
        # Party GL
        gle.update(
            self.get_gl_dict(
                {
                    "account": self.party_account,
                    "party_type": self.party_type,
                    "party": self.party,
                    "against_voucher_type": item.reference_doctype,
                    "against_voucher": item.reference_name,
                    "against": tax_account,
                    "account_currency": self.party_account_currency,
                    "cost_center": cost_center,
                    dr_or_cr + "_in_account_currency": tax_amount,
                    dr_or_cr: tax_amount,
                    dr_or_cr + "_in_transaction_currency": tax_amount
                    if self.transaction_currency == self.party_account_currency
                    else tax_amount / self.transaction_exchange_rate,
                },
                item=self,
            )
        )

        gl_entries.append(
            self.get_gl_dict(
                {
                    "account": tax_account,
                    "against": self.party_account,
                    tax_dr_or_cr: tax_amount,
                    tax_dr_or_cr + "_in_account_currency": tax_amount
                    if self.party_account_currency == self.company_currency
                    else tax_amount,
                    tax_dr_or_cr + "_in_transaction_currency": tax_amount
                    / self.transaction_exchange_rate,
                    "cost_center": cost_center,
                    "post_net_value": True,
                },
                self.party_account_currency,
                item=item))

        gl_entries.append(gle)

    def set_transaction_currency_and_rate(self) -> None:
        self.transaction_currency = self.paid_on_currency
        self.transaction_exchange_rate = self.exchange_rate


@frappe.whitelist()
def get_payment_entry(
    dt,
    dn,
    party_amount=None,
    bank_account=None,
    bank_amount=None,
    party_type=None,
    payment_type=None,
    reference_date=None,
    ignore_permissions=False,
    created_from_payment_request=False,
) -> PaymentEntry:

    # ERPNext no reconoce DocTypes custom en set_party_type() ni
    # set_payment_type(). Para la ND forzamos los valores correctos.
    if dt == "VE Sales Debit Note":
        party_type = party_type or "Customer"
        payment_type = payment_type or "Receive"

    payment_entry: PaymentEntry = _original_get_payment_entry(
        dt,
        dn,
        party_amount=party_amount,
        bank_account=bank_account,
        bank_amount=bank_amount,
        party_type=party_type,
        payment_type=payment_type,
        reference_date=reference_date,
        ignore_permissions=ignore_permissions,
        created_from_payment_request=created_from_payment_request,
    )

    # ERPNext usa get_party_account() genérica para DocTypes desconocidos,
    # lo cual podría devolver una cuenta AR distinta a la de la ND.
    if dt == "VE Sales Debit Note":
        nd_doc = frappe.get_cached_doc("VE Sales Debit Note", dn)
        if nd_doc.debit_to and payment_entry.paid_from != nd_doc.debit_to:
            payment_entry.paid_from = nd_doc.debit_to

    igtf_rate: float = frappe.db.get_single_value(
      "Venezuela Account Settings",
      "igtf_rate"
    )

    igtf_account_field: str = 'sales_igtf_account' \
        if payment_entry.party_type == "Customer" \
        else "purchase_igtf_account"

    company_data: _dict = frappe.db.get_value(
      "Company",
      payment_entry.company,
      [igtf_account_field, 'default_currency'],
      as_dict=True)

    doc = frappe.get_doc(dt, dn)

    _set_payment_entry_mode_of_payment(doc, payment_entry)

    payment_entry.paid_currency_amount = payment_entry.paid_amount

    payment_entry.igtf_rate = igtf_rate
    payment_entry.igtf_account = company_data.get(igtf_account_field)

    payment_entry.default_company_currency = company_data.default_currency
    payment_entry.paid_on_currency = doc.get('currency', company_data.default_currency)

    payment_entry.references[0].base_total = doc.get("base_total")
    payment_entry.references[0].bill_no = doc.get("bill_no") \
            or doc.get("credit_note_no") \
            or doc.get("debit_note_no")

    payment_entry.apply_taxes()

    return payment_entry


def _set_payment_entry_mode_of_payment(doc: Document, payment_entry: PaymentEntry) -> None:
    """
    Asigna el modo de pago predeterminado de la sucursal al documento de pago.
    """

    branch = doc.get("branch")

    if not branch:
        return

    payment_entry.branch = branch

    branch = frappe.get_cached_doc("VE Branch", payment_entry.branch)
    default_payment_mode: _dict = branch.get_default_payment_mode()

    if not default_payment_mode:
        return

    payment_entry.mode_of_payment = default_payment_mode.mode_of_payment
    if not default_payment_mode.account:
        return

    if payment_entry.payment_type == "Receive":
        payment_entry.paid_to = default_payment_mode.account
    else:
        payment_entry.paid_from = default_payment_mode.account


@frappe.whitelist()
def get_outstanding_reference_documents(args, validate: bool = False) -> list:
    """
    Filtra los documentos de referencia pendientes para incluir solo facturas de venta y compra.

    Esta función sobreescribe el método original de ERPNext. Modifica los argumentos
    de la solicitud para asegurar que se obtengan las facturas pendientes y luego
    filtra la lista resultante para excluir cualquier tipo de documento que no sea
    'Sales Invoice' o 'Purchase Invoice'.
    """
    if isinstance(args, str):
        args = json.loads(args)

    args['get_orders_to_be_billed'] = False

    args['get_outstanding_invoices'] = True

    all_outstanding_docs = original_get_outstanding_reference_documents(args, validate)

    ALLOWED_DOCTYPES = ("Sales Invoice", "Purchase Invoice")
    filtered_docs = [doc for doc in all_outstanding_docs if
                     doc.get("voucher_type") in ALLOWED_DOCTYPES]

    for doc in filtered_docs:

        if not doc.get("voucher_no"):
            continue

        base_total = frappe.db.get_value(
            doc.get("voucher_type"),
            doc.get("voucher_no"),
            "base_total"
        )

        doc["base_total"] = base_total or 0.0

    return filtered_docs


@frappe.whitelist()
def get_branch_payment_mode_account(branch: str, mode_of_payment: str) -> str | None:
    """Obtiene la cuenta configurada para un modo de pago en una sucursal."""
    if not branch or not mode_of_payment:
        return None

    account = frappe.db.get_value("VE Branch Payment Modes", {
        "parent": branch,
        "mode_of_payment": mode_of_payment
    }, "account")

    return account


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_branch_payment_modes(doctype, txt, searchfield, start, page_len, filters):
    if isinstance(filters, str):
        filters = json.loads(filters)
    elif not filters:
        filters = {}

    """Obtiene los modos de pago (y si aplican IGTF) configurados para una sucursal."""
    branch = filters.get("branch")
    if not branch:
        # Retornar todos los modos de pago si no hay sucursal
        return frappe.db.sql("""
            SELECT name, is_igtf_applicable
            FROM `tabMode of Payment`
            WHERE name LIKE %(txt)s
            AND enabled = 1
            ORDER BY name
            LIMIT %(start)s, %(page_len)s
        """, {
            "txt": "%" + txt + "%",
            "start": int(start),
            "page_len": int(page_len)
        })

    # Obtener modos de pago de la tabla hija de la sucursal
    return frappe.db.sql("""
        SELECT 
            vbpm.mode_of_payment, mop.is_igtf_applicable
        FROM `tabVE Branch Payment Modes` vbpm
        INNER JOIN `tabMode of Payment` mop ON mop.name = vbpm.mode_of_payment
        WHERE vbpm.parent = %(branch)s
        AND vbpm.mode_of_payment LIKE %(txt)s
        AND mop.enabled = 1
        ORDER BY vbpm.mode_of_payment
        LIMIT %(start)s, %(page_len)s
    """, {
        "branch": branch,
        "txt": "%" + txt + "%",
        "start": int(start),
        "page_len": int(page_len)
    })
