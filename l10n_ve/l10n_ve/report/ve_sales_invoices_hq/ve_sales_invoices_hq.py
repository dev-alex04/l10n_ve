# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Reporte HQ de facturas de venta (consolidado para casa matriz).

Wrapper del Libro de Ventas (``sales_book``): reusa su cálculo fiscal íntegro
(base imponible, IVA por alícuota, notas de crédito, serie) y le añade lo que
contabilidad necesita para conciliar, sin tocar el libro que usa para declarar:

  1. **Documento fiscal**: serie y número concatenados (``MIR-01-4779``), que
     hoy se pegan a mano porque el libro los trae en columnas separadas.
  2. **Sucursal Principal**: el ancestro de la sucursal que cuelga directo de la
     raíz del árbol (``ARMANDO`` -> ``GUARENAS`` -> **``MIR-01``**). Es el nivel
     al que consolida casa matriz, sin perder la sucursal operativa.
  3. **Municipio**: derivado de la sucursal (``VE Branch.municipality``).
  4. **Rollup padre-hijo**: al filtrar por una sucursal GRUPO se incluyen sus
     descendientes. El libro filtra por un único valor (``AND siv.branch = %s``),
     así que aquí se pide sin ese filtro y se recorta por el subárbol del nested
     set (``lft``/``rgt``).
  5. **Acceso restringido** por el rol ``VE Sales Book HQ``.

REGLA DE ORO: la única fuente de verdad fiscal es ``sales_book``. Aquí NO se
reimplementa ningún cálculo — se reusan sus funciones tal cual
(``get_columns``, ``get_sales_data``, ``get_total_row``, ``get_report_summary``).
Se usan las piezas y no ``sales_book.execute()`` porque el rollup obliga a
recortar filas, y los totales deben recalcularse **sobre las filas recortadas**
con las mismas funciones del libro; ``execute()`` devuelve las filas del período
y las de ajuste ya concatenadas, sin forma de distinguirlas.

NOTA — ``prepared_report`` va en 0 a propósito: l10n_ve **suprime** el sistema
de Prepared Report en toda la app (``hooks.py`` override de
``frappe.desk.query_report.run`` -> ``patches/frappe/report_session_patch.py``
fuerza ``ignore_prepared_report=True``; además el cron
``tasks.reset_all_prepared_reports`` limpia el flag cada 15 min). Activarlo aquí
sería inerte. Medido: ~2s para 10.712 filas en modo interactivo.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from l10n_ve.l10n_ve.report.sales_book.sales_book import (
    get_columns as _sales_book_columns,
    get_report_summary as _sales_book_report_summary,
    get_sales_data as _sales_book_data,
    get_total_row as _sales_book_total_row,
)

BRANCH_DOCTYPE: str = "VE Branch"
MUNICIPALITY_DOCTYPE: str = "VE Municipality"


def get_hq_data(filters=None) -> dict:
    """Núcleo del reporte: resuelve los filtros HQ y devuelve datos y totales.

    Es el ÚNICO lugar donde se aplica el filtrado propio del HQ (rollup de
    sucursal y sucursal principal). Lo consumen ``execute`` (pantalla) y las
    exportaciones a Excel y PDF: si cada una lo replicara, tarde o temprano una
    quedaría desfasada y entregaría un total distinto al de la pantalla.

    Devuelve ``main_data`` y ``adjustment_data`` POR SEPARADO a propósito: los
    totales del libro se calculan solo con las del período, así que quien
    necesite porcentajes (el PDF) debe usar ``main_data`` como denominador o no
    cuadrarían con los indicadores.
    """
    filters = dict(filters or {})
    _validate_filters(filters)

    # Rollup: si la sucursal elegida tiene descendientes, el libro no puede
    # filtrarlas (solo acepta un valor), así que se quita el filtro y se recorta
    # después por el subárbol.
    branch_filter: str = filters.get("branch") or ""
    main_branch_filter: str = filters.get("main_branch") or ""
    # El libro no conoce este filtro: se resuelve aquí.
    filters.pop("main_branch", None)

    subtree: set | None = _get_branch_subtree(branch_filter)
    if subtree:
        filters.pop("branch", None)

    # Sucursales admitidas. Filtrar por sucursal principal X equivale a su
    # subárbol, porque X cuelga de la raíz: todo lo que consolida en X está
    # debajo de X. Si además hay filtro de sucursal, se intersectan.
    allowed: set | None = subtree
    if main_branch_filter:
        main_allowed: set = (
            _get_branch_subtree(main_branch_filter) or {main_branch_filter}
        )
        allowed = main_allowed if allowed is None else (allowed & main_allowed)

    columns: list[dict] = _sales_book_columns()
    main_data, adjustment_data = _sales_book_data(filters)

    if allowed is not None:
        main_data = [r for r in main_data if r.get("branch") in allowed]
        adjustment_data = [r for r in adjustment_data if r.get("branch") in allowed]

    _add_hq_columns(columns, main_data + adjustment_data)

    # Totales con las MISMAS funciones del libro y sobre las filas ya recortadas.
    # Igual que el libro, se calculan solo con main_data (excluye los ajustes de
    # períodos anteriores).
    report_summary: list[dict] = _sales_book_report_summary(
        _sales_book_total_row(main_data)
    )

    return {
        "columns": columns,
        "main_data": main_data,
        "adjustment_data": adjustment_data,
        "report_summary": report_summary,
        "branch": branch_filter,
        "main_branch": main_branch_filter,
        "subtree": subtree,
    }


