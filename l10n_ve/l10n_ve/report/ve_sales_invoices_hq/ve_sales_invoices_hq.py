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
    _humanize_columns(columns)

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


# Cómo separa el Libro de Ventas a los clientes en sus columnas. El criterio NO
# es interpretación: sale del propio SQL (sales_book._get_*), que clasifica por
# la primera letra del RIF sin guiones.
_TAXPAYER_GROUPS: dict = {
    "non_taxpayer": ("No Contribuyente",
                     "clientes no contribuyentes (RIF que empieza en V o E, o sin RIF)"),
    "taxpayer": ("Contribuyente",
                 "clientes contribuyentes (RIF que no empieza en V ni E: J, G, P…)"),
}
_VAT_RATES: dict = {
    "general": ("General", "alícuota general"),
    "reduced": ("Reducida", "alícuota reducida"),
    "additional": ("Adicional", "alícuota adicional"),
}


def _column_texts() -> dict:
    """``{fieldname: (etiqueta, descripción)}`` para el encabezado.

    La etiqueta puede ser ``None``: significa dejar la que trae el libro.

    Las que sí se reescriben son las doce de alícuota. El libro las abrevia
    ("Base Imponible No C. G", donde "C." es contribuyente y la última letra la
    alícuota) y fuera de contabilidad nadie las descifra. Se reescriben SOLO
    acá: ``sales_book`` es el reporte fiscal y su formato se contrasta contra lo
    declarado, así que no se toca.

    El texto se arma en cada llamada y no en una constante de módulo para que
    ``_()`` traduzca con el idioma de quien pide el reporte, no con el que
    hubiera al importar.
    """
    # Las doce son la misma frase con dos variables; se generan para que no se
    # desincronicen entre sí al retocar la redacción.
    texts: dict = {}
    for rate, (rate_label, rate_name) in _VAT_RATES.items():
        for group, (group_label, group_criteria) in _TAXPAYER_GROUPS.items():
            texts[f"base_{rate}_{group}"] = (
                _("Base Imponible {0} {1}").format(group_label, rate_label),
                _("Base imponible facturada a la {0} a {1}.").format(
                    rate_name, group_criteria),
            )
            texts[f"iva_{rate}_{group}"] = (
                _("IVA {0} {1}").format(group_label, rate_label),
                _("IVA cobrado a la {0} a {1}.").format(rate_name, group_criteria),
            )

    # El resto conserva la etiqueta del libro y solo suma el tooltip.
    descriptions: dict = {
        "branch": _("Sucursal que emitió el documento."),
        "main_branch": _(
            "Sucursal de primer nivel de la que depende la emisora y bajo la "
            "que consolida. Por ejemplo, ARMANDO consolida en MIR-01."
        ),
        "municipality": _(
            "Municipio de la sucursal. Hoy solo está cargado en algunas, así "
            "que la columna sale vacía en la mayoría de las filas."
        ),
        "posting_date": _("Fecha de emisión del documento."),
        "customer_tax_id": _("RIF del cliente."),
        "customer_name": _("Razón social o nombre del cliente."),
        "customer_type": _(
            "PJD: persona jurídica domiciliada · PJND: jurídica no domiciliada · "
            "PND: persona natural domiciliada · PNND: natural no domiciliada."
        ),
        "fiscal_series": _("Serie de la imprenta digital asignada a la sucursal."),
        "fiscal_document_no": _(
            "Serie y número juntos, tal como se pegan en la declaración "
            "(MIR-01-4779). Antes había que armarlo a mano."
        ),
        "bill_no": _("Número de la factura."),
        "bill_control": _("Número de control que asigna la imprenta digital."),
        "credit_note_no": _("Número de la nota de crédito, si el documento lo es."),
        "debit_note_no": _("Número de la nota de débito, si el documento lo es."),
        "affected_invoice_number": _("Factura que modifica la nota de crédito o débito."),
        "transaction_type": _("Tipo de operación registrada."),
        "grand_total": _("Total del documento, con IVA incluido."),
        "ve_fob": _("Ventas de exportación, a valor FOB."),
        "total_exempt": _("Ventas internas exentas o no sujetas a IVA."),
        "iva_retained": _(
            "IVA que retuvo el cliente. Solo cuenta si hay comprobante emitido "
            "y la retención cae dentro del período consultado."
        ),
        "vat_withholding_voucher_number": _(
            "Número del comprobante de retención de IVA que emitió el cliente."
        ),
        "withholding_date": _("Fecha del comprobante de retención."),
        "vat_withholding_rate": _("Porcentaje de IVA que retuvo el cliente."),
        "base_amount_igtf": _("Monto sobre el que se calcula el IGTF."),
        "igtf_rate": _("Porcentaje de IGTF aplicado."),
        "total_igtf": _("Impuesto a las Grandes Transacciones Financieras cobrado."),
    }
    texts.update({f: (None, d) for f, d in descriptions.items()})
    return texts


