import re
import json
import unicodedata
from calendar import monthrange
from datetime import date
from typing import Optional

import frappe
from frappe.utils import getdate, flt, cint, get_datetime
from frappe.utils.data import money_in_words
from l10n_ve.utils.utils import is_juridical_customer, resolve_exchange_rate_date


def build_transaction_id(base: str, doc) -> str:
    """TransaccionId único para HKA a partir de ``base`` + marca de creación.

    HKA deduplica por TransaccionId: si dos documentos envían el mismo, el
    segundo se rechaza con código 201 "Documento duplicado". El ``name`` de un
    documento fiscal NO es único en el tiempo —Frappe reinicia el correlativo del
    naming series al borrar el último de la serie (revert_series_if_last)—, así
    que un name reciclado reusaría el TransaccionId de un documento ya emitido.
    Se le añade la fecha de creación del documento (AAMMDDHHMMSS): es estable por
    documento (idempotente ante reintentos del MISMO doc) y distinta entre dos
    documentos que reciclaron el mismo name (creados en instantes diferentes).

    Un documento fiscal guardado SIEMPRE tiene ``creation``; si faltara (doc en
    memoria sin insertar) se devuelve solo ``base`` para no romper el llamador.
    """
    creation = getattr(doc, "creation", None)
    if not creation:
        return base
    stamp: str = get_datetime(creation).strftime("%y%m%d%H%M%S")
    return f"{base}{stamp}"


