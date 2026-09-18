# Copyright (c) 2026, Galanet Solution and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from l10n_ve.numbering import take_next_number


class VEDigitalBillingSeries(Document):

    def validate(self) -> None:
        self._validate_no_duplicate_branches_in_active_series()

    # --- Numeración --------------------------------------------------------------
    # Misma lógica que la empresa (`l10n_ve.numbering`): lo único que cambia es de dónde
    # sale el contador. La serie no tiene campo de formato, así que el número se imprime
    # pelado, como hasta ahora; el día que haga falta, se agrega el campo y se pasa acá.
    #
    # Solo se usan en modo de operación Interno: en Tercero el número lo asigna HKA.

    def take_invoice_number(self, is_free=None) -> str:
        return take_next_number(
            "VE Digital Billing Series", self.name, "invoice_number_correlative", is_free=is_free
        )

    def take_credit_note_number(self, is_free=None) -> str:
        return take_next_number(
            "VE Digital Billing Series", self.name, "credit_note_number_correlative", is_free=is_free
        )

    def take_debit_note_number(self, is_free=None) -> str:
        return take_next_number(
            "VE Digital Billing Series", self.name, "debit_note_number_correlative", is_free=is_free
        )

    def _validate_no_duplicate_branches_in_active_series(self) -> None:
        """Valida que ninguna sucursal esté asignada a otra serie activa."""
        if self.status != "Active":
            return

        branches: list[str] = [
            row.branch for row in (self.get("branches") or []) if row.branch
        ]
        if not branches:
            return

        placeholders: str = ", ".join(["%s"] * len(branches))
        params: list = branches + [self.company, self.name]

        conflicts: list[dict] = frappe.db.sql(f"""
            SELECT
                child.branch,
                child.parent AS series_name
            FROM `tabVE Digital Billing Series Branch` child
            INNER JOIN `tabVE Digital Billing Series` serie
                ON serie.name = child.parent
            WHERE child.branch IN ({placeholders})
              AND serie.company = %s
              AND serie.status = 'Active'
              AND serie.name != %s
        """, params, as_dict=True)

        if conflicts:
            details: list[str] = [
                f"• {c['branch']} → ya asignada en serie {c['series_name']}"
                for c in conflicts
            ]
            frappe.throw(
                "Las siguientes sucursales ya están asignadas a otra serie activa "
                f"de la misma empresa:<br><br>{'<br>'.join(details)}",
                title="Sucursales Duplicadas",
            )
