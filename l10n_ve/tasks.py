import requests
from bs4 import BeautifulSoup

import frappe
from frappe.utils import getdate, formatdate, get_datetime_str, today, nowdate, flt


def _scrape_bcv_rates():
    """
    Método de respaldo para obtener tasas haciendo web scraping a la página del BCV.
    """
    url = "https://www.bcv.org.ve/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        tasas = {}
        # ADVERTENCIA: Esta lógica de scraping es frágil y depende de la estructura HTML
        # específica del sitio web del BCV. Puede romperse si el sitio se actualiza.
        dolar_div = soup.find('div', id='dolar')
        if dolar_div and dolar_div.find('strong'):
            tasas['USD'] = dolar_div.find('strong').text.strip().replace(',', '.')

        euro_div = soup.find('div', id='euro')
        if euro_div and euro_div.find('strong'):
            tasas['EUR'] = euro_div.find('strong').text.strip().replace(',', '.')

        if 'USD' in tasas and 'EUR' in tasas:
            frappe.log_error("BCV Scraper Success", "Tasas obtenidas por web scraping exitosamente.")
            return tasas
        else:
            frappe.log_error("BCV Scraper Error", f"No se encontraron los elementos de tasa en la página. Tasas parciales: {tasas}")
            return None

    except Exception as e:
        frappe.log_error("BCV Scraper Error", f"Error al conectar o procesar la página del BCV: {e}")
        return None


def _process_rates(rates_data):
    """
    Procesa un diccionario de tasas y crea/actualiza los documentos de Currency Exchange.
    """
    doctype_name_str = "Currency Exchange"
    to_currency = "VEF"
    exchange_date = getdate(rates_data.get("date"))
    purpose = "Selling-Buying"

    for from_currency, exchange_rate in rates_data.get("rates", {}).items():
        if not exchange_rate:
            continue

        exchange_name = f"{formatdate(get_datetime_str(exchange_date), 'yyyy-MM-dd')}-{from_currency}-{to_currency}-{purpose}"

        if frappe.db.exists(doctype_name_str, exchange_name):
            frappe.db.set_value(doctype_name_str, exchange_name, "exchange_rate", exchange_rate)
        else:
            currency_exchange = frappe.new_doc(doctype_name_str)
            currency_exchange.for_buying = True
            currency_exchange.for_selling = True
            currency_exchange.date = exchange_date
            currency_exchange.to_currency = to_currency
            currency_exchange.from_currency = from_currency
            currency_exchange.exchange_rate = exchange_rate
            currency_exchange.insert(ignore_permissions=True)


@frappe.whitelist()
def create_currency_exchange() -> None:
    response_error_str = "Error obteniendo las tasas de cambio del BCV"
    error_message = frappe._("Ocurrió un error al intentar actualizar las tasas de cambio. " \
                      "Por favor, contacte al administrador del sistema.")

    bcv_endpoint = frappe.get_site_config().bcv_endpoint
    bcv_api_key = frappe.get_site_config().bcv_api_key
    
    if bcv_endpoint:
        try:
            headers = {}
            if bcv_api_key:
                headers["x-dolarvzla-key"] = bcv_api_key

            response = requests.get(bcv_endpoint, headers=headers, timeout=10)

            if response.status_code == 200:
                json_data = response.json()
                current_rates = json_data.get("current", {})
                date_str = current_rates.get("date")
                usd_rate = current_rates.get("usd")
                eur_rate = current_rates.get("eur")

                if date_str and usd_rate and eur_rate:
                    api_rates_data = {
                        "date": date_str,
                        "rates": {
                            "USD": usd_rate,
                            "EUR": eur_rate
                        }
                    }
                    frappe.log_error("BCV API Success", "Tasas obtenidas por API exitosamente.")
                    _process_rates(api_rates_data)
                    return
                else:
                    frappe.log_error("BCV API Error", f"Respuesta de API incompleta. Datos: {json_data}")
            else:
                frappe.log_error(response_error_str, f"API Status {response.status_code}: {response.text}")

        except Exception as e:
            frappe.log_error(response_error_str, f"Error con API: {e}")
    else:
        frappe.log_error("BCV API Info", "bcv_endpoint no configurado, saltando a web scraping.")

    frappe.log_error("BCV Fallback", "Iniciando fallback a web scraping.")

    scraped_rates = _scrape_bcv_rates_new()
    if scraped_rates:
        print(scraped_rates)
        _process_rates(scraped_rates)
        return

    frappe.msgprint(error_message, title=frappe._("Error"), indicator="red")


def _scrape_bcv_rates_new():
    url = "https://www.bcv.org.ve/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:        
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        rates = {}
        monedas = {'dolar': 'USD', 'euro': 'EUR'}

        for id_html, iso in monedas.items():
            div = soup.find('div', id=id_html)
            if div and div.find('strong'):
                valor_raw = div.find('strong').text.strip()
                valor_limpio = valor_raw.replace('.', '').replace(',', '.')
                rates[iso] = "{:.8f}".format(flt(valor_limpio))

        fecha_container = soup.find('span', class_='date-display-single') or \
                          soup.find('div', class_='pull-right dinamyc-date')
        
        date_val = nowdate()
        
        if fecha_container:
            fecha_raw = fecha_container.text.strip()
            
            meses = {
                "Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04",
                "Mayo": "05", "Junio": "06", "Julio": "07", "Agosto": "08",
                "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"
            }
            
            try:
                partes = fecha_raw.replace(',', '').split()
                dia = partes[1].zfill(2)
                mes = meses.get(partes[2].capitalize(), "01")
                anio = partes[3]
                date_val = f"{anio}-{mes}-{dia}"
            except Exception as e:
                print(f"    [!] Error parseando fecha: {e}. Usando fecha actual.")

        resultado = {
            'date': date_val,
            'rates': rates
        }
        
        return resultado

    except Exception as e:
        print(f"\n[X] ERROR CRÍTICO: {str(e)}")
        return None