def strip_html(html: str) -> str:
    """Elimina tags HTML y limpia espacios/saltos redundantes."""
    text = re.sub(r"<br\s*/?>", ", ", html or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip(",").strip()


def clean_address(html: str) -> str:
    """Extrae solo la primera línea de la dirección para HKA.

    Frappe construye address_display como HTML con <br> separando:
    línea1<br>Ciudad<br>Estado<br>Municipio<br>Ciudad<br>CP<br>País<br>...
    Solo necesitamos la primera línea (dirección física real).
    """
    if not html:
        return ""
    # Tomar solo el segmento antes del primer <br>
    first_line = re.split(r"<br\s*/?>", html, maxsplit=1)[0]
    # Limpiar tags HTML residuales y espacios
    first_line = re.sub(r"<[^>]+>", "", first_line)
    first_line = re.sub(r"\s+", " ", first_line)
    # Eliminar punto o coma sobrante al final
    return first_line.strip().rstrip(".,").strip()


def to_camel_case(key: str) -> str:
    """Convierte la primera letra a minúscula (PascalCase a camelCase)"""
    if not key:
        return key
    return key[0].lower() + key[1:]


from l10n_ve.digital_invoice.hka_environment import notification_emails


def clean_payload(d):
    """
    1. Elimina nulos y vacíos para evitar colapsos en el parser.
    2. Convierte las claves a camelCase estricto según el Swagger de HKA.
    """
    if isinstance(d, dict):
        return {
            to_camel_case(k): clean_payload(v)
            for k, v in d.items()
            if v is not None and v != []
        }
    elif isinstance(d, list):
        return [clean_payload(v) for v in d if v is not None]
    else:
        return d


def _resolve_geo_label(doctype: str, value: str, label_field: str) -> Optional[str]:
    """Resuelve la etiqueta legible de un registro geo (VE Municipality / VE City).

    Los campos `county`/`city` del Address son `Data` (el comportamiento de Link es
    solo del diálogo VE, sin integridad referencial en el esquema), por lo que pueden
    guardar: el name de un registro válido, texto libre, o un id huérfano. Esta función:
      - name válido        → su etiqueta legible
      - texto libre        → el texto tal cual (el registro no existe)
      - id sin etiqueta    → None (NUNCA se emite el name/hash como Zona)
    """
    label = frappe.get_cached_value(doctype, value, label_field)
    if label:
        return label
    if not frappe.get_cached_value(doctype, value, "name"):
        return value  # texto libre cargado fuera del diálogo VE (el registro no existe)
    return None  # registro existe pero sin etiqueta legible: no emitir el id/hash


def resolve_zone_from_address(customer_name: str, customer_address: Optional[str] = None) -> Optional[str]:
    """Fallback de Zona: nombre legible del municipio de la dirección (no el name/hash).

    Orden de resolución (siempre devuelve la etiqueta legible, nunca el name/hash):
      1. Address.parish → VE Parish.municipality → VE Municipality.municipality
      2. Address.county (Link a VE Municipality) → VE Municipality.municipality
      3. Address.city (Link a VE City) → VE City.city

    `county` es el municipio y suele estar cargado aunque falte la parroquia (es
    obligatorio en el diálogo VE), por lo que es el fallback principal. Si algún
    campo guarda texto libre (direcciones creadas fuera del diálogo VE) se devuelve
    ese texto tal cual.
    """
    if not customer_address:
        rows = frappe.db.sql("""
            SELECT a.name
            FROM `tabAddress` a
            JOIN `tabDynamic Link` dl ON dl.parent = a.name
            WHERE dl.link_doctype = 'Customer'
              AND dl.link_name = %s
              AND a.address_type = 'Billing'
            LIMIT 1
        """, (customer_name,), as_list=True)
        if not rows:
            return None
        customer_address = rows[0][0]

    # 1. Parroquia → municipio (cadena enlazada original)
    parish = frappe.get_cached_value("Address", customer_address, "parish")
    if parish:
        muni_id = frappe.get_cached_value("VE Parish", parish, "municipality")
        if muni_id:
            label = frappe.get_cached_value("VE Municipality", muni_id, "municipality")
            if label:
                return label

    # 2. Municipio directo desde `county` (Link a VE Municipality, requerido en el diálogo VE)
    county = frappe.get_cached_value("Address", customer_address, "county")
    if county:
        label = _resolve_geo_label("VE Municipality", county, "municipality")
        if label:
            return label

    # 3. Último recurso: ciudad/pueblo (Link a VE City)
    city = frappe.get_cached_value("Address", customer_address, "city")
    if city:
        label = _resolve_geo_label("VE City", city, "city")
        if label:
            return label

    return None


_CURRENCY_WORDS = {"BSD": "bolívares", "VES": "bolívares", "VEF": "bolívares",
                   "USD": "dólares", "EUR": "euros"}


#: Meses en mayúsculas, como los imprime la plantilla de HKA.
MONTHS_ES: tuple[str, ...] = (
    "", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
    "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)


def service_period(doc) -> tuple[date, date]:
    """Período de servicio que cobra el documento: el suyo, no el de su emisión.

    Bajo emitir-al-pagar la factura se contabiliza el día que se cobra, así que un
    borrador de agosto cobrado en septiembre llega a HKA con ``posting_date`` de
    septiembre. Esa fecha es la de emisión y tiene que coincidir con la de HKA, pero no
    dice qué mes se cobra: eso lo guarda la propia factura en ``from_date``/``to_date``,
    fijados al crearla. Antes de #537 el período se leía de la Subscription en vivo, que
    avanza sola y a veces mostraba el mes anterior; #537 lo pasó a ``posting_date`` y
    desde entonces cada factura de un mes anterior sale con el mes de emisión. En
    producción, al 10-sep-2026: 747 facturas de julio y agosto emitidas en septiembre
    decían «SEPTIEMBRE 2026».

    Sin período propio completo (una factura manual), se usa el mes de ``posting_date``,
    como hasta ahora.
    """
    start = getdate(doc.get("from_date")) if doc.get("from_date") else None
    end = getdate(doc.get("to_date")) if doc.get("to_date") else None
    if start and end and start <= end:
        return start, end
    posting_date = getdate(doc.posting_date)
    last_day = monthrange(posting_date.year, posting_date.month)[1]
    return posting_date.replace(day=1), posting_date.replace(day=last_day)


def service_period_label(start: date, end: date) -> str:
    """El mes o los meses del período, como van en la «Nota»: «AGOSTO 2026», «AGOSTO - SEPTIEMBRE 2026»."""
    if (start.year, start.month) == (end.year, end.month):
        return f"{MONTHS_ES[start.month]} {start.year}"
    if start.year == end.year:
        return f"{MONTHS_ES[start.month]} - {MONTHS_ES[end.month]} {end.year}"
    return f"{MONTHS_ES[start.month]} {start.year} - {MONTHS_ES[end.month]} {end.year}"


class TFHKAPayloadBuilder:
    def __init__(self, doc, series_doc=None, branch_code: str = "", tasa_fecha: Optional[str] = None) -> None:
        """
        Inicializa el payload builder.

        Args:
            doc: Documento de la factura.
            series_doc: Documento de la serie.
            branch_code: Código de la sucursal.
            tasa_fecha: Fecha de la tasa BCV usada en el documento (YYYY-MM-DD).
                        Si se omite, se calcula desde posting_date.
        """
        self.doc = doc
        self.series_doc = series_doc
        self.branch_code = branch_code
        self.tasa_fecha: Optional[str] = tasa_fecha
        self.company_currency: str = frappe.get_cached_value(
            "Company", doc.company, "default_currency"
        ) or "VEF"
        # TFHKA solo acepta 'BSD' para el Bolívar venezolano. 'VEF' es el
        # código histórico que no existe en el catálogo de The Factory HKA.
        _TFHKA_CURRENCY_MAP = {"VEF": "BSD", "VES": "BSD"}
        self.company_currency = _TFHKA_CURRENCY_MAP.get(
            self.company_currency, self.company_currency
        )
        self._ensure_billing_address()

    def _ensure_billing_address(self) -> None:
        """Si la factura no tiene dirección, la busca desde el Customer master."""
        if self.doc.address_display:
            return

        from frappe.contacts.doctype.address.address import get_address_display

        billing_address: list = frappe.db.sql("""
            SELECT a.name
            FROM `tabAddress` a
            JOIN `tabDynamic Link` dl ON dl.parent = a.name
            WHERE dl.link_doctype = 'Customer'
              AND dl.link_name = %s
              AND a.address_type = 'Billing'
            LIMIT 1
        """, (self.doc.customer,), as_list=True)

        if not billing_address:
            return

        self.doc.address_display = get_address_display(billing_address[0][0])

    def build_payload(self) -> dict:
        self.items_payload = self._build_items()
        self.zona, self.nodo = self._resolve_zona_and_nodo()
        payload = {
            "documentoElectronico": {
                "Encabezado": self._build_encabezado(),
                "DetallesItems": self.items_payload,
                "DetallesRetencion": None,
                "Viajes": None,
                "InfoAdicional": self._build_info_adicional(),
                "GuiaDespacho": None,
                "Transporte": None,
                "EsLote": None,
                "EsMinimo": None
            }
        }
        return clean_payload(payload)

    def _build_encabezado(self) -> dict:
        return {
            "IdentificacionDocumento": self._build_identificacion_documento(),
            "Vendedor": None,
            "Comprador": self._build_comprador(),
            "SujetoRetenido": None,
            "Tercero": None,
            "Totales": self._build_totales(),
            "TotalesRetencion": None,
            "TotalesOtraMoneda": self._build_totales_otra_moneda(),
            "Orden": None
        }

    def _get_tipo_documento(self) -> str:
        """'01' Factura, '02' Nota Crédito, '03' Nota Débito."""
        if self.doc.is_return:
            return "02"
        if self.doc.get("is_debit_note"):
            return "03"
        return "01"

    def _format_posting_time(self) -> str:
        """Formatea la hora de contabilización al formato HH:MM:SS am/pm."""
        raw_time = self.doc.posting_time or "12:00:00"
        try:
            from frappe.utils import get_time
            return get_time(str(raw_time)).strftime("%I:%M:%S %p").lower()
        except Exception:
            return str(raw_time).split(".")[0]

    def _get_datos_factura_afectada(self) -> tuple[str, str, str]:
        """
        Retorna (fecha, monto_fiscal, numero) de la factura original.
        - monto_fiscal = base_net_total + IVA (excluye retenciones Deduct).
        - numero = bill_no fiscal de la factura original.
        """
        ref = self.doc.return_against
        numero_afectado: str = ref
        fecha_afectada: str = ""
        monto_fiscal: str = "0.00"

        try:
            inv = frappe.get_cached_doc("Sales Invoice", ref)
            fecha_afectada: str = getdate(inv.posting_date).strftime("%d/%m/%Y")

            iva_add = sum(
                flt(t.base_tax_amount)
                for t in inv.get("taxes", [])
                if getattr(t, "add_deduct_tax", "") == "Add"
            )
            monto_fiscal: str = "{:.2f}".format(flt(inv.base_net_total) + iva_add)

            if not inv.bill_no:
                frappe.throw(
                    f"La factura original <b>{ref}</b> no tiene número fiscal "
                    f"asignado (<b>Número de NC</b>). Verifique que fue emitida "
                    f"correctamente ante TFHKA."
                )
            numero_afectado = inv.bill_no

        except frappe.ValidationError:
            raise
        except Exception as e:
            frappe.throw(
                f"No se pudo obtener los datos de la factura original "
                f"<b>{ref}</b>: {e}"
            )

        return fecha_afectada, monto_fiscal, numero_afectado

    def _validate_motivo_nc(self) -> str:
        """Retorna el motivo de la NC/ND. Lanza error si está vacío."""
        motivo: str = (self.doc.get("reason") or "").strip()
        if not motivo:
            frappe.throw(
                "El campo <b>Motivo</b> es obligatorio antes de emitir una "
                "Nota de Crédito/Débito electrónica. Indique el motivo en el "
                "formulario de la NC/ND y vuelva a intentarlo."
            )
        return motivo

    def _get_serie_factura_afectada(self) -> str:
        """
        Consulta el log de facturación digital de la factura original
        para obtener la serie confirmada por TFHKA.
        Lanza error si no se encuentra o si no existe log exitoso.
        """
        ref = self.doc.return_against
        serie: str = ""
        try:
            log_raw = frappe.db.get_value(
                "VE Digital Invoice Log",
                {"sales_invoice": ref, "status": "Success"},
                "response_received",
                order_by="creation desc",
            )
            if log_raw:
                try:
                    parsed = json.loads(log_raw)
                    if isinstance(parsed, dict):
                        resultado = parsed.get("resultado") or {}
                        serie = resultado.get("serie") or ""
                except Exception:
                    pass

            # Fallback: check if the Sales Invoice remarks contain the HKA response json
            if not serie:
                inv_remarks = frappe.db.get_value("Sales Invoice", ref, "remarks")
                if inv_remarks:
                    try:
                        parsed = json.loads(inv_remarks)
                        if isinstance(parsed, dict):
                            resultado = parsed.get("resultado") or {}
                            serie = resultado.get("serie") or ""
                    except Exception:
                        pass
        except Exception as e:
            frappe.throw(
                f"Error al consultar el log de facturación digital "
                f"para <b>{ref}</b>: {e}"
            )

        if not serie:
            frappe.throw(
                f"No se puede determinar la <b>Serie</b> de la factura original "
                f"<b>{ref}</b>. La factura debe haber sido emitida electrónicamente "
                f"(TFHKA) antes de poder crear una Nota de Crédito/Débito. "
                f"Verifique que exista un log exitoso en <b>VE Digital Invoice Log</b> "
                f"para dicha factura."
            )
        return serie



    def _build_identificacion_documento(self) -> dict:
        tipo_doc: str = self._get_tipo_documento()
        is_nc_or_nd: bool = tipo_doc in ("02", "03")
        is_third_party: bool = (
            getattr(self.series_doc, "operation_mode", "Internal") == "Third Party"
        )

        posting_date: str = getdate(self.doc.posting_date).strftime("%d/%m/%Y")
        numero_documento: str = "" if is_third_party else (self.doc.bill_no or "")

        fecha_afectada = monto_afectado = numero_afectado = comentario_afectada = None
        serie_factura_afectada: str = ""

        if is_nc_or_nd:
            comentario_afectada = self._validate_motivo_nc()

        if is_nc_or_nd and self.doc.return_against:
            fecha_afectada, monto_afectado, numero_afectado = self._get_datos_factura_afectada()
            serie_factura_afectada = self._get_serie_factura_afectada()

        return {
            "TipoDocumento": tipo_doc,
            "NumeroDocumento": numero_documento,
            "TipoProveedor": None,
            "TipoTransaccion": None,
            "NumeroPlanillaImportacion": None,
            "NumeroExpedienteImportacion": None,
            "SerieFacturaAfectada": serie_factura_afectada if is_nc_or_nd else None,
            "NumeroFacturaAfectada": numero_afectado,
            "FechaFacturaAfectada": fecha_afectada,
            "MontoFacturaAfectada": monto_afectado,
            "ComentarioFacturaAfectada": comentario_afectada,
            "RegimenEspTributacion": None,
            "FechaEmision": posting_date,
            "FechaVencimiento": posting_date,
            "HoraEmision": self._format_posting_time(),
            "Anulado": False,
            "TipoDePago": "Contado" if self.doc.get("is_pos") else "Credito",
            "Serie": getattr(self.series_doc, "serie", "") or "",
            "Sucursal": self._resolve_branch_code(),
            "TipoDeVenta": "Interna",
            "Moneda": self.doc.currency,
            "TransaccionId": (
                build_transaction_id("".join(filter(str.isalnum, self.doc.name)), self.doc)
                if is_third_party else None
            ),
        }


    def _resolve_branch_code(self) -> str:
        """Retorna el branch_code ya resuelto desde la tabla hija (máximo 6 car.)"""
        return str(self.branch_code)[:6] if self.branch_code else ""

    def _build_comprador(self) -> dict:
        customer = frappe.get_cached_doc("Customer", self.doc.customer)

        if not customer.tax_id:
            frappe.throw(
                f"El cliente '{customer.customer_name}' no tiene RIF/Cédula (Tax ID) configurado. "
                "Es obligatorio para la facturación electrónica.",
                title="RIF del Cliente Requerido"
            )
        tipo_id, num_id = self._parse_tax_id(customer.tax_id)

        if not self.doc.address_display:
            frappe.throw(
                f"El cliente '{customer.customer_name}' no tiene dirección de facturación. "
                "Es obligatoria para la facturación electrónica.",
                title="Dirección del Cliente Requerida"
            )
        direccion = clean_address(self.doc.address_display)

        if not self.doc.contact_mobile:
            frappe.throw(
                f"El cliente '{customer.customer_name}' no tiene teléfono de contacto. "
                "Es obligatorio para la facturación electrónica.",
                title="Teléfono del Cliente Requerido"
            )

        return {
            "TipoIdentificacion": tipo_id,
            "NumeroIdentificacion": num_id,
            "RazonSocial": self._sanitize_razon_social(customer.customer_name),
            "Direccion": direccion,
            "Ubigeo": None,
            "Pais": "VE",
            "Notificar": None,
            "Telefono": [self.doc.contact_mobile],
            # En un sitio que no es producción el correo del cliente se desvía al de
            # pruebas. La regla vive en hka_environment para que el payload y la vista
            # previa digan lo mismo.
            "Correo": notification_emails(
                [e.strip() for e in (self.doc.contact_email or "").split(",") if e.strip()]
            ),
            "OtrosEnvios": None
        }

    @staticmethod
    def _sanitize_razon_social(name: str) -> str:
        """Limpia la razón social para cumplir con el formato requerido por HKA."""
        cleaned: str = " ".join((name or "").split())
        return cleaned[:300].strip()

    @staticmethod
    def _parse_tax_id(tax_id: str) -> tuple:
        """
        Extrae tipo y número de identificación fiscal.
        Soporta formatos: V-12345678, J123456789, V-12345678-9, G20000001-0, etc.
        """
        cleaned = (tax_id or "").strip().upper()
        if not cleaned:
            return "V", "000000000"

        tipo = cleaned[0] if cleaned[0] in ("V", "E", "J", "G", "P", "C") else "V"
        resto = cleaned[1:]
        numero = re.sub(r"[^0-9]", "", resto)

        return tipo, numero or "000000000"

    def _get_igtf_rate(self) -> float:
        """Obtiene la tasa IGTF desde la factura o desde la configuración fiscal."""
        rate: float = flt(self.doc.get("igtf_rate"))
        if rate:
            return rate
        return flt(
            frappe.get_cached_doc("Venezuela Account Settings").igtf_rate
        ) or 3.0

    def _get_iva_rate(self) -> float:
        """Extrae la alícuota IVA real desde las filas de impuestos de la factura."""
        for tax in self.doc.get("taxes", []):
            if (tax.get("charge_type") == "VAT"
                    and (tax.get("add_deduct_tax") or "Add") == "Add"
                    and flt(tax.rate) > 0):
                return flt(tax.rate)
        for tax in self.doc.get("taxes", []):
            account_lower = (tax.get("account_head") or "").lower()
            description_lower = (tax.get("description") or "").lower()
            if ("iva" in account_lower or "iva" in description_lower) and flt(tax.rate) > 0:
                return flt(tax.rate)
        return 16.0

    def _monto_en_letras(self, amount: float, currency: str) -> str:
        from num2words import num2words
        entero = int(flt(amount))
        centimos = cint(round((flt(amount) - entero) * 100))
        moneda = _CURRENCY_WORDS.get(currency, currency.lower())
        try:
            letras = f"{num2words(entero, lang='es')} {moneda}"
            letras += f" con {num2words(centimos, lang='es')} céntimos"
            return letras
        except Exception:
            return money_in_words(amount, currency).lower()

    def _build_totales(self) -> dict:
        """Totales principales en VES usando campos base_* almacenados.

        Los montos VEF se leen directamente de base_net_total y
        base_tax_amount de la factura (fuente de verdad), garantizando
        que HKA reciba exactamente lo que la factura muestra.
        La fuente USD se almacena en _totales_usd para que
        TotalesOtraMoneda y DetallesItems la reutilicen sin redondeo."""
        def fmt(val):
            return "{:.2f}".format(flt(val))

        iva_rate = self._get_iva_rate()
        tc: float = flt(self.doc.conversion_rate) if self.doc.conversion_rate else 1.0

        # USD: montos leídos directamente del documento (fuente de verdad).
        # net_total, total_exempt y tax.tax_amount son calculados por ERPNext
        # en un solo paso, sin redondeo intermedio por ítem.
        monto_exento_total_usd: float = flt(self.doc.get("total_exempt", 0.0))
        subtotal_usd: float = flt(self.doc.net_total)
        monto_gravado_total_usd: float = flt(subtotal_usd - monto_exento_total_usd)

        total_iva_usd: float = 0.0
        for tax in self.doc.get("taxes", []):
            if tax.get("charge_type") == "VAT" and flt(tax.rate) > 0:
                total_iva_usd += flt(tax.tax_amount)

        monto_total_con_iva_usd: float = flt(subtotal_usd + total_iva_usd)
        total_igtf_amount: float = flt(self.doc.get("total_igtf", 0.0))
        total_igtf_usd: float = flt(total_igtf_amount / tc, 2) if total_igtf_amount else 0.0
        total_a_pagar_usd: float = flt(monto_total_con_iva_usd + total_igtf_usd)

        # VES: montos leídos de campos base_* almacenados en la factura.
        # Evita recalcular desde USD × TC, eliminando diferencias por
        # redondeo entre la factura y lo enviado a HKA.
        base_tax_amount_ves: float = 0.0
        for tax in self.doc.get("taxes", []):
            if tax.get("charge_type") == "VAT" and flt(tax.rate) > 0:
                base_tax_amount_ves += flt(tax.base_tax_amount)

        # base_total_exempt (VEF) es la fuente de verdad del monto exento: se calcula
        # por línea (base_net_amount) en calculate_total_exempt y se respalda en los
        # históricos vía el patch backfill_base_total_exempt.
        monto_exento_total = flt(self.doc.get("base_total_exempt", 0.0), 2)
        monto_gravado_total = flt(flt(self.doc.base_net_total) - monto_exento_total, 2)

        subtotal = flt(self.doc.base_net_total, 2)
        total_iva = flt(base_tax_amount_ves, 2)
        monto_total_con_iva = flt(subtotal + total_iva, 2)
        total_a_pagar = flt(monto_total_con_iva + total_igtf_amount, 2)

        self._totales_usd = {
            "subtotal": subtotal_usd,
            "monto_gravado": monto_gravado_total_usd,
            "monto_exento": monto_exento_total_usd,
            "total_iva": total_iva_usd,
            "monto_total_con_iva": monto_total_con_iva_usd,
            "total_a_pagar": total_a_pagar_usd,
            "base_igtf": flt(self.doc.get("base_amount_igtf", 0.0)) / tc if total_igtf_amount and tc > 0 else 0.0,
            "total_igtf": total_igtf_usd,
            "igtf_rate": self._get_igtf_rate(),
        }

        total_igtf_str = None
        if total_igtf_amount > 0:
            total_igtf_str = fmt(total_igtf_amount)

        try:
            letras = self._monto_en_letras(total_a_pagar, "VES")
        except Exception:
            letras = "monto en letras"

        is_nc = bool(self.doc.is_return)
        descuento_base = flt(self.doc.base_discount_amount)

        return {
            "NroItems": str(len(self.doc.items)),
            "MontoGravadoTotal": fmt(monto_gravado_total),
            "MontoExentoTotal": fmt(monto_exento_total),
            "MontoPercibidoTotal": "0.00",
            "SubtotalAntesDescuento": fmt(subtotal + descuento_base),
            "TotalDescuento": fmt(descuento_base) if descuento_base else ("0.00" if is_nc else None),
            "TotalRecargos": None,
            "Subtotal": fmt(subtotal),
            "TotalIVA": fmt(total_iva),
            "MontoTotalConIVA": fmt(monto_total_con_iva),
            "TotalAPagar": fmt(total_a_pagar),
            "MontoEnLetras": letras,
            "ListaRecargo": None,
            "ListaDescBonificacion": None,
            "ImpuestosSubtotal": self._build_impuestos_subtotal(monto_gravado_total, monto_exento_total, total_iva),
            "OtrosImpuestosSubtotal": None,
            "FormasPago": self._build_formas_pago(total_a_pagar),
            "TotalIGTF": total_igtf_str,
            "TotalIGTF_VES": None,
            "MontoTotalOTI": None,
            "MontoTotalIVAyOTI": None
        }

    def _build_impuestos_subtotal(self, monto_gravado: float, monto_exento: float, total_iva: float) -> list:
        def fmt(val): return "{:.2f}".format(flt(val))
        iva_rate = self._get_iva_rate()
        impuestos = []

        if monto_exento > 0:
            impuestos.append({
                "CodigoTotalImp": "E",
                "AlicuotaImp": "00.00",
                "BaseImponibleImp": fmt(monto_exento),
                "ValorTotalImp": "00.00"
            })

        if flt(self.doc.get("total_igtf", 0.0)) > 0:
            base_igtf = flt(self.doc.get("base_amount_igtf", 0.0))
            impuestos.append({
                "CodigoTotalImp": "IGTF",
                "AlicuotaImp": fmt(self._get_igtf_rate()),
                "BaseImponibleImp": fmt(base_igtf),
                "ValorTotalImp": fmt(self.doc.total_igtf)
            })

        if monto_gravado > 0:
            impuestos.append({
                "CodigoTotalImp": "G",
                "AlicuotaImp": fmt(iva_rate),
                "BaseImponibleImp": fmt(monto_gravado),
                "ValorTotalImp": fmt(total_iva)
            })

        return impuestos

    def _build_formas_pago(self, total_a_pagar_bsd: float) -> list:
        def fmt(val): return "{:.2f}".format(flt(val))
        formas = []

        if self.doc.get("payments"):

            for p in self.doc.payments:
                forma_codigo = "01"
                mode = str(p.mode_of_payment).lower()
                if "efectivo" in mode and "usd" in mode:
                    forma_codigo = "09"
                elif "efectivo" in mode:
                    forma_codigo = "08"
                elif "movil" in mode or "móvil" in mode:
                    forma_codigo = "02"
                elif "debito" in mode or "débito" in mode:
                    forma_codigo = "05"
                elif "credito" in mode or "crédito" in mode:
                    forma_codigo = "06"

                formas.append({
                    "Descripcion": p.mode_of_payment[:30],
                    "Fecha": getdate(self.doc.posting_date).strftime("%d/%m/%Y"),
                    "Forma": forma_codigo,
                    "Monto": fmt(flt(p.amount) * flt(self.doc.conversion_rate)),
                    "Moneda": self.company_currency,
                    "TipoCambio": "1.0000"
                })
        else:
            formas.append({
                "Descripcion": "Acuerdo Crediticio",
                "Fecha": getdate(self.doc.posting_date).strftime("%d/%m/%Y"),
                "Forma": "99",
                "Monto": fmt(total_a_pagar_bsd),
                "Moneda": self.company_currency,
                "TipoCambio": "1.0000"
            })
        return formas

    def _build_totales_otra_moneda(self) -> Optional[dict]:
        """TotalesOtraMoneda en USD, tomados directamente de _totales_usd
        para que cuadren exactamente con DetallesItems (ambos en USD)."""
        if self.doc.currency == frappe.get_cached_value("Company", self.doc.company, "default_currency"):
            return None

        def fmt(val): return "{:.2f}".format(flt(val))

        tc: float = flt(self.doc.conversion_rate)
        if tc <= 0:
            return None

        iva_rate = self._get_iva_rate()
        tipo_cambio = "{:.4f}".format(tc)
        usd = self._totales_usd

        monto_gravado = flt(usd["monto_gravado"], 2)
        monto_exento = flt(usd["monto_exento"], 2)
        subtotal = flt(usd["subtotal"], 2)
        total_iva = flt(usd["total_iva"], 2)
        monto_total_con_iva = flt(usd["monto_total_con_iva"], 2)
        total_a_pagar = flt(usd["total_a_pagar"], 2)

        try:
            letras = self._monto_en_letras(total_a_pagar, self.doc.currency)
        except Exception:
            letras = "monto en letras"

        impuestos = []
        if monto_exento > 0:
            impuestos.append({
                "CodigoTotalImp": "E",
                "AlicuotaImp": "00.00",
                "BaseImponibleImp": fmt(monto_exento),
                "ValorTotalImp": "00.00"
            })

        if flt(usd.get("total_igtf", 0.0)) > 0:
            impuestos.append({
                "CodigoTotalImp": "IGTF",
                "AlicuotaImp": fmt(usd.get("igtf_rate", 3.0)),
                "BaseImponibleImp": fmt(usd.get("base_igtf", 0.0)),
                "ValorTotalImp": fmt(usd.get("total_igtf", 0.0))
            })

        if monto_gravado > 0:
            impuestos.append({
                "CodigoTotalImp": "G",
                "AlicuotaImp": fmt(iva_rate),
                "BaseImponibleImp": fmt(monto_gravado),
                "ValorTotalImp": fmt(total_iva)
            })

        discount = flt(self.doc.discount_amount)
        is_nc = bool(self.doc.is_return)

        return {
            "Moneda": self.doc.currency,
            "TipoCambio": tipo_cambio,
            "MontoGravadoTotal": fmt(monto_gravado),
            "MontoPercibidoTotal": "0.00",
            "MontoExentoTotal": fmt(monto_exento),
            "Subtotal": fmt(subtotal),
            "TotalAPagar": fmt(total_a_pagar),
            "TotalIVA": fmt(total_iva),
            "MontoTotalConIVA": fmt(monto_total_con_iva),
            "MontoEnLetras": letras,
            "SubtotalAntesDescuento": fmt(subtotal + discount) if discount else (fmt(subtotal) if is_nc else None),
            "TotalDescuento": fmt(discount) if discount else ("0.00" if is_nc else None),
            "TotalRecargos": None,
            "ListaRecargo": None,
            "ListaDescBonificacion": None,
            "ImpuestosSubtotal": impuestos,
            "OtrosImpuestosSubtotal": None,
            "MontoTotalOTI": None,
            "MontoTotalIVAyOTI": None
        }

    def _resolve_tfhka_code(self, item_code: str) -> str:
        """Busca el codigo TFHKA del Subscription Plan asociado al item.

        Lanza frappe.throw si no existe el código asignado.
        """
        code: Optional[str] = frappe.get_cached_value(
            "Subscription Plan", {"item": item_code}, "code"
        )
        if not code:
            frappe.throw(
                f"El artículo '{item_code}' no tiene un código TFHKA asignado en su Plan de Suscripción. "
                "Asigne el código antes de enviar la factura a la imprenta digital."
            )
        return code[:20]

    def _build_items(self) -> list:
        def fmt(val): return "{:.2f}".format(flt(val))
        detalles = []
        iva_rate = self._get_iva_rate()

        has_vat_charge = any(
            tax.get("charge_type") == "VAT"
            and (tax.get("add_deduct_tax") or "Add") == "Add"
            and flt(tax.rate) > 0
            for tax in self.doc.get("taxes", [])
        )

        for idx, item in enumerate(self.doc.items, start=1):
            is_exempt = item.get("is_exempt", 0) or item.get("vat_exempt", 0)
            item_amount = flt(item.amount, 2)
            item_rate = flt(item.rate, 2)

            valor_iva = 0.0
            tasa_iva = "0"
            codigo_impuesto = "E"

            if not is_exempt and has_vat_charge:
                tasa_iva = str(int(iva_rate))
                codigo_impuesto = "G"
                valor_iva = flt(item_amount * (iva_rate / 100), 2)

            cantidad = str(cint(item.qty)) if item.qty == cint(item.qty) else str(item.qty)

            descripcion_item = item.item_name or ""
            # SENIAT prohíbe la palabra "Total" en la descripción de los ítems
            descripcion_item = re.sub(r'(?i)\btotal\b', '', descripcion_item).strip()

            detalles.append({
                "NumeroLinea": str(idx),
                "CodigoCIIU": "0198",
                "CodigoPLU": self._resolve_tfhka_code(item.item_code),
                "IndicadorBienoServicio": "2" if "servicio" in str(item.item_group).lower() else "1",
                "Descripcion": descripcion_item[:250],
                "Cantidad": cantidad,
                "UnidadMedida": "94",
                "PrecioUnitario": fmt(item_rate),
                "PrecioUnitarioDescuento": None,
                "MontoBonificacion": None,
                "DescripcionBonificacion": None,
                "DescuentoMonto": "0.00",
                "RecargoMonto": "0",
                "PrecioItem": fmt(item_amount),
                "PrecioAntesDescuento": fmt(item_amount),
                "CodigoImpuesto": codigo_impuesto,
                "TasaIVA": tasa_iva,
                "ValorIVA": fmt(valor_iva),
                "ValorTotalItem": fmt(item_amount + valor_iva),
                "InfoAdicionalItem": [],
                "ListaItemOTI": None
            })

        return detalles

    def _resolve_zona_and_nodo(self) -> tuple:
        """Resuelve Zona (territory del customer) y Nodo (el Nodo es dominio ISP, lo provee domina_isp vía monkeypatch).

        Para VE Sales Credit Note (sin campo subscription), intenta heredar
        el número de factura original (bill_no) para reportarlo.
        Usa get_cached_doc para minimizar queries SQL en envíos masivos.
        """
        zona: Optional[str] = None
        nodo: Optional[str] = None

        try:
            customer_doc = frappe.get_cached_doc("Customer", self.doc.customer)
            zona = customer_doc.territory
        except Exception:
            return zona, nodo

        if not zona:
            zona = resolve_zone_from_address(self.doc.customer, self.doc.get("customer_address"))

        if not self.doc.get("subscription") and self.doc.get("return_against"):
            bill_no = frappe.db.get_value(
                "Sales Invoice",
                self.doc.return_against,
                "bill_no"
            )
            self._bill_no_original = bill_no or ""

        return zona, nodo

    def _build_info_adicional(self) -> list:
        """Construye el nodo InfoAdicional con un objeto por cada dato.

        La API de HKA exige:
        - Cada entrada es un objeto {"Campo": campo, "Valor": valor}.
        - El valor debe ser texto plano alfanumérico (sin {}, '' ni JSON).
        - Máximo 255 caracteres por campo y por valor.
        """
        doc = self.doc
        subscription_name: str = doc.get("subscription") or ""

        # RIF del cliente como identificador del servicio (ej. J304858906)
        id_servicio: str = doc.get("tax_id") or ""

        direccion_servicio = clean_address(doc.address_display) if doc.address_display else ""

        tasa_bcv: str = ""
        if flt(doc.conversion_rate) > 0:
            # tasa_fecha explícita (capturada antes de actualizar posting_date a hoy).
            # Fallback: si no se proporcionó, se calcula con la misma regla fiscal
            # que _compute_tasa_fecha (evita romper llamadas sin el parámetro).
            if self.tasa_fecha:
                fecha_valor = getdate(self.tasa_fecha)
            elif is_juridical_customer(doc.customer):
                # Fecha real de la tasa que porta el documento, no el posting_date:
                # la tasa del jurídico se actualiza al primer pago.
                fecha_valor = getdate(
                    resolve_exchange_rate_date(flt(doc.conversion_rate), doc.currency)
                    or doc.posting_date
                )
            else:
                fecha_valor = getdate(doc.posting_date).replace(day=1)

            fecha_valor_str = fecha_valor.strftime("%d/%m/%Y")
            tasa_bcv = (
                f"Tasa de cambio publicado por el BCV Bs {flt(doc.conversion_rate, 4)} "
                f"por 1,00 USD de fecha valor {fecha_valor_str}."
            )

        # «Periodo» y «Nota» dicen qué mes se cobra, no cuándo se emite: ver service_period.
        period_start, period_end = service_period(doc)

        notes: str = " ".join(str(doc.get("notes") or "").replace('"', "").split())
        period_default = service_period_label(period_start, period_end)
        nota_periodo = notes or period_default

        periodo: str = f"Desde el {period_start:%d/%m/%Y} hasta el {period_end:%d/%m/%Y}"

        coletilla_a: str = (
            "En los casos en que la base imponible de la venta o prestacion de servicio "
            "estuviere expresada en moneda extranjera, se establecera la equivalencia en "
            "moneda nacional, al tipo de cambio corriente en el mercado que ocurra el "
            "hecho imponible, salvo "
        )
        coletilla_b: str = (
            "que este ocurra en un dia no habil para el sector financiero, en cuyo caso "
            "se aplicara el vigente en el dia habil inmediatamente siguiente al de la "
            "operacion. ART. 25 Ley de I.V.A. G.O Nro 6.152 de fecha 18/11/2014"
        )

        # Validaciones de campos que no pueden estar vacíos
        if not direccion_servicio:
            frappe.throw("La dirección de facturación del cliente está vacía y es obligatoria para la facturación electrónica.")

        if not id_servicio:
            frappe.throw("El ID de Servicio (RIF/Cédula) del cliente es obligatorio.")

        if not self.zona:
            frappe.throw("El cliente no tiene asignada una 'Zona', campo requerido para HKA.")

        serie: str = getattr(self.series_doc, "serie", "") or ""
        if not serie:
            frappe.throw(
                "La serie de facturación no tiene el campo 'Serie' configurado. "
                "Es obligatorio para la facturación electrónica.",
                title="Serie Requerida"
            )

        # Construir y retornar el string de diccionario único (modo "PDF")
        # ya que la plantilla de impresión de TFHKA evalúa este string internamente.

        dict_pdf = {"DireccionServicio": direccion_servicio}
        dict_pdf["Serie"] = serie
        dict_pdf["TasaCambio"] = tasa_bcv
        dict_pdf["Periodo"] = periodo if periodo else f"Desde {period_default}"

        bill_no_original: str = getattr(self, "_bill_no_original", "")
        if bill_no_original:
            dict_pdf["FacturaOriginal"] = bill_no_original

        dict_pdf["Zona"] = self.zona
        dict_pdf["Nodo"] = self.nodo or ""
        dict_pdf["IdServicio"] = id_servicio
        dict_pdf["Nota"] = nota_periodo
        dict_pdf["coletilla2"] = f"{coletilla_a} {coletilla_b}"

        # Convertir a string de python-like dict (con comillas simples) para que el parser
        # de The Factory HKA no falle en su plantilla
        sanitized: dict = {
            k: v.replace("'", "") if isinstance(v, str) else v
            for k, v in dict_pdf.items()
        }
        json_str = json.dumps(sanitized, ensure_ascii=False).replace('"', "'")

        return [
            {"Campo": "PDF", "Valor": json_str}
        ]
