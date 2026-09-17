"""Utilidades para el cálculo de retención ISLR (Venezuela).

Fuente única de verdad para resolver la alícuota del tabulador ISLR
y calcular el monto de retención. Consumido por:
- l10n_ve/controllers/taxes_mixin.py  (inyección de fila ISLR en factura)
- domina_isp/.../isp_payment_entry.py (cálculo de ISLR en ISP Payment Entry)
- domina_isp/.../index.py             (portal: tasa ISLR para display)
"""
import frappe
from frappe import _
from frappe.utils import flt


def get_islr_aliquot(
    customer: str, company: str
) -> tuple | None:
    """Resuelve el tabulador ISLR y la alícuota aplicable.

    Busca el tabulador asignado al cliente y filtra la alícuota
    según el type_of_person de la compañía.

    Args:
        customer: Nombre del Customer.
        company: Nombre de la Company.

    Returns:
        (aliquot_row, tabulator_doc) o None si no aplica ISLR.
    """
    tabulator_name: str | None = frappe.get_cached_value(
        "Customer", customer, "tabulator_islr"
    )
    if not tabulator_name:
        return None

    tabulator = frappe.get_cached_doc("Tabulator ISLR", tabulator_name)
    if not tabulator.aliquot:
        return None

    type_of_person: str | None = frappe.get_cached_value(
        "Company", company, "type_of_person"
    )
    if not type_of_person:
        return None

    aliquot_info = next(
        (aq for aq in tabulator.aliquot
         if aq.types_of_person == type_of_person and aq.aliquot > 0),
        None
    )
    if not aliquot_info:
        return None

    return aliquot_info, tabulator


def resolve_purchase_islr_aliquot(tabulator, type_of_person: str):
    """Elige la alícuota del concepto que corresponde aplicarle a un proveedor.

    Busca primero la del tipo de persona del proveedor. Si el concepto no la
    tiene y ofrece una sola alícuota, aplica esa: es el caso de las sociedades
    de personas —firmas civiles de abogados o contadores, con RIF jurídico, que
    por el Decreto 1808 (artículo 9, parágrafo cuarto) se retienen con las tasas
    de las personas naturales—. Se acordó con el equipo contable el 31-jul-2026,
    y es la razón de que el buscador de conceptos no filtre por tipo de persona.

    Lo que NO hace es tomar "la primera disponible" cuando el concepto ofrece
    varias y ninguna es la del proveedor: esa cifra termina declarada ante el
    SENIAT, y equivocarse en silencio sale mucho más caro que fallar a la vista.
    Hoy sólo el concepto 077 está en ese caso (1 % natural y 5 % jurídica).

    Args:
        tabulator: Documento Tabulator ISLR.
        type_of_person: Tipo de persona del proveedor.

    Returns:
        La fila de Tabulator ISLR Aliquots que se debe aplicar.
    """
    usable: list = [row for row in (tabulator.aliquot or []) if flt(row.aliquot) > 0]

    if not usable:
        frappe.throw(
            _("El concepto de ISLR '{0}' no tiene ninguna alícuota con tasa "
              "mayor a cero.").format(tabulator.name)
        )

    own_rate = next(
        (row for row in usable if row.types_of_person == type_of_person), None
    )
    if own_rate:
        return own_rate

    if len(usable) == 1:
        return usable[0]

    person_label: str = _(type_of_person) if type_of_person else _("No configurado")
    offered: str = ", ".join(
        f"{_(row.types_of_person)} {flt(row.aliquot)}%" for row in usable
    )
    frappe.throw(
        _("El concepto de ISLR '{0}' no tiene alícuota para un proveedor "
          "'{1}', y ofrece más de una: {2}. Elija el concepto que "
          "corresponda.").format(tabulator.name, person_label, offered)
    )


def describe_purchase_islr_row(tabulator, aliquot_row, type_of_person: str = "") -> str:
    """Arma la descripción de la fila de ISLR de una factura de compra.

    Cuando la alícuota aplicada no es la del tipo de persona del proveedor, lo
    deja dicho en el propio documento: quien audite el Libro de Compras o el
    comprobante meses después ve un proveedor jurídico retenido con tarifa de
    natural y necesita saber que fue deliberado, no un error de carga.
    """
    description: str = (
        f"ISLR {tabulator.codigo} {tabulator.descripcion}"
        f" ({flt(aliquot_row.aliquot)}%)"
    )

    if type_of_person and aliquot_row.types_of_person != type_of_person:
        description += " - " + _("alícuota de {0} aplicada a un proveedor {1}").format(
            _(aliquot_row.types_of_person), _(type_of_person)
        )

    return description


def calculate_islr_amount(
    total: float, aliquot_info, conversion_rate: float = 1.0
) -> float:
    """Calcula el monto ISLR basándose en la alícuota del tabulador.

    Fórmula fiscal venezolana:
        base = total × (percentage_base / 100)
        sustraendo_ref = sustraendo_bs / conversion_rate
        islr = (base × aliquot / 100) − sustraendo_ref

    Args:
        total: Monto base de la factura (net_total en moneda de referencia).
        aliquot_info: Fila de Tabulator ISLR Aliquots con percentage_base,
                      aliquot y subtracting (en Bs).
        conversion_rate: Tasa de cambio para convertir el sustraendo de Bs
                         a moneda de referencia.

    Returns:
        Monto ISLR redondeado a 2 decimales, mínimo 0.
    """
    tax_base: float = flt(flt(total) * flt(aliquot_info.percentage_base) / 100, 2)
    sustraendo_ref: float = flt(aliquot_info.subtracting / conversion_rate, 2) if conversion_rate > 0 else 0.0
    islr: float = (tax_base * flt(aliquot_info.aliquot) / 100) - sustraendo_ref
    return flt(max(islr, 0), 2)