def execute(filters=None):
    hq = get_hq_data(filters)

    data: list[dict] = hq["main_data"] + hq["adjustment_data"]
    for i, row in enumerate(data):
        row["sequence_number"] = i + 1

    # 3er valor = 'message': Frappe lo pinta entre los filtros y las tarjetas de
    # totales (query_report.js -> show_status / $status).
    message: str = _build_report_message(
        hq["branch"], hq["subtree"], hq["main_branch"]
    )

    return hq["columns"], data, message, None, hq["report_summary"]


def _build_report_message(branch: str, subtree: set | None, main_branch: str = "") -> str:
    """Descripción que se muestra sobre el reporte (bajo los filtros).

    Explica de dónde salen los números y hace visible el rollup: sin esto, al
    filtrar por una sucursal con dependencias el usuario ve más filas de las que
    espera y no sabe por qué.
    """
    lineas: list[str] = [
        "<b>{0}</b> {1}".format(
            _("Facturas de Venta HQ:"),
            _(
                "consolidado para casa matriz. Reusa el cálculo del Libro de "
                "Ventas, así que los totales cuadran con lo declarado."
            ),
        ),
        "• <b>{0}</b> {1} <code>MIR-01-4779</code>.".format(
            _("Documento Fiscal:"), _("serie y número juntos, por ejemplo")
        ),
        "• <b>{0}</b> {1}".format(
            _("Sucursal:"),
            _(
                "al elegir una sucursal con dependencias se incluyen "
                "automáticamente las sucursales hijas."
            ),
        ),
        "• {0}".format(
            _(
                "Solo incluye documentos ya certificados por la imprenta "
                "digital, igual que el Libro de Ventas."
            )
        ),
    ]

    if subtree:
        dependientes: list[str] = sorted(n for n in subtree if n != branch)
        lineas.append(
            "<b>{0}</b> {1} <b>{2}</b> {3} {4} ({5}).".format(
                "→",
                _("Mostrando"),
                branch,
                _("y sus"),
                _("{0} sucursales dependientes").format(len(dependientes)),
                ", ".join(dependientes),
            )
        )

    if main_branch:
        lineas.append(
            "<b>→</b> {0} <b>{1}</b>.".format(
                _("Consolidando por sucursal principal"), main_branch
            )
        )

    return "<br>".join(lineas)


def _validate_filters(filters: dict) -> None:
    """Mismas validaciones de entrada que ``sales_book.execute``."""
    if not filters.get("company"):
        frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))
    if not filters.get("from_date"):
        frappe.throw(_("Debe ingresar la Fecha Desde."))
    if not filters.get("to_date"):
        frappe.throw(_("Debe ingresar la Fecha Hasta."))
    if getdate(filters["from_date"]) > getdate(filters["to_date"]):
        frappe.throw(_("La Fecha Desde no puede ser posterior a la Fecha Hasta."))


def _get_branch_subtree(branch: str | None) -> set | None:
    """Nombres de la sucursal y sus descendientes, o ``None`` si no hay rollup.

    Devuelve ``None`` cuando no hay filtro de sucursal o cuando la elegida es
    una hoja: en ese caso conviene dejar que el libro filtre en SQL (usa el
    índice ``branch_index``) en vez de traer todo y recortar en memoria.
    """
    if not branch:
        return None

    node = frappe.db.get_value(BRANCH_DOCTYPE, branch, ["lft", "rgt"], as_dict=True)
    if not node or node.lft is None or node.rgt is None:
        return None

    names: list[str] = frappe.get_all(
        BRANCH_DOCTYPE,
        filters={"lft": [">=", node.lft], "rgt": ["<=", node.rgt]},
        pluck="name",
    )
    return set(names) if len(names) > 1 else None


