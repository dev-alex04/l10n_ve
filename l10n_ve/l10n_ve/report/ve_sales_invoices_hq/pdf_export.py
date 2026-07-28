# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Exportación a PDF ejecutivo del Reporte HQ de facturas de venta.

No es el reporte impreso: es un documento de una página con indicadores,
comparativa contra el período anterior, concentración por sucursal, evolución
diaria, composición fiscal y observaciones derivadas de los datos. El detalle
fila por fila vive en la exportación a Excel.

Como el Excel, se genera **en memoria** y viaja en base64: no queda ningún
archivo en el disco del servidor.

OJO al motor: Frappe usa wkhtmltopdf, con un WebKit viejo que NO ejecuta
JavaScript y NO admite flex/grid. De ahí dos cosas que parecen rarezas y no lo
son: la retícula se arma con ``<table>`` y ``border-spacing``, y los gráficos
son SVG generado acá (no hay Chart.js ni canvas que valgan). Probado contra ese
motor: ``box-shadow``, ``border-radius`` y los SVG sí pintan; ``linear-gradient``
NO, por eso no se usa en ninguna parte.

Los números salen de ``get_hq_data`` —el mismo núcleo que alimenta la
pantalla—, y los porcentajes se calculan contra ``main_data`` (las filas del
período), que es exactamente lo que suman los totales del libro. Sumar también
las filas de ajuste daría un denominador mayor y el documento se contradiría
consigo mismo.
"""

import base64
import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, get_first_day, get_last_day, getdate
from frappe.utils.pdf import get_pdf

from l10n_ve.l10n_ve.report.ve_sales_invoices_hq.ve_sales_invoices_hq import (
    _get_main_branch_map,
    get_hq_data,
)
from l10n_ve.utils.pdf_utils import _sanitize_html_for_wkhtmltopdf

# Paleta del logo (ver l10n_ve/public/js/utils/brand_logo.js). Aquí se repite en
# Python porque el PDF lo arma el servidor, sin pasar por el navegador.
BRAND = {
    "top_left": "#E91A4B",
    "top_right": "#FF5100",
    "bottom_right": "#00B5E5",
    "bottom_left": "#009B52",
}
PATHS = {
    "top_left": "M -44,-1 L -1,-44 L -1,-26 L -26,-1 Z",
    "top_right": "M 1,-44 L 44,-1 L 26,-1 L 1,-26 Z",
    "bottom_right": "M 44,1 L 1,44 L 1,26 L 26,1 Z",
    "bottom_left": "M -1,44 L -44,1 L -26,1 L -1,26 Z",
}
QUADRANTS = ("top_left", "top_right", "bottom_right", "bottom_left")
SLICE_COLORS = ["#00B5E5", "#009B52", "#FF5100", "#8B5CF6", "#E91A4B", "#9CA3AF"]

# Franja de acento de cada indicador. Se evita a propósito el rojo de la marca:
# en un documento financiero una barra roja se lee como alarma, no como color.
KPI_ACCENTS = ["#00B5E5", "#009B52", "#FF5100", "#8B5CF6"]

UP, DOWN = "#059669", "#DC2626"
INK, SOFT, RULE = "#111827", "#6B7280", "#E5E7EB"

# Se listan también las alícuotas en cero: en un documento fiscal "no hubo" es
# información, no ruido.
COMPOSITION = [
    ("Base imponible general", "Base Imponible General", "Impuesto General"),
    ("Base imponible reducida", "Base Imponible Reducida", "Impuesto Reducido"),
    ("Base imponible adicional", "Base Imponible Adicional", "Impuesto Adicional"),
    ("Ventas no gravadas", "Ventas No Gravadas", None),
    ("IGTF", "Base IGTF", "Monto IGTF"),
]
TOP_CUSTOMERS = 12

# Anchos en píxeles y NO en porcentaje: el WebKit de wkhtmltopdf colapsa a cero
# los SVG con ancho porcentual. Salen de la retícula de la página (carta
# vertical, márgenes de 12 mm) menos el relleno de cada tarjeta.
DAY_CHART_WIDTH = 428
DONUT_SIZE = 118
MAX_SLICES = 5


@frappe.whitelist()
def download_hq_pdf(filters: str | dict | None = None) -> dict:
    """Genera el PDF ejecutivo y lo devuelve para descarga directa.

    El endpoint es invocable por sí solo: sin el chequeo de rol cualquier
    usuario autenticado podría bajarse el consolidado de facturación.
    """
    frappe.only_for(("VE Sales Book HQ", "System Manager"))

    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    company = filters.get("company") or ""

    html = build_html(filters, company)
    # Quita recursos externos (fuentes/CDN) que hacen fallar a wkhtmltopdf con
    # HostNotFoundError en entornos aislados.
    pdf = get_pdf(
        _sanitize_html_for_wkhtmltopdf(html),
        {
            "orientation": "Portrait",
            "page-size": "Letter",
            "load-error-handling": "skip",
            "disable-javascript": "",
        },
    )

    return {
        "type": "download",
        "filename": _build_filename(filters),
        "filecontent": base64.b64encode(pdf).decode("ascii"),
    }


def _build_filename(filters: dict) -> str:
    parts = ["Resumen_Ejecutivo_Facturas"]
    for key in ("from_date", "to_date"):
        if filters.get(key):
            parts.append(getdate(filters[key]).strftime("%Y%m%d"))
    return "{0}.pdf".format("_".join(parts))


def previous_period(from_date, to_date) -> tuple:
    """Período contra el que se compara.

    Si el rango es un mes calendario completo se usa el mes anterior, que es
    como razona contabilidad. Para un rango arbitrario, la misma cantidad de
    días inmediatamente antes.
    """
    start, end = getdate(from_date), getdate(to_date)
    if start == get_first_day(start) and end == get_last_day(end) and start.month == end.month:
        previous = add_months(start, -1)
        return str(get_first_day(previous)), str(get_last_day(previous))
    days = (end - start).days + 1
    return str(add_days(start, -days)), str(add_days(start, -1))


def money(value, decimals: int = 2) -> str:
    """Formato venezolano: 1.234.567,89"""
    return f"{float(value or 0):,.{decimals}f}".translate(str.maketrans({",": ".", ".": ","}))


def compact(value) -> str:
    value = float(value or 0)
    return f"{money(value / 1_000_000, 2)} M" if abs(value) >= 1_000_000 else money(value)


def variation(current, previous):
    return ((current - previous) / previous * 100) if previous else None


def collect(filters: dict) -> dict:
    """Agrega SOLO las filas del período (las que suman los totales)."""
    hq = get_hq_data(filters)
    main_data = hq["main_data"]
    summary = {x.get("label"): x.get("value") for x in (hq["report_summary"] or [])}
    main_branch = _get_main_branch_map()

    by_branch, by_customer, by_day = defaultdict(float), defaultdict(float), defaultdict(float)
    credit_notes, credit_amount = 0, 0.0
    for row in main_data:
        amount = float(row.get("grand_total") or 0)
        by_branch[main_branch.get(row.get("branch")) or "—"] += amount
        by_customer[row.get("customer_name") or "—"] += amount
        by_day[str(row.get("posting_date"))] += amount
        if row.get("credit_note_no"):
            credit_notes += 1
            credit_amount += amount

    return {
        "summary": summary,
        "docs": len(main_data),
        "by_branch": dict(by_branch),
        "by_customer": dict(by_customer),
        "by_day": dict(by_day),
        "credit_notes": credit_notes,
        "credit_amount": credit_amount,
        "total": float(summary.get("Total Ventas Incl. IVA") or 0),
    }


def observations(current: dict, previous: dict, previous_label: str) -> list:
    """Frases derivadas de los datos, no texto fijo."""
    notes = []
    total = current["total"]

    started = [
        branch for branch, value in current["by_branch"].items()
        if value > 0 and float(previous["by_branch"].get(branch, 0)) == 0
    ]
    growth = variation(total, previous["total"])
    if started and growth and growth > 25:
        notes.append((
            "alert",
            _("El aumento de {0}% frente a {1} se explica principalmente por {2}, "
              "que no facturaba en ese período.").format(
                money(growth, 1), previous_label, ", ".join(sorted(started)))
        ))
    elif growth is not None:
        notes.append((
            "info",
            _("La facturación {0} {1}% frente a {2}.").format(
                _("aumentó") if growth >= 0 else _("disminuyó"),
                money(abs(growth), 1), previous_label)
        ))

    if current["by_customer"] and total:
        name, value = max(current["by_customer"].items(), key=lambda kv: kv[1])
        share = value / total * 100
        if share >= 5:
            notes.append((
                "alert",
                _("Un solo cliente ({0}) concentra el {1}% del período.").format(
                    name.strip(), money(share, 1))
            ))

    if current["credit_notes"]:
        notes.append((
            "info",
            _("{0} nota(s) de crédito restan {1} del período.").format(
                current["credit_notes"], money(abs(current["credit_amount"])))
        ))

    notes.append((
        "info",
        _("{0} clientes facturados; {1} días con actividad.").format(
            money(len(current["by_customer"]), 0), money(len(current["by_day"]), 0))
    ))
    notes.append((
        "muted",
        _("Solo incluye documentos ya certificados por la imprenta digital."),
    ))
    return notes


def logo_svg(size: int = 30) -> str:
    paths = "".join(f'<path fill="{BRAND[q]}" d="{PATHS[q]}"/>' for q in QUADRANTS)
    return (f'<svg viewBox="0 0 100 100" width="{size}" height="{size}">'
            f'<g transform="translate(50,50)">{paths}</g></svg>')


def _slices(pairs: list) -> list:
    """Las sucursales de cola se agrupan en «Otras»: más de cinco porciones la
    dona deja de leerse y las etiquetas se pisan."""
    ordered = sorted(pairs, key=lambda kv: -kv[1])
    if len(ordered) <= MAX_SLICES:
        return ordered
    rest = sum(v for _n, v in ordered[MAX_SLICES:])
    return ordered[:MAX_SLICES] + [(_("Otras ({0})").format(len(ordered) - MAX_SLICES), rest)]


def donut_chart(pairs: list, total: float) -> str:
    """Anillo de participación con leyenda debajo."""
    items = _slices(pairs)
    if not items:
        return ""
    added = sum(v for _n, v in items) or 1
    radius, center = DONUT_SIZE / 2 - 1, DONUT_SIZE / 2
    wedges, angle = [], -math.pi / 2

    for i, (_label, value) in enumerate(items):
        end = angle + 2 * math.pi * (value / added)
        # Una porción única no se puede dibujar con un arco (inicio y fin
        # coinciden y el path sale vacío): se resuelve con el anillo completo.
        if len(items) == 1:
            wedges.append(f'<circle cx="{center}" cy="{center}" r="{radius}" fill="{SLICE_COLORS[0]}"/>')
            break
        x0, y0 = center + radius * math.cos(angle), center + radius * math.sin(angle)
        x1, y1 = center + radius * math.cos(end), center + radius * math.sin(end)
        wedges.append(
            f'<path d="M {center} {center} L {x0:.2f} {y0:.2f} '
            f'A {radius:.2f} {radius:.2f} 0 {1 if end - angle > math.pi else 0} 1 {x1:.2f} {y1:.2f} Z" '
            f'fill="{SLICE_COLORS[i % len(SLICE_COLORS)]}"/>'
        )
        angle = end

    wedges.append(f'<circle cx="{center}" cy="{center}" r="{radius*0.60:.2f}" fill="#FFFFFF"/>')
    wedges.append(
        f'<text x="{center}" y="{center-1}" font-size="12" font-weight="bold" '
        f'fill="{INK}" text-anchor="middle">{compact(total)}</text>'
        f'<text x="{center}" y="{center+10}" font-size="6.5" fill="{SOFT}" '
        f'text-anchor="middle">{_("TOTAL")}</text>'
    )

    legend = "".join(
        f'<tr><td style="width:9px;padding:1.5px 0;">'
        f'<span style="display:inline-block;width:6px;height:6px;border-radius:3px;'
        f'background:{SLICE_COLORS[i % len(SLICE_COLORS)]};"></span></td>'
        f'<td style="color:#374151;">{frappe.utils.escape_html(str(label))[:16]}</td>'
        f'<td style="text-align:right;color:{INK};font-weight:bold;">'
        f'{money(value/added*100,1)}%</td></tr>'
        for i, (label, value) in enumerate(items)
    )

    return (f'<div style="text-align:center;">'
            f'<svg width="{DONUT_SIZE}" height="{DONUT_SIZE}" '
            f'viewBox="0 0 {DONUT_SIZE} {DONUT_SIZE}">{"".join(wedges)}</svg></div>'
            f'<table style="font-size:8pt;margin-top:5px;">{legend}</table>')


def day_chart(by_day: dict, height: int = 152) -> str:
    """Evolución diaria como línea con área, con el día pico marcado."""
    if not by_day:
        return ""
    items = sorted(by_day.items(), key=lambda kv: (kv[0][6:], kv[0][3:5], kv[0][:2]))
    largest = max(v for _n, v in items) or 1
    top, floor = 16, height - 16
    span = floor - top
    step = DAY_CHART_WIDTH / max(len(items) - 1, 1)
    points = [(i * step, floor - (value / largest) * span) for i, (_d, value) in enumerate(items)]
    peak = max(range(len(items)), key=lambda i: items[i][1])

    # Un solo día no tiene línea que trazar; se dibuja el punto y ya.
    path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)
    parts = [
        f'<line x1="0" y1="{floor}" x2="{DAY_CHART_WIDTH}" y2="{floor}" stroke="{RULE}" stroke-width="0.7"/>',
        f'<path d="{path} L {points[-1][0]:.2f} {floor} L 0 {floor} Z" fill="#E1F4FB"/>',
        f'<path d="{path}" fill="none" stroke="#00B5E5" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round"/>',
        f'<circle cx="{points[peak][0]:.2f}" cy="{points[peak][1]:.2f}" r="2.6" fill="#00B5E5"/>',
        f'<text x="{min(points[peak][0], DAY_CHART_WIDTH-70):.2f}" y="{max(points[peak][1]-6, 8):.2f}" '
        f'font-size="7.5" fill="{SOFT}">{_("pico")} {items[peak][0][:5]} · {compact(items[peak][1])}</text>',
    ]

    ticks = list(range(0, len(items), 7))
    if len(items) - 1 not in ticks:
        ticks.append(len(items) - 1)
    for i in ticks:
        x = min(max(points[i][0], 12), DAY_CHART_WIDTH - 12)
        parts.append(f'<text x="{x:.2f}" y="{floor+11}" font-size="7" fill="#9CA3AF" '
                     f'text-anchor="middle">{items[i][0][:5]}</text>')

    return (f'<svg width="{DAY_CHART_WIDTH}" height="{height}" '
            f'viewBox="0 0 {DAY_CHART_WIDTH} {height}">{"".join(parts)}</svg>')


def kpi_cell(label: str, value: str, delta, accent: str) -> str:
    """Tarjeta de indicador con franja de acento a la izquierda.

    La variación va con flecha además de con color: impreso en blanco y negro,
    o para quien no distingue rojo de verde, el color solo no dice nada.
    """
    trend = f'<div style="font-size:8pt;color:#9CA3AF;margin-top:2px;">{_("sin comparativa")}</div>'
    if delta is not None:
        arrow = "&#9650;" if delta >= 0 else "&#9660;"
        trend = (f'<div style="font-size:8pt;margin-top:2px;color:{UP if delta >= 0 else DOWN};">'
                 f'{arrow} {"+" if delta >= 0 else ""}{money(delta,1)}% '
                 f'<span style="color:#9CA3AF;">{_("vs anterior")}</span></div>')
    return (f'<td class="card" style="width:25%;border-left:3px solid {accent};">'
            f'<div class="cap">{label}</div>'
            f'<div style="font-size:15pt;font-weight:bold;color:{INK};margin-top:2px;'
            f'letter-spacing:-0.3px;">{value}</div>{trend}</td>')


def composition_table(summary: dict, total: float) -> str:
    rows = []
    for label, base_key, tax_key in COMPOSITION:
        base = float(summary.get(base_key) or 0)
        tax = float(summary.get(tax_key) or 0) if tax_key else None
        empty = ' style="color:#C7CBD1;"' if base == 0 and not tax else ""
        share = f"{money(base/total*100,1)}%" if total and base else "—"
        rows.append(
            f'<tr{empty}><td style="padding:3px 0;">{_(label)}</td>'
            f'<td style="text-align:right;">{compact(base)}</td>'
            f'<td style="text-align:right;width:42px;color:{SOFT};">{share}</td>'
            f'<td style="text-align:right;width:72px;">{compact(tax) if tax_key else ""}</td></tr>'
        )

    rows.append(
        f'<tr style="font-weight:bold;color:{INK};">'
        f'<td style="padding:5px 0 0;border-top:1px solid {RULE};">{_("Total IVA")}</td>'
        f'<td style="border-top:1px solid {RULE};"></td><td style="border-top:1px solid {RULE};"></td>'
        f'<td style="text-align:right;padding-top:5px;border-top:1px solid {RULE};">'
        f'{compact(summary.get("Total IVA"))}</td></tr>'
    )
    withheld = float(summary.get("IVA Retenido") or 0)
    if withheld:
        rows.append(
            f'<tr style="color:{SOFT};"><td style="padding:2px 0;">{_("IVA retenido")}</td>'
            f'<td></td><td></td><td style="text-align:right;">{compact(withheld)}</td></tr>'
        )

    header = (f'<tr class="cap"><td></td>'
              f'<td style="text-align:right;">{_("Base")}</td>'
              f'<td style="text-align:right;">%</td>'
              f'<td style="text-align:right;">{_("Impuesto")}</td></tr>')
    return f'<table style="font-size:8.5pt;">{header}{"".join(rows)}</table>'


def customers_table(by_customer: dict, total: float) -> str:
    items = sorted(by_customer.items(), key=lambda kv: -kv[1])[:TOP_CUSTOMERS]
    if not items:
        return f'<div style="font-size:8.5pt;color:#AAA;">{_("Sin clientes en el período.")}</div>'
    half = (len(items) + 1) // 2

    def column(chunk, offset):
        rows = "".join(
            f'<tr><td style="color:#C7CBD1;width:15px;font-size:7.5pt;">{offset+i+1}</td>'
            f'<td style="padding:3px 0;color:#374151;">{frappe.utils.escape_html(name.strip()[:30])}</td>'
            f'<td style="text-align:right;color:{INK};font-weight:bold;">{compact(value)}</td>'
            f'<td style="text-align:right;color:{SOFT};width:38px;">'
            f'{money(value/total*100,1) if total else "0,0"}%</td></tr>'
            for i, (name, value) in enumerate(chunk)
        )
        return f'<table style="font-size:8.5pt;">{rows}</table>'

    covered = sum(v for _n, v in items) / total * 100 if total else 0
    return (f'<table><tr>'
            f'<td style="width:50%;vertical-align:top;padding-right:14px;">{column(items[:half], 0)}</td>'
            f'<td style="vertical-align:top;">{column(items[half:], half)}</td></tr></table>'
            f'<div style="font-size:7.5pt;color:{SOFT};margin-top:5px;padding-top:4px;'
            f'border-top:1px solid {RULE};">'
            f'{_("Estos {0} clientes representan el {1}% del período.").format(len(items), money(covered,1))}</div>')


def build_html(filters: dict, company_name: str) -> str:
    current = collect(filters)
    prev_from, prev_to = previous_period(filters["from_date"], filters["to_date"])
    previous = collect({**filters, "from_date": prev_from, "to_date": prev_to})
    previous_label = (f"{getdate(prev_from).strftime('%d/%m/%Y')}–"
                      f"{getdate(prev_to).strftime('%d/%m/%Y')}")

    cur_sum, prev_sum = current["summary"], previous["summary"]

    def figure(summary, *keys):
        for key in keys:
            if summary.get(key) is not None:
                return float(summary.get(key) or 0)
        return 0.0

    base_now = figure(cur_sum, "Base Imponible General")
    tax_now = figure(cur_sum, "Total IVA", "Impuesto General")
    kpis = "".join([
        kpi_cell(_("Total con IVA"), compact(current["total"]),
                 variation(current["total"], previous["total"]), KPI_ACCENTS[0]),
        kpi_cell(_("Base imponible"), compact(base_now),
                 variation(base_now, figure(prev_sum, "Base Imponible General")), KPI_ACCENTS[1]),
        kpi_cell(_("IVA"), compact(tax_now),
                 variation(tax_now, figure(prev_sum, "Total IVA", "Impuesto General")), KPI_ACCENTS[2]),
        kpi_cell(_("Documentos"), money(current["docs"], 0),
                 variation(current["docs"], previous["docs"]), KPI_ACCENTS[3]),
    ])

    total = current["total"]
    branches = sorted(current["by_branch"].items(), key=lambda kv: -kv[1])

    styles = {
        "alert": f"border-left:3px solid #F59E0B;background:#FFFBEB;color:#92400E;",
        "info": f"border-left:3px solid {RULE};background:#F9FAFB;color:#374151;",
        "muted": "border-left:3px solid transparent;color:#9CA3AF;",
    }
    notes = "".join(
        f'<div style="padding:5px 8px;margin-bottom:5px;font-size:8.5pt;'
        f'border-radius:0 3px 3px 0;{styles[kind]}">{text}</div>'
        for kind, text in observations(current, previous, previous_label)
    )

    date_from = getdate(filters["from_date"]).strftime("%d/%m/%Y")
    date_to = getdate(filters["to_date"]).strftime("%d/%m/%Y")
    scope = filters.get("main_branch") or filters.get("branch") or _("Consolidado")
    company_name = frappe.utils.escape_html(company_name or "")

    # La retícula se arma con <table> y border-spacing, no con flex ni grid: el
    # WebKit de wkhtmltopdf es viejo y los reparte mal. El separado entre
    # tarjetas es el border-spacing, por eso cada bloque es su propia tabla.
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page {{ size: letter portrait; margin: 11mm 11mm 16mm 11mm; }}
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 9pt; color: #374151;
        margin: 0; background: #F3F4F6; }}
h2 {{ font-size: 10pt; font-weight: bold; margin: 0 0 7px; color: {INK}; }}
table {{ width: 100%; border-collapse: collapse; }}
.grid {{ border-collapse: separate; border-spacing: 6px; margin: 0 -6px; }}
.card {{ background: #FFFFFF; border-radius: 5px; padding: 9px 11px;
         box-shadow: 0 1px 2px rgba(17,24,39,0.10); vertical-align: top; }}
.cap {{ font-size: 7pt; color: {SOFT}; text-transform: uppercase; letter-spacing: 0.7px; }}
.foot {{ position: fixed; bottom: -9mm; left: 0; right: 0; font-size: 7.5pt; color: #9CA3AF;
         border-top: 1px solid {RULE}; padding-top: 5px; }}
</style></head><body>

<table style="margin-bottom:9px;"><tr>
  <td style="width:40px;vertical-align:middle;">{logo_svg(34)}</td>
  <td style="vertical-align:middle;">
    <div style="font-size:14pt;font-weight:bold;color:{INK};letter-spacing:-0.3px;">
      {_("Facturas de venta: resumen ejecutivo")}</div>
    <div style="font-size:8.5pt;color:{SOFT};margin-top:1px;">{company_name} ·
      {date_from} {_("al")} {date_to} ·
      <span style="display:inline-block;background:#E5E7EB;color:#374151;border-radius:8px;
                   padding:1px 7px;font-size:7.5pt;">{frappe.utils.escape_html(str(scope))}</span>
    </div>
  </td>
  <td style="text-align:right;vertical-align:middle;font-size:7.5pt;color:#9CA3AF;">
    {_("Comparado contra")}<br/><span style="color:{SOFT};">{previous_label}</span>
  </td>
</tr></table>

<table class="grid"><tr>{kpis}</tr></table>

<table class="grid"><tr>
  <td class="card" style="width:64%;">
    <h2>{_("Evolución diaria")}</h2>
    {day_chart(current["by_day"])}
  </td>
  <td class="card">
    <h2>{_("Concentración por sucursal")}</h2>
    {donut_chart(branches, total)}
  </td>
</tr></table>

<table class="grid"><tr>
  <td class="card" style="width:52%;">
    <h2>{_("Composición fiscal")}</h2>
    {composition_table(cur_sum, total)}
  </td>
  <td class="card">
    <h2>{_("Observaciones clave")}</h2>
    {notes}
  </td>
</tr></table>

<table class="grid"><tr><td class="card">
  <h2>{_("Principales clientes")}</h2>
  {customers_table(current["by_customer"], total)}
</td></tr></table>

<div class="foot"><table><tr>
  <td>{company_name}</td>
  <td style="text-align:right;vertical-align:middle;">
    <span style="vertical-align:middle;">powered by Domina Software</span>
    <span style="vertical-align:middle;display:inline-block;margin-left:5px;">{logo_svg(13)}</span>
  </td>
</tr></table></div>

</body></html>"""
