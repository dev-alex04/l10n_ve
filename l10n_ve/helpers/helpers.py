# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
    from frappe.model.document import Document


def set_ve_branch(doc: "Document", method: str) -> None:
    """Asigna la sucursal VE Branch al documento y establece el centro de costos correspondiente."""

    try:
        if not frappe.get_meta(doc.doctype).get_field("branch"):
            return

        if not doc.branch and doc.doctype == "Payment Entry":
            for ref in (doc.get("references") or []):
                if ref.reference_doctype == "Sales Invoice" and ref.reference_name:
                    si_branch = frappe.db.get_value("Sales Invoice", ref.reference_name, "branch")
                    if si_branch:
                        doc.branch = si_branch
                        break

        if not doc.branch:
            branches = frappe.get_all("VE Branch Users", filters={
                "user": frappe.session.user,
                "parenttype": "VE Branch"
            }, fields=["parent"])

            unique_branches = list(set([b.parent for b in branches if b.parent]))

            if len(unique_branches) == 1:
                doc.branch = unique_branches[0]

            elif len(unique_branches) > 1:
                branches_list = ", ".join([frappe.bold(frappe.utils.escape_html(b)) for b in unique_branches])

                frappe.throw(
                    frappe._("El usuario tiene múltiples sucursales asignadas: {0}. Por favor seleccione una.").format(branches_list),
                    title=frappe._("Selección de Sucursal")
                )

        _set_cost_center_from_branch(doc)

    except Exception as e:
        if isinstance(e, frappe.exceptions.ValidationError):
            raise

        frappe.log_error(
            title="Error al asignar sucursal",
            message=f"Error al asignar sucursal: {str(e)} \n{frappe.get_traceback()}"
        )


def _payment_entry_invoice_cost_centers(doc: "Document") -> set:
    """Centros de costo de las Sales Invoice que este cobro salda.

    Una referencia sin factura localizable, o cuya factura no trae centro de
    costo, mete ``None`` en el conjunto: no se completa a medias con las que sí
    lo traen. Si el resultado tiene más de un valor -- incluido ``None`` -- el
    llamador no puede preferir la factura y cae a la sucursal.

    Espejo de ``domina_isp.overrides.payment_entry._resolve_cost_center``, que ya
    aplica este mismo criterio en la conciliación (``on_update_after_submit``).
    No se importa desde ahí a propósito: l10n_ve es la app base y domina_isp
    depende de ella, no al revés.
    """
    names = [
        ref.reference_name
        for ref in (doc.get("references") or [])
        if ref.reference_doctype == "Sales Invoice" and ref.reference_name
    ]
    if not names:
        return set()

    rows = frappe.get_all(
        "Sales Invoice",
        filters={"name": ["in", names]},
        fields=["name", "cost_center"],
    )
    found = {r.name: r.cost_center for r in rows}
    return {found.get(name) or None for name in names}


def _set_cost_center_from_branch(doc: "Document") -> None:
    """Establece el centro de costos del documento.

    Para casi todos los doctypes sale de la sucursal (``doc.branch``), como
    siempre. Payment Entry es la excepción: cuando salda facturas de venta,
    prefiere el centro de costo de esas facturas -- pero SOLO si todas
    coinciden en uno -- y recién si no hay acuerdo (o no hay facturas) cae a la
    sucursal del cobro.

    El orden importa y no es cosmético. Un cobro se puede cargar en una
    sucursal y saldar una factura de otra -- medido en producción, 8 casos
    limpios donde las facturas SÍ coinciden entre ellas mientras la sucursal
    del cobro dice otra cosa -- y ahí derivar de la sucursal escribe un centro
    de costo que ninguna factura tiene. La factura, en cambio, no falla nunca:
    de las facturas emitidas con sucursal y centro de costo, ninguna trae uno
    distinto al de su propia sucursal.

    Es la misma regla que ``domina_isp.overrides.payment_entry._resolve_cost_center``
    ya usa en la conciliación; acá se aplica también en la emisión, que es
    donde faltaba (``set_ve_branch`` corre en el ``before_submit`` de Payment
    Entry, antes que cualquier hook de domina_isp).

    Cuando las facturas NO coinciden entre ellas, caer a la sucursal no es
    mejor -- reparte un centro de costo entre varias facturas y ninguno es
    correcto para todas -- pero es un valor definido y auditable, y vacío es
    peor: un cobro sin centro de costo es invisible para el filtro de permisos
    de sucursal (``branch IN (...)``, que ``NULL`` no casa contra ninguna
    lista).

    Aplica el cost_center a nivel de documento, a cada item de la tabla hija
    `items`, `taxes`, `references` y `deductions`.
    """
    if not frappe.get_meta(doc.doctype).get_field("cost_center"):
        return

    branch_cost_center: str | None = (
        frappe.get_cached_value("VE Branch", doc.branch, "cost_center")
        if doc.branch else None
    )

    cost_center: str | None = branch_cost_center

    if doc.doctype == "Payment Entry":
        invoice_cost_centers = _payment_entry_invoice_cost_centers(doc)
        if len(invoice_cost_centers) == 1 and None not in invoice_cost_centers:
            cost_center = invoice_cost_centers.pop()

    if not cost_center:
        return

    doc.cost_center = cost_center

    child_tables = [
        "items",
        "taxes",
        "references",
        "deductions"
    ]

    for table in child_tables:
        for item in (doc.get(table) or []):
            if not hasattr(item, "cost_center"):
                continue
            item.cost_center = cost_center
