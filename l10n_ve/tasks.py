import requests
from bs4 import BeautifulSoup
import frappe

from frappe.utils import getdate, formatdate, get_datetime_str, nowdate, flt, fmt_money, add_years, add_days


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

    # Recién publicada la tasa, alinear los borradores que la esperaban. Va aquí (y no
    # como cron aparte) para garantizar el orden: primero existe la fila, después se
    # re-aplica. Nunca debe tumbar la carga de tasas.
    try:
        reconcile_draft_invoice_exchange_rates()
    except Exception:
        frappe.log_error(
            "BCV: fallo al alinear tasas de borradores",
            frappe.get_traceback(),
        )


# Tope por corrida: el caso normal son pocas facturas (solo las generadas con mucha
# anticipación). Un número alto solo puede venir de un backfill/anomalía: se procesa
# por tandas horarias y queda registro, en vez de barrer miles en un solo job.
DRAFT_RATE_SYNC_LIMIT: int = 500

# Tope de facturas detalladas en el Error Log agregado de fallos. El campo del Error Log
# se trunca: listarlas todas pierde justo el traceback que va al final y explica la causa.
_RATE_SYNC_FAILURES_IN_LOG: int = 100


def reconcile_draft_invoice_exchange_rates(limit: int = DRAFT_RATE_SYNC_LIMIT) -> dict:
    """Re-aplica la tasa BCV correcta a las facturas en BORRADOR que la esperaban.

    PROBLEMA QUE PREVIENE: una factura generada con anticipación toma la tasa vigente
    al crearse, porque la tasa del 1° de SU mes todavía no existe (el BCV la publica
    la noche anterior). Cuando después aparece, el documento queda con una tasa que no
    coincide con la de su ``tasa_fecha`` y ``_validate_tasa_coherencia`` BLOQUEA la
    certificación ante HKA (fail-closed), dejando la factura trabada indefinidamente.

    Corregir aquí es inocuo y llega a tiempo: la factura sigue en BORRADOR (no toca el
    mayor) y el ajuste ocurre ANTES de que el cliente pague, así que paga el monto en
    Bs correcto.

    Alcance deliberadamente estrecho (todo lo demás se omite):
      - Solo ``docstatus=0``. Una factura emitida cambia montos en Bs y asiento
        contable: eso es decisión de contabilidad, no de un cron.
      - Solo clientes NATURALES: su ``tasa_fecha`` es el 1° del mes por regla fiscal.
        El jurídico deriva su ``tasa_fecha`` de su propia tasa (auto-consistente) y se
        sincroniza al primer pago, así que tocarlo rompería ese flujo.
      - Solo si existe fila ``Currency Exchange`` con la fecha EXACTA del 1° del mes.
        Sin fila, el lookup cae a la tasa más reciente y estaríamos fijando un valor
        móvil que volvería a quedar desfasado.
      - NUNCA si la factura ya tiene pagos registrados en su ISP Payment Entry: el
        cliente pagó en Bs con la tasa vieja y subirla le crearía un faltante.

    Idempotente: si la tasa ya coincide, no se toca el documento.
    """
    from l10n_ve.utils.utils import is_juridical_customer

    company_currency: str = (
        frappe.db.get_single_value("Global Defaults", "default_currency") or "VEF"
    )
    cutoff: str = frappe.db.get_single_value("TFHKA Settings", "cutoff_date")
    if not cutoff:
        return {"checked": 0, "updated": 0, "failed": 0, "skipped_paid": 0,
                "skipped_no_rate": 0}

    drafts: list[dict] = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 0,
            "posting_date": [">=", cutoff],
            "currency": ["!=", company_currency],
        },
        fields=["name", "customer", "posting_date", "conversion_rate", "currency"],
        order_by="posting_date asc",
        limit_page_length=0,
    )

    has_isp_pe: bool = bool(frappe.db.exists("DocType", "ISP Payment Entry"))
    rate_cache: dict = {}
    updated: list[str] = []
    failed: list[str] = []
    first_traceback: str = ""
    skipped_paid = skipped_no_rate = 0

    for inv in drafts:
        if len(updated) >= limit:
            break
        try:
            if is_juridical_customer(inv.customer):
                continue

            rate_date = getdate(inv.posting_date).replace(day=1)
            key = (str(rate_date), inv.currency)
            if key not in rate_cache:
                rate_cache[key] = frappe.db.get_value(
                    "Currency Exchange",
                    {
                        "date": str(rate_date),
                        "from_currency": inv.currency,
                        "to_currency": company_currency,
                    },
                    "exchange_rate",
                    order_by="modified desc",
                )
            official = flt(rate_cache[key])

            if official <= 0:
                skipped_no_rate += 1
                continue
            if abs(official - flt(inv.conversion_rate)) <= 0.0001:
                continue

            # Ya pagada (aunque siga en borrador): no se le mueve la tasa.
            if has_isp_pe:
                isp_pe = frappe.db.get_value(
                    "ISP Payment Entry", {"sales_invoice": inv.name}, "name"
                )
                if isp_pe and frappe.db.count(
                    "ISP Payment Entry Lines", {"parent": isp_pe}
                ):
                    skipped_paid += 1
                    continue

            doc = frappe.get_doc("Sales Invoice", inv.name)
            if doc.docstatus != 0:  # cambió entre la consulta y ahora
                continue
            doc.conversion_rate = official
            doc.plc_conversion_rate = official
            doc.save(ignore_permissions=True)
            updated.append(inv.name)
        except Exception as e:
            # Una entrada de Error Log por factura y por corrida convierte a una sola
            # factura atascada en un flood: ACC-SINV-2026-21533 (con el vencimiento del
            # cronograma de pago anterior a su fecha de emisión, así que ERPNext nunca
            # la deja guardar) escribió 226 entradas entre el 4 y el 13 de agosto —el
            # 100% de esta firma—. Se acumulan y se escribe UNA sola al final de la
            # corrida, con el traceback del primer fallo.
            if not first_traceback:
                first_traceback = frappe.get_traceback()
            failed.append(f"• {inv.name} ({inv.posting_date}): {e}")

    if failed:
        omitidas: int = max(0, len(failed) - _RATE_SYNC_FAILURES_IN_LOG)
        frappe.log_error(
            "BCV: facturas cuya tasa no se pudo alinear",
            f"{len(failed)} de {len(drafts)} factura(s) en borrador no aceptaron la "
            f"tasa oficial.\n\n"
            + "\n".join(failed[:_RATE_SYNC_FAILURES_IN_LOG])
            + (f"\n… y {omitidas} más." if omitidas else "")
            + f"\n\nTraceback del primer fallo:\n{first_traceback}",
        )

    if updated:
        frappe.db.commit()
        frappe.log_error(
            "BCV: tasas de borradores alineadas",
            f"Se alineó la tasa BCV de {len(updated)} factura(s) en borrador "
            f"(omitidas por pago previo: {skipped_paid}).\n" + "\n".join(updated[:100]),
        )

    return {
        "checked": len(drafts),
        "updated": len(updated),
        "failed": len(failed),
        "skipped_paid": skipped_paid,
        "skipped_no_rate": skipped_no_rate,
    }


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

    Cuando el BCV publica una tasa con FECHA VALOR FUTURA (el próximo día
    hábil), se registra con esa fecha real además de cubrir hoy. Así la tasa
    del día siguiente ya existe antes de que ese día empiece y los procesos
    que corren a medianoche (facturación) no se quedan sin tasa.
    """
    doctype = "Currency Exchange"
    to_currency = "VEF"
    purpose = "Selling-Buying"

    api_date = getdate(rates_data.get("date"))
    today_date = getdate(nowdate())

    for from_currency, exchange_rate in rates_data.get("rates", {}).items():
        if not exchange_rate:
            continue

        targets = _resolve_rate_targets(
            api_date, today_date, from_currency,
            to_currency, exchange_rate, doctype
        )

        for target_date, target_rate in targets:
            _upsert_exchange_rate(
                doctype, purpose, from_currency,
                to_currency, target_date, target_rate
            )

    # frappe.db.set_value no dispara doc_events, así que invalidamos el caché
    # de tasas explícitamente tras la sincronización BCV.
    from l10n_ve.utils.utils import clear_exchange_rate_cache
    clear_exchange_rate_cache()


def _upsert_exchange_rate(
    doctype: str,
    purpose: str,
    from_currency: str,
    to_currency: str,
    target_date,
    target_rate,
) -> None:
    """Crea o actualiza la fila de Currency Exchange para una fecha dada."""
    exchange_name = (
        f"{formatdate(get_datetime_str(target_date), 'yyyy-MM-dd')}"
        f"-{from_currency}-{to_currency}-{purpose}"
    )

    if frappe.db.exists(doctype, exchange_name):
        frappe.db.set_value(doctype, exchange_name, "exchange_rate", target_rate)
        return

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


def _resolve_rate_targets(
    api_date,
    today_date,
    from_currency: str,
    to_currency: str,
    exchange_rate,
    doctype: str,
) -> list[tuple]:
    """Decide qué pares (fecha, tasa) hay que registrar.

    - Fecha del BCV de hoy o pasada: se registra tal cual.
    - Fecha del BCV FUTURA (fecha valor del próximo día hábil): se **precarga**
      con su fecha real —de modo que la tasa de ese día exista antes de que el
      día empiece— y, además, si hoy todavía no tiene tasa, se cubre hoy con la
      última conocida (protección original para fines de semana/feriados).

    La precarga es la que elimina la carrera de medianoche: sin ella, la tasa
    del día 1 no existía hasta que el cron corría ya entrado el día, y la
    facturación de las 00:00 emitía con la tasa del mes anterior.
    """
    if api_date <= today_date:
        return [(api_date, exchange_rate)]

    # Precarga de la fecha valor real (lo que antes se descartaba).
    targets: list[tuple] = [(api_date, exchange_rate)]

    today_already_has_rate = frappe.db.exists(doctype, {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "date": today_date,
    })

    if today_already_has_rate:
        return targets

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
        return targets

    frappe.log_error(
        "BCV Protection",
        f"Fecha futura detectada ({api_date}): se precarga con su fecha valor. "
        f"Hoy ({today_date}) se cubre con la tasa previa ({last_rate})."
    )
    targets.append((today_date, last_rate))
    return targets


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


# Años de retención de los logs de éxito. A diferencia de los logs de error
# (ruido de reintentos), los Success son el respaldo fiscal de cada emisión:
# guardan el payload enviado a HKA (incl. el string de tasa) y el numeroControl
# de la respuesta. Se conservan por el período de prescripción fiscal.
# Confirmar el valor con el área contable antes de reducirlo.
SUCCESS_LOG_RETENTION_YEARS: int = 6


def purge_old_digital_invoice_success_logs() -> None:
    """Elimina logs de éxito más antiguos que la ventana de retención fiscal.

    Los Success son el respaldo de lo que realmente se transmitió a HKA, por lo
    que solo se purgan tras el período de prescripción (no mensualmente). Se
    ejecuta el 1 de cada mes y borra lo anterior a la ventana de retención.
    """
    cutoff: str = add_years(nowdate(), -SUCCESS_LOG_RETENTION_YEARS)

    count: int = frappe.db.count(
        "VE Digital Invoice Log",
        {"status": "Success", "creation": ["<", cutoff]},
    )

    if not count:
        return

    frappe.db.delete(
        "VE Digital Invoice Log",
        {"status": "Success", "creation": ["<", cutoff]},
    )
    frappe.db.commit()
    frappe.logger("tfhka").info(
        f"Purga de retención ({SUCCESS_LOG_RETENTION_YEARS} años): "
        f"{count} logs de éxito anteriores a {cutoff} eliminados"
    )


def get_l10n_ve_settings() -> dict | None:
    """
    Obtiene la configuración propia del módulo l10n_ve_settings en site_config.json.
    """
    site_config = frappe.get_site_config()
    return site_config.get("l10n_ve_settings") or site_config.get("ve_settings")


# --- Avisos de retenciones pendientes ----------------------------------------
# Requerimiento de Galanet (Aurelys Torres, correo "Requerimiento- avisos
# Retenciones Caracas" del 29-07-2026; tarea P101 del control de peticiones):
# el aviso sale en 3 momentos — el mismo día en que se emite la factura fiscal,
# al tercer día de emitida, y en una fecha tope única que es el 22 de cada mes.

RETENTION_REMINDER_DAYS_OLD = 3
RETENTION_REMINDER_DEADLINE_DAY = 22
RETENTION_REMINDER_TEMPLATE = "Recordatorio de Retenciones Pendientes"


def _log_reminder(message: str) -> None:
    """Traza del proceso de avisos de retención.

    Va al logger de la app y no a stdout: estas funciones corren dentro de
    workers de RQ, donde los print() terminan en worker.error.log mezclados con
    el ruido de la cola.
    """
    frappe.logger("l10n_ve").info(f"[Recordatorio Retenciones] {message}")


def _fetch_customer_emails_bulk(customer_ids: list[str]) -> dict[str, list[str]]:
    """Obtiene los correos de varios clientes en una sola query (evita el N+1).

    Conserva la semántica de VECustomer.get_email_list, que era la fuente antes
    de este prefetch: el origen es el campo `email_id` del Cliente, que admite
    varias direcciones separadas por coma. Separarlas acá es obligatorio —
    Frappe solo parte por coma cuando `recipients` es un string suelto, no
    cuando la coma viene dentro de un elemento de la lista (QueueBuilder.
    _get_emails_list), así que una dirección compuesta llega entera al RCPT TO
    y rebota sin avisar.

    Retorna un dict {customer_id: [email1, email2, ...]}.
    """
    if not customer_ids:
        return {}

    rows = frappe.db.sql(
        """
        SELECT name, email_id
        FROM `tabCustomer`
        WHERE name IN %(ids)s
          AND email_id IS NOT NULL AND email_id != ''
        """,
        {"ids": customer_ids},
        as_dict=True,
    )

    result: dict[str, list[str]] = {}
    for row in rows:
        emails: list[str] = []
        seen: set[str] = set()
        for email in (row.email_id or "").split(","):
            email = email.strip()
            if not email or email.lower() in seen:
                continue
            seen.add(email.lower())
            emails.append(email)
        if emails:
            result[row.name] = emails

    return result


def _customer_needs_retention_vouchers(customer: str | None) -> bool:
    """Indica si al cliente le aplican comprobantes de retención.

    Mismo criterio que la consulta del barrido: contribuyente especial (retiene
    IVA) o con Concepto de ISLR asignado.
    """
    if not customer:
        return False

    row = frappe.db.get_value(
        "Customer", customer, ["is_special_taxpayer", "tabulator_islr"], as_dict=True
    ) or {}

    if row.get("is_special_taxpayer"):
        return True

    tabulator = (row.get("tabulator_islr") or "").strip()
    return bool(tabulator) and tabulator != "None"


def _invoice_has_retention_lines(sales_invoice: str) -> bool:
    """Indica si la factura trae líneas de retención de IVA o ISLR con monto."""
    return bool(
        frappe.db.sql(
            """
            SELECT 1
            FROM `tabSales Taxes and Charges`
            WHERE parent = %(invoice)s
              AND parenttype = 'Sales Invoice'
              AND charge_type IN ('VAT Withholding', 'ISLR')
              AND tax_amount != 0
            LIMIT 1
            """,
            {"invoice": sales_invoice},
        )
    )


def _send_retention_reminder_to_customer(
    customer: str,
    inv_list: list,
    is_production: bool,
    test_email: str,
    customer_emails_map: dict[str, list[str]],
    company_map: dict[str, str],
    email_template: object,
) -> None:
    """
    Renderiza y encola el correo de aviso de retención para un cliente específico.
    """
    from frappe.utils import fmt_money

    if not is_production:
        recipients = [test_email]
    else:
        recipients = customer_emails_map.get(customer, [])
        if not recipients:
            frappe.log_error(
                title="Recordatorio de Retenciones - Sin Correo",
                message=f"El cliente {customer} tiene facturas con retenciones pendientes pero no tiene correos configurados."
            )
            return

    company_name = company_map.get(inv_list[0].company, inv_list[0].company)

    invoices_data = []
    for inv in inv_list:
        missing_vat = False
        missing_islr = False

        if 'VAT Withholding' in (inv.charge_types or "") and inv.is_special_taxpayer and (not inv.vat_withholding_voucher_number or inv.vat_withholding_voucher_number == "None"):
            missing_vat = True

        has_islr_concept = inv.tabulator_islr and inv.tabulator_islr != "None"
        if 'ISLR' in (inv.charge_types or "") and (has_islr_concept or inv.is_special_taxpayer) and (not inv.islr_receipt_number or inv.islr_receipt_number == "None"):
            missing_islr = True

        if not missing_vat and not missing_islr:
            continue

        invoices_data.append({
            "name": inv.bill_no,
            "bill_control": inv.bill_control,
            "formatted_date": formatdate(inv.posting_date, "dd-MM-yyyy"),
            "formatted_total": fmt_money(inv.grand_total, currency=inv.currency),
            "missing_vat": missing_vat,
            "missing_islr": missing_islr
        })

    if not invoices_data:
        return

    customer_name = inv_list[0].customer_name or customer
    subject = "Recordatorio: Comprobantes de Retención Pendientes"

    try:
        subject = email_template.subject or subject
        template_html = email_template.response_html or email_template.response
        email_body = frappe.render_template(template_html, {
            "customer_name": customer_name,
            "invoices": invoices_data,
            "company": company_name
        })
    except Exception as e:
        frappe.log_error(
            title="Error al renderizar plantilla de retención",
            message=f"No se pudo renderizar la plantilla para el cliente {customer}. Error: {str(e)}"
        )
        return

    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=email_body
        )
        _log_reminder(f"Correo encolado para '{customer}' → {recipients}")
    except Exception as e:
        frappe.log_error(
            title="Error al enviar recordatorio de retención",
            message=f"No se pudo enviar el correo al cliente {customer}. Error: {str(e)}"
        )
        _log_reminder(f"Error al enviar correo al cliente '{customer}': {str(e)}")


def send_missing_retentions_reminders(sales_invoice: str | None = None, days_old: int | None = None) -> None:
    """Busca facturas de venta con retenciones pendientes y envía un correo consolidado a los clientes.

    Permite filtrar por una factura específica (sales_invoice) o por antigüedad en días (days_old).

    Optimizaciones:
    - Prefetch de correos de todos los clientes en una sola query (evita N+1).
    - Prefetch de nombres de empresa en una sola query.
    - La plantilla de correo se carga una sola vez fuera del loop.
    """
    _log_reminder("Iniciando búsqueda de facturas...")

    # 0. Requisito obligatorio: La configuración l10n_ve_settings debe existir en site_config.json
    ve_settings = get_l10n_ve_settings()
    if not ve_settings:
        _log_reminder("Omitido: No se encontró 'l10n_ve_settings' en site_config.json.")
        return

    is_production = bool(ve_settings.get("is_production_mode"))
    test_email = ve_settings.get("test_email")

    if not is_production and not test_email:
        _log_reminder("Omitido: Modo Sandbox activo (is_production_mode=0) pero falta 'test_email' en l10n_ve_settings.")
        return

    # Fragmentos de SQL fijos definidos acá mismo; los valores siempre van
    # bindeados en filter_params. No agregar fragmentos que vengan del caller.
    extra_filters = ""
    filter_params: dict = {}

    if sales_invoice:
        extra_filters += " AND si.name = %(sales_invoice)s"
        filter_params["sales_invoice"] = sales_invoice

    if days_old is not None:
        target_date = add_days(nowdate(), -days_old)
        extra_filters += " AND si.posting_date = %(target_date)s"
        filter_params["target_date"] = target_date

    # Buscar facturas de venta sometidas (docstatus=1) de clientes que tengan el check de Contribuyente Especial
    # o tengan configurado el Concepto de ISLR, con bill_no y bill_control, y comprobantes pendientes.
    query = f"""
        SELECT
            si.name, si.customer, si.customer_name, si.branch, si.company,
            si.posting_date, si.outstanding_amount, si.grand_total, si.currency,
            si.bill_no, si.bill_control,
            si.vat_withholding_voucher_number, si.islr_receipt_number,
            c.is_special_taxpayer, c.tabulator_islr,
            GROUP_CONCAT(DISTINCT stc.charge_type) as charge_types
        FROM `tabSales Invoice` si
        JOIN `tabSales Taxes and Charges` stc ON stc.parent = si.name
        JOIN `tabCustomer` c ON c.name = si.customer
        WHERE si.docstatus = 1
          AND (c.is_special_taxpayer = 1 OR (c.tabulator_islr IS NOT NULL AND c.tabulator_islr != '' AND c.tabulator_islr != 'None'))
          AND si.bill_no IS NOT NULL AND si.bill_no != ''
          AND si.bill_control IS NOT NULL AND si.bill_control != ''
          AND stc.charge_type IN ('VAT Withholding', 'ISLR')
          AND stc.tax_amount != 0
          AND (
              (stc.charge_type = 'VAT Withholding' AND (si.vat_withholding_voucher_number IS NULL OR si.vat_withholding_voucher_number = '' OR si.vat_withholding_voucher_number = 'None'))
              OR
              (stc.charge_type = 'ISLR' AND (si.islr_receipt_number IS NULL OR si.islr_receipt_number = '' OR si.islr_receipt_number = 'None'))
          )
          {extra_filters}
        GROUP BY si.name
        ORDER BY si.customer, si.posting_date DESC
    """
    invoices = frappe.db.sql(query, filter_params, as_dict=True)

    _log_reminder(f"Facturas pendientes encontradas: {len(invoices)}")

    if not invoices:
        _log_reminder("No hay facturas que requieran recordatorio. Proceso finalizado.")
        return

    # Agrupar facturas por cliente
    customer_invoices: dict[str, list] = {}
    for inv in invoices:
        customer_invoices.setdefault(inv.customer, []).append(inv)

    customer_ids = list(customer_invoices.keys())

    # --- Prefetch en lote: correos de todos los clientes (1 query) ---
    customer_emails_map: dict[str, list[str]] = {}
    if is_production:
        customer_emails_map = _fetch_customer_emails_bulk(customer_ids)

    # --- Prefetch en lote: nombres de empresa (1 query) ---
    company_ids = list({inv.company for inv in invoices if inv.company})
    company_map: dict[str, str] = {}
    if company_ids:
        rows = frappe.db.sql("""
            SELECT name, company_name FROM `tabCompany` WHERE name IN %(ids)s
        """, {"ids": company_ids}, as_dict=True)
        company_map = {r.name: r.company_name for r in rows}

    # --- Cargar la plantilla de correo una sola vez fuera del loop ---
    try:
        email_template = frappe.get_cached_doc("Email Template", RETENTION_REMINDER_TEMPLATE)
    except Exception:
        frappe.log_error(
            title="Error al enviar recordatorio de retención",
            message=f"La plantilla '{RETENTION_REMINDER_TEMPLATE}' no se encuentra en la base de datos."
        )
        return

    # --- Procesar cada cliente ---
    for customer, inv_list in customer_invoices.items():
        _send_retention_reminder_to_customer(
            customer=customer,
            inv_list=inv_list,
            is_production=is_production,
            test_email=test_email,
            customer_emails_map=customer_emails_map,
            company_map=company_map,
            email_template=email_template,
        )


def send_3_days_retention_reminders() -> None:
    """Segundo aviso: facturas a los 3 días de su posting_date.

    Solo entran las que para entonces ya tienen bill_no y bill_control (la
    consulta lo exige): si al tercer día la factura todavía no se emitió
    fiscalmente, no aplica el aviso.

    El día tope se omite: ese día sale el consolidado y no tiene sentido
    mandarle los dos correos al mismo cliente.
    """
    if getdate(nowdate()).day == RETENTION_REMINDER_DEADLINE_DAY:
        _log_reminder(
            f"Omitido: hoy es el día tope ({RETENTION_REMINDER_DEADLINE_DAY}), sale el aviso consolidado."
        )
        return

    send_missing_retentions_reminders(days_old=RETENTION_REMINDER_DAYS_OLD)


def send_monthly_deadline_retention_reminders() -> None:
    """Tercer aviso: barrido consolidado de la fecha tope (22 de cada mes).

    Se reencola en la cola `long` con timeout explícito en lugar de correr en
    línea: los cron del scheduler van a la cola `default` (timeout 300 s) y este
    barrido recorre todas las facturas pendientes encolando un correo por
    cliente, así que RQ lo mataría a mitad del loop dejando media cartera sin
    avisar y sin reintento hasta el mes siguiente.
    """
    frappe.enqueue(
        "l10n_ve.tasks.send_missing_retentions_reminders",
        queue="long",
        timeout=3600,
        now=bool(frappe.flags.in_test),
    )


def trigger_retention_reminder_on_invoice_emission(doc: object) -> None:
    """Primer aviso: encola el correo si la factura recién emitida lo amerita.

    Los filtros baratos van ANTES del enqueue a propósito. El hook corre en cada
    Sales Invoice sometida y la facturación masiva somete miles por corrida; sin
    ellos se encolaría un job por factura solo para que el worker corriera el
    join de 3 tablas y descubriera que no aplicaba.
    """
    if getattr(doc, "doctype", None) != "Sales Invoice":
        return

    if not get_l10n_ve_settings():
        return

    # Leer de la BD y no del doc en memoria: la emisión fiscal escribe bill_no y
    # bill_control con db.set_value, sin refrescar el documento.
    fiscal = frappe.db.get_value(
        "Sales Invoice", doc.name, ["bill_no", "bill_control", "customer"], as_dict=True
    ) or {}

    if not fiscal.get("bill_no") or not fiscal.get("bill_control"):
        return

    if not _customer_needs_retention_vouchers(fiscal.get("customer")):
        return

    if not _invoice_has_retention_lines(doc.name):
        return

    # enqueue_after_commit: sin esto el job sale a Redis de una y un worker
    # ocioso puede arrancarlo antes de que commitee la transacción que lo
    # originó. El barrido filtra por docstatus=1 + bill_no + bill_control, nada
    # de lo cual está visible todavía, así que no encontraría la factura y el
    # aviso se perdería en silencio.
    frappe.enqueue(
        "l10n_ve.tasks.send_missing_retentions_reminders",
        sales_invoice=doc.name,
        queue="short",
        enqueue_after_commit=True,
        now=bool(frappe.flags.in_test),
    )


def on_sales_invoice_submit(doc: object, method: str | None = None) -> None:
    """Hook que se ejecuta al someter una factura de venta (Sales Invoice)."""
    trigger_retention_reminder_on_invoice_emission(doc)


# --- Notice (7:00 / 12:00 / 16:00): documents that should have reached HKA -------


def _escape(value) -> str:
    """Escape a value for the notice.

    Done when building the context, not in the template: ``frappe.render_template``
    does NOT autoescape, so an unescaped customer name would be injected raw into the
    message. Escaping once here keeps both the template and the fallback safe, and
    lets the template stay free of ``| e`` filters that an editor could drop.
    """
    return frappe.utils.escape_html(str(value)) if value not in (None, "") else ""


def _build_unsent_context(result: dict) -> dict:
    """Presentation-ready context, shared by the template and the fallback.

    Grouped by reason because the suggested action belongs to the reason, not to each
    row: repeating it per line is noise in a table meant to be scanned.
    """
    groups: dict[str, dict] = {}
    for row in result["rows"]:
        group = groups.setdefault(
            row["reason_code"],
            {"reason": _escape(row["reason"]), "action": _escape(row["action"]), "rows": []},
        )
        group["rows"].append(
            {
                "name": _escape(row["name"]),
                "date": formatdate(row["date"], "dd-MM-yyyy"),
                "party": _escape(row["party"]),
                "amount": _escape(
                    fmt_money(row["amount"], currency=row["currency"]) if row.get("amount") else ""
                ),
                "branch": _escape(row["branch"]),
                "detail": _escape(row["detail"]),
            }
        )

    for group in groups.values():
        group["count"] = len(group["rows"])

    period: dict = result["period"]
    return {
        "period_from": formatdate(period["from"], "dd-MM-yyyy"),
        "period_to": formatdate(period["to"], "dd-MM-yyyy"),
        "as_of": period["as_of"].strftime("%H:%M"),
        "auto_send_enabled": bool(result["auto_send_enabled"]),
        "total": len(result["rows"]),
        "groups": list(groups.values()),
    }


def build_unsent_hka_documents_email(reference_datetime=None) -> tuple[str, str] | None:
    """Build the notice. Returns ``(subject, html)``, or ``None`` if nothing to report.

    Split from the sending task so the message can be inspected without a mail server
    — the local site has no outgoing account, so this is the only way to review the
    copy before it goes anywhere::

        bench --site <site> execute l10n_ve.tasks.build_unsent_hka_documents_email
    """
    from frappe.utils import now_datetime

    from l10n_ve.digital_invoice.unsent_documents import get_unsent_documents

    result: dict = get_unsent_documents(reference_datetime or now_datetime())
    if not result["rows"]:
        return None

    context: dict = _build_unsent_context(result)
    return _render_unsent_notice(context)


def _render_unsent_notice(context: dict) -> tuple[str, str]:
    """Render through the Email Template, falling back to built-in HTML.

    The template is the source of the wording: setup seeds it and accounting can edit
    it from the UI. But an alert that cannot be rendered must still go out — losing
    the message is exactly the failure this notice exists to prevent — so a missing or
    broken template degrades to the built-in layout and leaves a trace in Error Log
    instead of dropping the send.
    """
    from l10n_ve.setup import HKA_UNSENT_NOTICE_TEMPLATE

    try:
        template = frappe.get_cached_doc("Email Template", HKA_UNSENT_NOTICE_TEMPLATE)
        subject: str = frappe.render_template(template.subject, context)
        message: str = frappe.render_template(
            template.response_html or template.response, context
        )
        return subject, message
    except Exception:
        frappe.log_error(
            title="Aviso HKA: no se pudo usar la plantilla de correo",
            message=(
                f"No se pudo renderizar '{HKA_UNSENT_NOTICE_TEMPLATE}'. Se envió con el "
                f"formato de respaldo.\n\n{frappe.get_traceback()}"
            ),
        )
        return _render_unsent_fallback(context)


def _render_unsent_fallback(context: dict) -> tuple[str, str]:
    """Built-in layout. Same context as the template, so the two cannot drift apart."""
    subject: str = (
        f"Documentos sin enviar a la imprenta digital (HKA) — {context['total']} documento(s)"
    )

    parts: list[str] = [
        f"<p>Documentos con fecha entre <b>{context['period_from']}</b> y "
        f"<b>{context['period_to']}</b> que debieron enviarse a HKA y no salieron, "
        f"al corte de las {context['as_of']}.</p>"
    ]

    if not context["auto_send_enabled"]:
        parts.append(
            '<p style="padding:8px;border-left:3px solid #b00">El envío automático a HKA '
            "está <b>desactivado</b> en TFHKA Settings. Mientras siga así, ningún documento "
            "se emite solo.</p>"
        )

    for group in context["groups"]:
        parts.append(f"<h3 style=\"margin-bottom:2px\">{group['reason']} — {group['count']}</h3>")
        parts.append(f"<p style=\"margin-top:0;color:#555\">{group['action']}</p>")
        parts.append(_unsent_rows_table(group["rows"]))

    parts.append(
        '<p style="color:#777;font-size:11px">Aviso automático de l10n_ve. '
        "El detalle completo está en el reporte <i>Estado de Facturas VE HKA</i>.</p>"
    )
    return subject, "\n".join(parts)


def _unsent_rows_table(rows: list[dict]) -> str:
    """Render one group of already-escaped rows as an HTML table."""
    head: str = (
        '<tr style="text-align:left;background:#f4f4f4">'
        "<th>Documento</th><th>Fecha</th><th>Cliente / Proveedor</th>"
        "<th>Monto</th><th>Sucursal</th><th>Detalle</th></tr>"
    )

    body: list[str] = [
        "<tr>"
        f"<td>{row['name']}</td>"
        f"<td>{row['date']}</td>"
        f"<td>{row['party']}</td>"
        f"<td align=\"right\">{row['amount']}</td>"
        f"<td>{row['branch']}</td>"
        f"<td>{row['detail']}</td>"
        "</tr>"
        for row in rows
    ]

    return (
        '<table border="1" cellpadding="4" cellspacing="0" '
        'style="border-collapse:collapse;font-size:12px;width:100%">'
        f"{head}{''.join(body)}</table>"
    )


def send_unsent_hka_documents_notice() -> None:
    """Notice of documents that should have reached HKA and did not.

    Runs three times a day (7:00, 12:00 and 16:00): with a single morning pass, whatever
    jams mid-morning only surfaces the next day. Each run reports the state at that
    moment over the current month, so the later passes are not a resend of the first.

    Sends nothing when there is nothing to report, and nothing when no recipients are
    configured — both are normal states, not errors.

    Runs inline rather than re-enqueued: it is one query plus one email, unlike the
    retention sweep that loops the whole customer base and needs the ``long`` queue.
    """
    settings = frappe.get_doc("TFHKA Settings")
    recipients: list[str] = settings.get_notification_recipients()
    if not recipients:
        return

    built = build_unsent_hka_documents_email()
    if not built:
        return

    subject, message = built

    try:
        frappe.sendmail(recipients=recipients, subject=subject, message=message)
    except Exception as e:
        # An alert that cannot be delivered must not die silently: the Error Log is the
        # only channel left, and it is part of the team's review routine.
        frappe.log_error(
            title="Error al enviar el aviso de documentos sin enviar a HKA",
            message=f"Destinatarios: {recipients}. Error: {e}",
        )
