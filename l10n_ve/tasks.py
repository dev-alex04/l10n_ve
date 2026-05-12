import requests
from bs4 import BeautifulSoup
import frappe

from frappe.utils import getdate, formatdate, get_datetime_str, nowdate, flt


BCV_URL = "https://www.bcv.org.ve/"
BCV_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@frappe.whitelist()
def create_currency_exchange() -> None:
    """
    Obtiene las tasas de cambio del BCV y crea/actualiza Currency Exchange.
    Estrategia: BCV/SENIAT → API externa → web scraping → error.
    """
    rates_data = (
        _fetch_rates_from_bcv_seniat()
        or _fetch_rates_from_api()
        or _fetch_rates_from_scraping()
    )

    if not rates_data:
        frappe.log_error(
            "BCV Error",
            "No se pudieron obtener las tasas por ningún método (API ni scraping)."
        )
        return

    _process_rates(rates_data)


CURRENCY_SWIFT_CODES = ("USD", "EUR")


def _fetch_rates_from_bcv_seniat() -> dict | None:
    """Obtiene las tasas de cambio desde la API oficial del BCV/SENIAT ignorando SSL."""
    bcv_seniat_endpoint = (
        frappe.get_site_config().get("bcv_seniat_endpoint")
        or "https://tcseniat.extra.bcv.org.ve/tcseniat/resources/TipoCambio/fechaOperacion"
    )

    try:
        response = requests.get(
            bcv_seniat_endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": BCV_USER_AGENT,
            },
            timeout=15,
            verify=False  
        )
        response.raise_for_status()

        data = response.json()
        mercado = next(iter(data.get("MERCADO", [])), {})
        fecha_valor = mercado.get("FECHAVALOR")
        monedas = mercado.get("MONEDA", [])

        if not fecha_valor or not monedas:
            frappe.log_error(
                "BCV SENIAT Error",
                f"Respuesta incompleta del BCV/SENIAT. Datos: {data}"
            )
            return None

        rates = {}
        for moneda in monedas:
            swift = moneda.get("SWIFT")
            if swift in CURRENCY_SWIFT_CODES:
                rates[swift] = "{:.8f}".format(flt(moneda.get("BDVENTAASK", 0)))

        if not rates:
            frappe.log_error(
                "BCV SENIAT Error",
                f"No se encontraron tasas para {CURRENCY_SWIFT_CODES}."
            )
            return None

        return {
            "date": fecha_valor[:10], 
            "rates": rates,
        }

    except requests.exceptions.RequestException as e:
        frappe.log_error(
            "BCV SENIAT Error",
            f"Error al obtener tasas del BCV/SENIAT: {e}"
        )
        return None


def _fetch_rates_from_api() -> dict | None:
    """Intenta obtener las tasas de cambio desde la API configurada en site_config."""
    bcv_endpoint = frappe.get_site_config().get("bcv_endpoint")
    bcv_api_key = frappe.get_site_config().get("bcv_api_key")

    if not bcv_endpoint:
        frappe.log_error(
            "BCV API Info",
            "bcv_endpoint no configurado, saltando a web scraping."
        )
        return None

    try:
        headers = {}
        if bcv_api_key:
            headers["x-dolarvzla-key"] = bcv_api_key

        response = requests.get(bcv_endpoint, headers=headers, timeout=10)

        if response.status_code != 200:
            frappe.log_error(
                "BCV API Error",
                f"API Status {response.status_code}: {response.text}"
            )
            return None

        current_rates = response.json().get("current", {})
        date_str = current_rates.get("date")
        usd_rate = current_rates.get("usd")
        eur_rate = current_rates.get("eur")

        if not (date_str and usd_rate and eur_rate):
            frappe.log_error(
                "BCV API Error",
                f"Respuesta de API incompleta. Datos: {current_rates}"
            )
            return None

        return {
            "date": date_str,
            "rates": {"USD": usd_rate, "EUR": eur_rate},
        }

    except Exception as e:
        frappe.log_error(
            "BCV API Error",
            f"Error con API: {e}"
        )
        return None


