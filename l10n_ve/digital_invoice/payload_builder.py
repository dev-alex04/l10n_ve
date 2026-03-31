import re
import json
from typing import Optional

import frappe
from frappe.utils import getdate, format_time, flt, cint
from frappe.utils.data import money_in_words


def strip_html(html: str) -> str:
    """Elimina tags HTML y limpia espacios/saltos redundantes."""
    text = re.sub(r"<br\s*/?>", ", ", html or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip(",").strip()


def to_camel_case(key: str) -> str:
    """Convierte la primera letra a minúscula (PascalCase a camelCase)"""
    if not key:
        return key
    return key[0].lower() + key[1:]


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


class TFHKAPayloadBuilder:
    def __init__(self, doc, series_doc=None) -> None:
        self.doc = doc
        self.series_doc = series_doc
        self.company_currency: str = frappe.get_cached_value(
            "Company", doc.company, "default_currency"
        ) or "VEF"
        # TFHKA solo acepta 'BSD' para el Bolívar venezolano. 'VEF' es el
        # código histórico que no existe en el catálogo de The Factory HKA.
        _TFHKA_CURRENCY_MAP = {"VEF": "BSD", "VES": "BSD"}
        self.company_currency = _TFHKA_CURRENCY_MAP.get(
            self.company_currency, self.company_currency
        )

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

    def _build_identificacion_documento(self) -> dict:
        tipo_doc = self._get_tipo_documento()
        posting_date = getdate(self.doc.posting_date).strftime("%d/%m/%Y")
        due_date = getdate(self.doc.due_date or self.doc.posting_date).strftime("%d/%m/%Y")

        raw_time = self.doc.posting_time or "12:00:00"
        try:
            from datetime import datetime as dt
            time_parts = str(raw_time).split(".")[0]
            t = dt.strptime(time_parts, "%H:%M:%S")
            time_obj = t.strftime("%I:%M:%S %p").lower()
        except Exception:
            time_obj = raw_time

        if tipo_doc == "02":
            numero_documento = self.doc.credit_note_no
        elif tipo_doc == "03":
            numero_documento = self.doc.debit_note_no
        else:
            numero_documento = self.doc.bill_no
        is_nc_or_nd = tipo_doc in ("02", "03")

        fecha_afectada = None
        monto_afectado = None
        numero_afectado = None
        if is_nc_or_nd and self.doc.return_against:
            numero_afectado = self.doc.return_against
            try:
                inv_afectada = frappe.get_cached_doc("Sales Invoice", self.doc.return_against)
                fecha_afectada = getdate(inv_afectada.posting_date).strftime("%d/%m/%Y")
                monto_afectado = "{:.2f}".format(flt(inv_afectada.base_grand_total))
                if inv_afectada.bill_no:
                    numero_afectado = inv_afectada.bill_no
            except Exception:
                pass

        comentario_afectada = None
        if is_nc_or_nd:
            comentario_afectada = "devolucion" if tipo_doc == "02" else "incremento"

        return {
            "TipoDocumento": tipo_doc,
            "NumeroDocumento": numero_documento,
            "TipoProveedor": None,
            "TipoTransaccion": None,
            "NumeroPlanillaImportacion": None,
            "NumeroExpedienteImportacion": None,
            "SerieFacturaAfectada": "" if is_nc_or_nd else None,
            "NumeroFacturaAfectada": numero_afectado,
            "FechaFacturaAfectada": fecha_afectada,
            "MontoFacturaAfectada": monto_afectado,
            "ComentarioFacturaAfectada": comentario_afectada,
            "RegimenEspTributacion": None,
            "FechaEmision": posting_date,
            "FechaVencimiento": due_date,
            "HoraEmision": time_obj,
            "Anulado": False,
            "TipoDePago": "Contado" if self.doc.is_pos else "Credito",
            "Serie": self.series_doc.tfhka_serie if self.series_doc and self.series_doc.tfhka_serie else "",
            "Sucursal": (self.series_doc.branch_code or self.series_doc.branch or "")[:6] if self.series_doc else "",
            "TipoDeVenta": "Interna",
            "Moneda": self.doc.currency
        }

    def _build_comprador(self) -> dict:
        customer = frappe.get_cached_doc("Customer", self.doc.customer)
        tax_id = customer.tax_id or "V-000000000"
        tipo_id, num_id = self._parse_tax_id(tax_id)

        direccion = strip_html(self.doc.address_display) if self.doc.address_display else "NO INFO"

        return {
            "TipoIdentificacion": tipo_id,
            "NumeroIdentificacion": num_id,
            "RazonSocial": customer.customer_name,
            "Direccion": direccion,
            "Ubigeo": None,
            "Pais": "VE",
            "Notificar": None,
            "Telefono": [self.doc.contact_mobile or "0000-0000000"],
            "Correo": [self.doc.contact_email] if self.doc.contact_email else [],
            "OtrosEnvios": None
        }

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

    def _get_iva_rate(self) -> float:
        """Extrae la alícuota IVA real desde las filas de impuestos de la factura."""
        for tax in self.doc.get("taxes", []):
            account_lower = (tax.get("account_head") or "").lower()
            description_lower = (tax.get("description") or "").lower()
            if ("iva" in account_lower or "iva" in description_lower) and flt(tax.rate) > 0:
                return flt(tax.rate)
        return 16.0

    def _build_totales(self) -> dict:
        """Totales principales en VES derivados de USD × TC.

        Se calculan primero en USD (moneda del documento) y luego se
        multiplican por la tasa de cambio para obtener bolívares.
        La fuente USD se almacena en _totales_usd para que
        TotalesOtraMoneda y DetallesItems la reutilicen sin redondeo."""
        def fmt(val):
            return "{:.2f}".format(flt(val))

        iva_rate = self._get_iva_rate()
        tc: float = flt(self.doc.conversion_rate) if self.doc.conversion_rate else 1.0
        monto_exento_total_usd = 0.0
        monto_gravado_total_usd = 0.0
        total_iva_usd = 0.0

        for item in self.doc.items:
            is_exempt = item.get("is_exempt", 0) or item.get("vat_exempt", 0)
            if is_exempt or flt(self.doc.base_total_taxes_and_charges) == 0:
                monto_exento_total_usd += flt(item.amount)
            else:
                monto_gravado_total_usd += flt(item.amount)
                item_iva_usd = flt(fmt(flt(fmt(item.amount)) * (iva_rate / 100)))
                total_iva_usd += item_iva_usd

        subtotal_usd = monto_gravado_total_usd + monto_exento_total_usd
        monto_total_con_iva_usd = subtotal_usd + total_iva_usd
        total_igtf_amount = flt(self.doc.get("total_igtf", 0.0))
        total_igtf_usd = flt(total_igtf_amount / tc, 2) if total_igtf_amount else 0.0
        total_a_pagar_usd = monto_total_con_iva_usd + total_igtf_usd

        # VES = USD * TC
        monto_gravado_total = flt(fmt(monto_gravado_total_usd * tc))
        monto_exento_total = flt(fmt(monto_exento_total_usd * tc))
        subtotal = flt(fmt(subtotal_usd * tc))
        total_iva = flt(fmt(total_iva_usd * tc))
        monto_total_con_iva = flt(fmt(monto_total_con_iva_usd * tc))
        total_a_pagar = flt(fmt(total_a_pagar_usd * tc))

        self._totales_usd = {
            "subtotal": subtotal_usd,
            "monto_gravado": monto_gravado_total_usd,
            "monto_exento": monto_exento_total_usd,
            "total_iva": total_iva_usd,
            "monto_total_con_iva": monto_total_con_iva_usd,
            "total_a_pagar": total_a_pagar_usd,
        }

        total_igtf_str = None
        if total_igtf_amount > 0:
            total_igtf_str = fmt(total_igtf_amount)

        try:
            letras = money_in_words(total_a_pagar, "VEF").lower()
        except Exception:
            letras = "monto en letras"

        return {
            "NroItems": str(len(self.doc.items)),
            "MontoGravadoTotal": fmt(monto_gravado_total),
            "MontoExentoTotal": fmt(monto_exento_total),
            "MontoPercibidoTotal": "0.00",
            "SubtotalAntesDescuento": fmt(subtotal + flt(self.doc.base_discount_amount)),
            "TotalDescuento": fmt(self.doc.base_discount_amount) if flt(self.doc.base_discount_amount) else None,
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
                "AlicuotaImp": fmt(self.doc.get("igtf_rate", 3.0)),
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

        if self.doc.payments:

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
            letras = money_in_words(total_a_pagar, self.doc.currency).lower()
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

        if monto_gravado > 0:
            impuestos.append({
                "CodigoTotalImp": "G",
                "AlicuotaImp": fmt(iva_rate),
                "BaseImponibleImp": fmt(monto_gravado),
                "ValorTotalImp": fmt(total_iva)
            })

        discount = flt(self.doc.discount_amount)

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
            "SubtotalAntesDescuento": fmt(subtotal + discount) if discount else None,
            "TotalDescuento": fmt(discount) if discount else None,
            "TotalRecargos": None,
            "ListaRecargo": None,
            "ListaDescBonificacion": None,
            "ImpuestosSubtotal": impuestos,
            "OtrosImpuestosSubtotal": None,
            "MontoTotalOTI": None,
            "MontoTotalIVAyOTI": None
        }

    def _build_items(self) -> list:
        def fmt(val): return "{:.2f}".format(flt(val))
        detalles = []
        iva_rate = self._get_iva_rate()

        for idx, item in enumerate(self.doc.items, start=1):
            is_exempt = item.get("is_exempt", 0) or item.get("vat_exempt", 0)
            item_amount = flt(fmt(item.amount))
            item_rate = flt(fmt(item.rate))

            valor_iva = 0.0
            tasa_iva = "0"
            codigo_impuesto = "E"

            if not is_exempt and flt(self.doc.base_total_taxes_and_charges) > 0:
                tasa_iva = str(int(iva_rate))
                codigo_impuesto = "G"
                valor_iva = flt(fmt(item_amount * (iva_rate / 100)))

            cantidad = str(cint(item.qty)) if item.qty == cint(item.qty) else str(item.qty)

            detalles.append({
                "NumeroLinea": str(idx),
                "CodigoCIIU": "0198",
                "CodigoPLU": item.item_code[:20],
                "IndicadorBienoServicio": "2" if "servicio" in str(item.item_group).lower() else "1",
                "Descripcion": item.item_name[:250],
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
        """Resuelve Zona (territory del customer) y Nodo (via subscription → router → ISP Nodes).

        Usa get_cached_doc para minimizar queries SQL en envíos masivos.
        """
        zona: Optional[str] = None
        nodo: Optional[str] = None

        try:
            customer_doc = frappe.get_cached_doc("Customer", self.doc.customer)
            zona = customer_doc.territory
        except Exception:
            return zona, nodo

        subscription_name: Optional[str] = self.doc.get("subscription")
        if not subscription_name:
            return zona, nodo

        service_row = next(
            (row for row in (customer_doc.get("internet_services") or [])
             if row.subscription == subscription_name),
            None
        )
        if not service_row or not service_row.router:
            return zona, nodo

        try:
            nodo = frappe.db.get_value(
                "ISP Node Routers",
                {"router": service_row.router},
                "parent"
            )
        except Exception:
            pass

        return zona, nodo

    def _build_info_adicional(self) -> list:
        """Construye el nodo InfoAdicional con datos del servicio ISP."""
        doc = self.doc
        subscription_name: str = doc.get("subscription") or ""
        contrato: str = ""
        id_servicio: str = ""

        if subscription_name:
            try:
                customer_doc = frappe.get_cached_doc("Customer", doc.customer)
                service_row = next(
                    (row for row in (customer_doc.get("internet_services") or [])
                     if row.subscription == subscription_name),
                    None
                )
                if service_row:
                    contrato = service_row.name or ""
                    id_servicio = service_row.parent or ""
            except Exception:
                pass

        direccion_servicio = strip_html(doc.address_display) if doc.address_display else ""

        tasa_bcv: str = ""
        if flt(doc.conversion_rate) > 0:
            posting_date_str = getdate(doc.posting_date).strftime("%d/%m/%Y")
            tasa_bcv = (
                f"Tasa de cambio publicado por el BCV Bs {flt(doc.conversion_rate, 4)} "
                f"por 1,00 USD de fecha valor {posting_date_str}."
            )

        periodo: str = ""
        nota_periodo: str = ""
        if subscription_name:
            try:
                sub = frappe.get_cached_doc("Subscription", subscription_name)
                if sub.current_invoice_start and sub.current_invoice_end:
                    inicio = getdate(sub.current_invoice_start).strftime("%d/%m/%Y")
                    fin = getdate(sub.current_invoice_end).strftime("%d/%m/%Y")
                    periodo = f"Desde el {inicio} hasta el {fin}"
            except Exception:
                pass

        valor_dict = {
            "Contrato": contrato,
            "DireccionServicio": direccion_servicio[:200] if direccion_servicio else "",
            "TasaCambio": tasa_bcv,
            "Periodo": periodo,
            "Zona": self.zona or "",
            "Nodo": self.nodo or "",
            "IdServicio": id_servicio,
            "Nota": nota_periodo,
        }
        valor_dict = {k: v for k, v in valor_dict.items() if v}

        # Serialize to valid JSON string
        json_str = json.dumps(valor_dict, ensure_ascii=False)

        return [{"Campo": "PDF", "Valor": json_str}]