def _humanize_columns(columns: list[dict]) -> None:
    """Reescribe las etiquetas abreviadas y cuelga el tooltip, in place.

    Todo esto viaja una sola vez por corrida (no por fila), así que no pesa:
    son unos pocos kilobytes contra los megabytes de datos.
    """
    texts: dict = _column_texts()
    for column in columns:
        label, description = texts.get(column.get("fieldname"), (None, ""))
        if label:
            column["label"] = label
        if description:
            column["description"] = description


# Tipos cuyas columnas se pueden ocultar cuando el período las trae en cero.
_NUMERIC_FIELDTYPES: set = {"Currency", "Float", "Percent", "Int"}


def _drop_empty_numeric_columns(columns: list[dict], rows: list[dict]) -> list[dict]:
    """Quita de la PANTALLA las columnas numéricas sin un solo valor.

    Galanet no usa las alícuotas reducida y adicional ni las de no
    contribuyente, así que diez de las treinta y siete columnas salen en cero
    en todas las filas: son celdas que igual hay que formatear y dibujar.

    Se limita a las numéricas a propósito. Si desapareciera una de identidad
    (sucursal, municipio, cliente) porque el período no la trae, el reporte
    parecería incompleto en vez de vacío.

    Nada de esto toca ``get_hq_data``: el Excel debe seguir llevando las
    columnas completas del libro, tenga datos o no, porque es el artefacto que
    se contrasta contra lo declarado.
    """
    # Sin filas, "todo vacío" es cierto para cualquier columna y se llevaría
    # por delante hasta la última: no hay nada que ocultar.
    if not rows:
        return columns

    vacias: set = {
        column["fieldname"]
        for column in columns
        if column.get("fieldname")
        and column.get("fieldtype") in _NUMERIC_FIELDTYPES
        and not any(row.get(column["fieldname"]) for row in rows)
    }
    return [c for c in columns if c.get("fieldname") not in vacias]


def execute(filters=None):
    hq = get_hq_data(filters)
    rows: list[dict] = hq["main_data"] + hq["adjustment_data"]

    columns: list[dict] = _drop_empty_numeric_columns(hq["columns"], rows)

    # Las filas viajan como LISTA, no como diccionario: Frappe rearma el objeto
    # en el navegador mapeando por posición (query_report.js -> prepare_data).
    # Con 10.712 facturas eso baja el payload de 12,2 MB a 3,1 MB por sí solo, y
    # a 2,6 MB con las columnas vacías ya fuera. Lo que pesaba no eran los datos
    # (~1,3 MB) sino el nombre de cada campo repetido en cada una de las filas;
    # esa memoria de más era la que trababa el scroll de la tabla.
    fieldnames: list = [c.get("fieldname") for c in columns]
    data: list[list] = [[row.get(f) for f in fieldnames] for row in rows]

    # 3er valor = 'message': Frappe lo pinta entre los filtros y las tarjetas de
    # totales (query_report.js -> show_status / $status).
    message: str = _build_report_message(
        hq["branch"], hq["subtree"], hq["main_branch"]
    )

    return columns, data, message, None, hq["report_summary"]


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
