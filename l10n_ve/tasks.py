import requests
from bs4 import BeautifulSoup
import frappe

from frappe.utils import getdate, formatdate, get_datetime_str, nowdate, flt, add_years


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


def send_missing_retentions_reminders() -> None:
    """Busca facturas de venta con retenciones pendientes y envía un correo consolidado a los clientes."""
    from l10n_ve.overrides.customer import get_customer_emails
    from frappe.utils import formatdate, fmt_money

    print("[Recordatorio Retenciones] Iniciando búsqueda de facturas...")

    # 0. Requisito obligatorio: La configuración l10n_ve_settings debe existir en site_config.json
    ve_settings = get_l10n_ve_settings()
    if not ve_settings:
        print("[Recordatorio Retenciones] Omitido: No se encontró 'l10n_ve_settings' en site_config.json.")
        return

    is_production = bool(ve_settings.get("is_production_mode"))
    test_email = ve_settings.get("test_email")

    if not is_production and not test_email:
        print("[Recordatorio Retenciones] Omitido: Modo Sandbox activo (is_production_mode=0) pero falta 'test_email' en l10n_ve_settings.")
        return

    # Buscar facturas de venta sometidas (docstatus=1) de clientes que tengan el check de Contribuyente Especial (is_special_taxpayer=1)
    # o tengan configurado el Concepto de ISLR (tabulator_islr), con bill_no y bill_control, y comprobantes pendientes.
    invoices = frappe.db.sql("""
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
        GROUP BY si.name
        ORDER BY si.customer, si.posting_date DESC
    """, as_dict=True)

    print(f"[Recordatorio Retenciones] Facturas pendientes encontradas en base de datos: {len(invoices)}")

    if not invoices:
        print("[Recordatorio Retenciones] No hay facturas que requieran recordatorio. Proceso finalizado.")
        return

    # Agrupar facturas por cliente
    customer_invoices = {}
    for inv in invoices:
        customer_invoices.setdefault(inv.customer, []).append(inv)

    for customer, inv_list in customer_invoices.items():
        if not is_production:
            recipients = [test_email]
        else:
            # Obtener correos del cliente desde su ficha en producción
            try:
                recipients = get_customer_emails(customer)
            except frappe.DoesNotExistError:
                frappe.log_error(
                    title="Recordatorio de Retenciones - Cliente No Existe",
                    message=f"El cliente '{customer}' no existe en la base de datos, omitiendo recordatorio para sus facturas."
                )
                continue

            if not recipients:
                frappe.log_error(
                    title="Recordatorio de Retenciones - Sin Correo",
                    message=f"El cliente {customer} tiene facturas con retenciones pendientes pero no tiene correos configurados."
                )
                continue

        # Obtener información de la Empresa de la primera factura
        company = None
        if inv_list[0].company:
            company = frappe.db.get_value("Company", inv_list[0].company, "company_name") or inv_list[0].company

        # Preparar los datos de las facturas para el contexto de la plantilla
        invoices_data = []
        for inv in inv_list:
            missing_vat = False
            missing_islr = False
            
            # Para el IVA: El cliente debe ser Contribuyente Especial (is_special_taxpayer)
            if 'VAT Withholding' in (inv.charge_types or "") and inv.is_special_taxpayer and (not inv.vat_withholding_voucher_number or inv.vat_withholding_voucher_number == "None"):
                missing_vat = True
            
            # Para el ISLR: El cliente debe tener asignado el Concepto de ISLR (tabulator_islr) o ser Contribuyente Especial
            has_islr_concept = inv.tabulator_islr and inv.tabulator_islr != "None"
            if 'ISLR' in (inv.charge_types or "") and (has_islr_concept or inv.is_special_taxpayer) and (not inv.islr_receipt_number or inv.islr_receipt_number == "None"):
                missing_islr = True

            if not missing_vat and not missing_islr:
                continue

            invoices_data.append({
                "name": inv.bill_no,  # Mostramos el número de factura fiscal (bill_no) en lugar del correlativo interno del sistema
                "bill_control": inv.bill_control,
                "formatted_date": formatdate(inv.posting_date, "dd-MM-yyyy"),
                "formatted_total": fmt_money(inv.grand_total, currency=inv.currency),
                "missing_vat": missing_vat,
                "missing_islr": missing_islr
            })

        if not invoices_data:
            continue

        customer_name = inv_list[0].customer_name or customer

        # Obtener y renderizar la plantilla de correo general
        email_template = None
        try:
            email_template = frappe.get_doc("Email Template", "Recordatorio de Retenciones Pendientes")
        except Exception:
            pass

        subject = "Recordatorio: Comprobantes de Retención Pendientes"
        try:
            if not email_template:
                frappe.log_error(
                    title="Error al enviar recordatorio de retención",
                    message="La plantilla 'Recordatorio de Retenciones Pendientes' no se encuentra en la base de datos."
                )
                continue

            subject = email_template.subject or subject
            template_html = email_template.response_html or email_template.response
            email_body = frappe.render_template(template_html, {
                "customer_name": customer_name,
                "invoices": invoices_data,
                "company": company
            })
        except Exception as e:
            frappe.log_error(
                title="Error al renderizar plantilla de retención",
                message=f"No se pudo renderizar la plantilla para el cliente {customer}. Error: {str(e)}"
            )
            continue

        try:
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=email_body
            )
            print(f"[Recordatorio Retenciones] ✓ Correo encolado exitosamente para el cliente '{customer}' a los destinatarios {recipients}")
        except Exception as e:
            frappe.log_error(
                title="Error al enviar recordatorio de retención",
                message=f"No se pudo enviar el correo al cliente {customer}. Error: {str(e)}"
            )
            print(f"[Recordatorio Retenciones] ✗ Error al enviar correo al cliente '{customer}': {str(e)}")