def _fetch_rates_from_scraping() -> dict | None:
    """Fallback: obtiene las tasas haciendo web scraping a la página del BCV."""
    frappe.log_error("BCV Fallback", "Iniciando fallback a web scraping.")

    try:
        response = requests.get(
            BCV_URL,
            headers={"User-Agent": BCV_USER_AGENT},
            verify=False,
            timeout=60,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        rates = _extract_rates_from_html(soup)
        date_val = _extract_date_from_html(soup)

        if not date_val or not rates:
            frappe.log_error(
                "BCV Scrape Error",
                "No se pudo obtener la fecha o las tasas."
            )
            return None

        return {"date": date_val, "rates": rates}

    except Exception as e:
        frappe.log_error("BCV Scrape Error", str(e))
        return None


def _extract_rates_from_html(soup: BeautifulSoup) -> dict:
    """Extrae las tasas USD y EUR del HTML del BCV."""
    rates = {}
    currencies = {"dolar": "USD", "euro": "EUR"}

    for html_id, iso in currencies.items():
        div = soup.find("div", id=html_id)
        if not (div and div.find("strong")):
            continue

        raw_value = div.find("strong").text.strip()
        clean_value = raw_value.replace(".", "").replace(",", ".")
        rates[iso] = "{:.8f}".format(flt(clean_value))

    return rates


def _extract_date_from_html(soup: BeautifulSoup) -> str | None:
    """Extrae la fecha de publicación de las tasas del HTML del BCV."""
    date_container = soup.find(
        "div", class_="views-field-field-fecha-del-indicador"
    )
    time_tag = date_container.find("time") if date_container else None

    if not (time_tag and time_tag.get("datetime")):
        return None

    return time_tag.get("datetime")[:10]


def _process_rates(rates_data: dict) -> None:
    """
    Crea/actualiza documentos de Currency Exchange.
    Incluye protección contra fechas futuras (fines de semana/feriados).
    """
    doctype = "Currency Exchange"
    to_currency = "VEF"
    purpose = "Selling-Buying"

    api_date = getdate(rates_data.get("date"))
    today_date = getdate(nowdate())

    for from_currency, exchange_rate in rates_data.get("rates", {}).items():
        if not exchange_rate:
            continue

        resolved = _resolve_future_date(
            api_date, today_date, from_currency,
            to_currency, exchange_rate, doctype
        )

        if resolved is None:
            continue

        target_date, target_rate = resolved

        exchange_name = (
            f"{formatdate(get_datetime_str(target_date), 'yyyy-MM-dd')}"
            f"-{from_currency}-{to_currency}-{purpose}"
        )

        if frappe.db.exists(doctype, exchange_name):
            frappe.db.set_value(
                doctype, exchange_name,
                "exchange_rate", target_rate
            )
        else:
            doc = frappe.new_doc(doctype)
            doc.update({
                "for_buying": True,
                "for_selling": True,
                "date": target_date,
                "to_currency": to_currency,
                "from_currency": from_currency,
                "exchange_rate": target_rate,
            })
            doc.insert(ignore_permissions=True)


def _resolve_future_date(
    api_date,
    today_date,
    from_currency: str,
    to_currency: str,
    exchange_rate,
    doctype: str,
) -> tuple | None:
    """
    Si la fecha del BCV es futura y hoy ya tiene tasa, retorna None (no hacer nada).
    Si la fecha es futura y hoy NO tiene tasa, usa la última tasa conocida.
    Si la fecha es de hoy o pasada, retorna la tasa tal cual.
    """
    if api_date <= today_date:
        return api_date, exchange_rate

    today_already_has_rate = frappe.db.exists(doctype, {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "date": today_date,
    })

    if today_already_has_rate:
        return None

    last_rate = frappe.db.get_value(
        doctype,
        {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "date": ["<", today_date],
            "for_selling": 1,
        },
        "exchange_rate",
        order_by="date desc",
    )

    if not last_rate:
        return api_date, exchange_rate

    frappe.log_error(
        "BCV Protection",
        f"Fecha futura detectada ({api_date}). "
        f"Usando tasa previa ({last_rate}) para hoy ({today_date})."
    )
    return today_date, last_rate


def reset_all_prepared_reports() -> None:
    """
    Capa 1 — Red de seguridad del sistema de prepared_report inteligente.

    Frappe activa prepared_report=1 en BD cuando un reporte tarda > 15s.
    La Capa 2 (report_session_patch.py) suprime ese mecanismo interceptando
    execute_script_report, pero pueden existir paths alternativos no cubiertos.

    Esta tarea corre cada 15 minutos y resetea prepared_report=0 en todos
    los reportes que lo tengan activo en BD, garantizando que ningún reporte
    quede bloqueado en modo background de forma permanente.

    El commit lo gestiona el llamador (el worker de scheduler de Frappe hace
    commit automático al finalizar cada job; migrate lo hace por patch).
    """
    if not (frappe.local and getattr(frappe.local, "db", None)):
        return

    try:
        reportes_afectados = frappe.db.get_all(
            "Report",
            filters={"prepared_report": 1},
            pluck="name",
        )

        if not reportes_afectados:
            return

        for report_name in reportes_afectados:
            frappe.db.set_value("Report", report_name, "prepared_report", 0)

        frappe.logger().info(
            f"[l10n_ve] reset_all_prepared_reports: {len(reportes_afectados)} "
            f"reporte(s) reseteado(s): {reportes_afectados}"
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "[l10n_ve] Error en reset_all_prepared_reports")


def cleanup_resolved_digital_invoice_error_logs() -> None:
    """Elimina logs de error HKA que ya no aportan valor diagnóstico.

    Ejecuta 7 estrategias de limpieza en orden y reporta el resultado.
    """
    strategies: dict[str, int] = {
        "resueltos_por_log": _cleanup_resolved_by_success_log(),
        "resueltos_por_bill_no": _cleanup_resolved_by_bill_no(),
        "resumenes": _cleanup_batch_summaries(),
        "tracebacks": _cleanup_resolved_tracebacks(),
        "canceladas": _cleanup_cancelled_invoice_logs(),
        "infra": _cleanup_stale_infra_logs(),
        "duplicados": _cleanup_duplicate_error_logs(),
    }

    total_deleted: int = sum(strategies.values())
    if total_deleted:
        frappe.db.commit()
        detail: str = ", ".join(
            f"{k}: {v}" for k, v in strategies.items() if v
        )
        frappe.logger("tfhka").info(
            f"Limpieza de logs: {total_deleted} eliminados ({detail})"
        )


def _delete_logs(names: list[str]) -> int:
    """Elimina logs por lista de names y retorna la cantidad eliminada."""
    if not names:
        return 0
    frappe.db.delete("VE Digital Invoice Log", {"name": ["in", names]})
    return len(names)


def _cleanup_resolved_by_success_log() -> int:
    """A) Logs de error cuya factura ya tiene un log exitoso."""
    rows: list[dict] = frappe.db.sql("""
        SELECT err.name
        FROM `tabVE Digital Invoice Log` err
        INNER JOIN `tabVE Digital Invoice Log` ok
            ON ok.sales_invoice = err.sales_invoice
            AND ok.document_type = err.document_type
            AND ok.status = 'Success'
        WHERE err.status = 'Error'
    """, as_dict=True)
    return _delete_logs([r.name for r in rows])


def _cleanup_resolved_by_bill_no() -> int:
    """B) Logs con sales_invoice NULL cuya factura ya tiene bill_no o fue cancelada."""
    rows: list[dict] = frappe.db.sql("""
        SELECT log.name
        FROM `tabVE Digital Invoice Log` log
        JOIN `tabSales Invoice` si
            ON si.name = SUBSTRING_INDEX(
                SUBSTRING_INDEX(log.notes, ': ', 1),
                'Error enviando ', -1
            )
        WHERE log.status = 'Error'
          AND log.sales_invoice IS NULL
          AND log.notes LIKE 'Error enviando ACC-%%'
          AND (
              (si.bill_no IS NOT NULL AND si.bill_no != '')
              OR si.docstatus = 2
          )
    """, as_dict=True)
    return _delete_logs([r.name for r in rows])


def _cleanup_batch_summaries() -> int:
    """C) Resúmenes redundantes ('Completado: X exitosas, Y con error')."""
    rows: list[dict] = frappe.db.sql("""
        SELECT name
        FROM `tabVE Digital Invoice Log`
        WHERE status != 'Success'
          AND notes LIKE 'Completado:%%'
    """, as_dict=True)
    return _delete_logs([r.name for r in rows])


def _cleanup_resolved_tracebacks() -> int:
    """D) Tracebacks cuya factura ya tiene bill_no (resuelta por reintento).

    El JOIN usa LIKE bilateral, así que se limita a logs de los últimos
    7 días para evitar full scan sobre tablas grandes.
    """
    rows: list[dict] = frappe.db.sql("""
        SELECT log.name
        FROM `tabVE Digital Invoice Log` log
        JOIN `tabSales Invoice` si
            ON log.notes LIKE CONCAT('%%', si.name, '%%')
        WHERE log.status = 'Error'
          AND log.sales_invoice IS NULL
          AND log.notes LIKE 'Traceback%%'
          AND log.creation >= DATE_SUB(NOW(), INTERVAL 7 DAY)
          AND si.bill_no IS NOT NULL AND si.bill_no != ''
          AND si.posting_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """, as_dict=True)
    return _delete_logs([r.name for r in rows])


def _cleanup_cancelled_invoice_logs() -> int:
    """E) Logs de facturas canceladas (nunca se procesarán)."""
    rows: list[dict] = frappe.db.sql("""
        SELECT log.name
        FROM `tabVE Digital Invoice Log` log
        JOIN `tabSales Invoice` si ON si.name = log.sales_invoice
        WHERE log.status = 'Error'
          AND si.docstatus = 2
    """, as_dict=True)
    return _delete_logs([r.name for r in rows])


def _cleanup_stale_infra_logs() -> int:
    """F) Errores de infraestructura antiguos (auth, notes vacío)."""
    rows: list[dict] = frappe.db.sql("""
        SELECT name
        FROM `tabVE Digital Invoice Log`
        WHERE status = 'Error'
          AND sales_invoice IS NULL
          AND (notes IS NULL OR notes = '')
    """, as_dict=True)
    return _delete_logs([r.name for r in rows])


def _cleanup_duplicate_error_logs() -> int:
    """G) Deduplicación: conserva solo el log más reciente por factura."""
    rows: list[dict] = frappe.db.sql("""
        SELECT log.name
        FROM `tabVE Digital Invoice Log` log
        INNER JOIN (
            SELECT
                SUBSTRING_INDEX(
                    SUBSTRING_INDEX(notes, ': ', 1),
                    'Error enviando ', -1
                ) AS factura,
                MAX(creation) AS ultima
            FROM `tabVE Digital Invoice Log`
            WHERE status = 'Error'
              AND notes LIKE 'Error enviando ACC-%%'
            GROUP BY factura
            HAVING COUNT(*) > 1
        ) dup ON log.notes LIKE CONCAT('Error enviando ', dup.factura, ':%%')
              AND log.creation < dup.ultima
        WHERE log.status = 'Error'
          AND log.notes LIKE 'Error enviando ACC-%%'
    """, as_dict=True)
    return _delete_logs([r.name for r in rows])


def purge_old_digital_invoice_success_logs() -> None:
    """Elimina logs de éxito del mes anterior. Se ejecuta el 1 de cada mes."""
    first_of_current_month: str = getdate(nowdate()).replace(day=1).isoformat()

    count: int = frappe.db.count(
        "VE Digital Invoice Log",
        {"status": "Success", "creation": ["<", first_of_current_month]},
    )

    if not count:
        return

    frappe.db.delete(
        "VE Digital Invoice Log",
        {"status": "Success", "creation": ["<", first_of_current_month]},
    )
    frappe.db.commit()
    frappe.logger("tfhka").info(
        f"Purga mensual: {count} logs de éxito anteriores a {first_of_current_month} eliminados"
    )