def _add_hq_columns(columns: list[dict], data: list[dict]) -> None:
    """Agrega las columnas 'Documento Fiscal' y 'Municipio' (in place)."""
    municipality_by_branch: dict = _get_municipality_by_branch(
        {r.get("branch") for r in data if r.get("branch")}
    )

    main_branch_by_branch: dict = _get_main_branch_map()

    for row in data:
        row["fiscal_document_no"] = _format_fiscal_document_no(
            row.get("fiscal_series"), row.get("bill_no")
        )
        row["main_branch"] = main_branch_by_branch.get(row.get("branch"), "")
        row["municipality"] = municipality_by_branch.get(row.get("branch"), "")

    _insert_column_after(
        columns,
        "fiscal_series",
        {
            "label": _("Documento Fiscal"),
            "fieldname": "fiscal_document_no",
            "fieldtype": "Data",
            "width": 140,
        },
    )
    # Orden: Sucursal (operativa) -> Sucursal Principal (consolidación) -> Municipio
    _insert_column_after(
        columns,
        "branch",
        {
            "label": _("Sucursal Principal"),
            "fieldname": "main_branch",
            "fieldtype": "Data",
            "width": 150,
        },
    )
    _insert_column_after(
        columns,
        "main_branch",
        {
            "label": _("Municipio"),
            "fieldname": "municipality",
            "fieldtype": "Data",
            "width": 130,
        },
    )


def _format_fiscal_document_no(series, number) -> str:
    """``('MIR-01', '4779')`` -> ``'MIR-01-4779'``.

    Si falta una de las dos partes se devuelve la otra sola, para no inventar un
    identificador a medias.
    """
    series = str(series or "").strip()
    number = str(number or "").strip()
    if series and number:
        return f"{series}-{number}"
    return series or number


def _get_main_branch_map() -> dict:
    """Mapa ``{sucursal: sucursal principal}``.

    La *sucursal principal* es el ancestro que cuelga **directo de la raíz** del
    árbol, que es el nivel al que consolida casa matriz. Ejemplo real:
    ``ARMANDO`` -> ``GUARENAS`` -> ``MIR-01`` -> ``GALANET HQ`` (raíz), luego la
    principal de ``ARMANDO`` es ``MIR-01``.

    Las sucursales que ya cuelgan de la raíz (``ARA-02``, ``DC-01``...) y la raíz
    misma se apuntan a sí mismas, así la columna nunca queda vacía.

    Se resuelve subiendo por ``parent_ve_branch`` con el árbol completo en
    memoria (son decenas de nodos): una sola consulta para todas las filas.
    """
    rows: list[dict] = frappe.get_all(
        BRANCH_DOCTYPE, fields=["name", "parent_ve_branch"]
    )
    parent: dict = {r.name: r.parent_ve_branch for r in rows}
    roots: set = {name for name, p in parent.items() if not p}

    def _main_branch(branch: str) -> str:
        current, seen = branch, set()
        while True:
            p = parent.get(current)
            if not p or p in roots:
                return current
            if current in seen:  # árbol inconsistente: no colgarse
                return branch
            seen.add(current)
            current = p

    return {name: _main_branch(name) for name in parent}


def _get_municipality_by_branch(branches: set) -> dict:
    """Mapa ``{sucursal: nombre legible del municipio}``.

    ``VE Branch.municipality`` es un Link a ``VE Municipality``: mostrar el ID
    crudo sería un hash, así que se resuelve al título.
    """
    branches = {b for b in branches if b}
    if not branches:
        return {}

    rows: list[dict] = frappe.get_all(
        BRANCH_DOCTYPE,
        filters={"name": ["in", list(branches)]},
        fields=["name", "municipality"],
    )

    municipality_ids: set = {r.municipality for r in rows if r.municipality}
    labels: dict = {}
    if municipality_ids:
        title_field: str = (
            frappe.get_meta(MUNICIPALITY_DOCTYPE).get_title_field() or "name"
        )
        for m in frappe.get_all(
            MUNICIPALITY_DOCTYPE,
            filters={"name": ["in", list(municipality_ids)]},
            fields=["name", title_field],
        ):
            labels[m["name"]] = m.get(title_field) or m["name"]

    return {r.name: labels.get(r.municipality, "") for r in rows}


def _insert_column_after(columns: list[dict], fieldname: str, column: dict) -> None:
    """Inserta ``column`` justo después de la de ``fieldname`` (o al final)."""
    for i, existing in enumerate(columns):
        if existing.get("fieldname") == fieldname:
            columns.insert(i + 1, column)
            return
    columns.append(column)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_main_branches(doctype, txt, searchfield, start, page_len, filters):
    """Link query del filtro 'Sucursal Principal': solo las de consolidación.

    Son las que cuelgan directo de la raíz del árbol. Ofrecer las sucursales
    completas obligaría al usuario a saber de memoria cuáles consolidan.
    """
    return frappe.db.sql("""
        SELECT b.name
        FROM `tabVE Branch` b
        INNER JOIN `tabVE Branch` raiz ON raiz.name = b.parent_ve_branch
        WHERE IFNULL(raiz.parent_ve_branch, '') = ''
          AND b.name LIKE %(txt)s
        ORDER BY b.name
        LIMIT %(start)s, %(page_len)s
    """, {"txt": "%" + txt + "%", "start": start, "page_len": page_len})
