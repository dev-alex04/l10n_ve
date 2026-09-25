"""Payload del documento fiscal 04 de HKA: Orden de Entrega o Guía de Despacho.

Es un solo tipo de documento con dos caras. Lo único que las separa es el campo
`esGuiaDespacho` del nodo `GuiaDespacho` ("1" guía, "0" orden), que cambia el título del
impreso. Sale de dos doctypes de ERPNext:

- **Delivery Note**, la nota de entrega a un cliente. Es un documento de venta con la misma
  forma que la factura --cliente, tasa, `base_*`, impuestos, ítems con precio--, así que su
  builder hereda de `TFHKAPayloadBuilder` y los montos fiscales se arman con el MISMO código
  que la factura. Solo cambia lo que no le corresponde a una entrega: no hay formas de pago,
  el código del ítem no sale de un plan de suscripción y la información adicional no es la
  del servicio de internet.
- **Stock Entry** de propósito *Material Transfer*, el traslado entre almacenes. No tiene
  cliente ni impuestos: el receptor es la propia empresa y los ítems van a su costo de
  valoración, exentos, en la moneda de la empresa. Su builder es propio.

Los nodos del 04 (`GuiaDespacho`, la identificación con la fecha de emisión y la
información adicional) son comunes y viven en `DispatchNodesMixin`. El nodo `Transporte`
no se manda: la regla de validación lo marca opcional, y lo que describe --conductor,
vehículo y transportista-- ya viaja dentro de `GuiaDespacho`.
"""

from __future__ import annotations

import datetime
import json
import re

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import (
    get_company_address,
    get_default_address,
    render_address,
)
from frappe.utils import cint, flt, getdate, now_datetime

from l10n_ve.digital_invoice.hka_environment import notification_emails
from l10n_ve.digital_invoice.payload_builder import (
    TFHKAPayloadBuilder,
    build_transaction_id,
    clean_address,
    clean_payload,
    hka_currency_code,
    strip_html,
)
from l10n_ve.utils.utils import resolve_exchange_rate_date

#: Catálogo 1 del SENIAT: Orden de Entrega o Guía de Despacho.
DISPATCH_DOCUMENT_TYPE: str = "04"

DELIVERY_ORDER: str = "Orden de Entrega"
DISPATCH_GUIDE: str = "Guía de Despacho"

#: Motivos del catálogo 13 que exigen describir el servicio o la causa.
REASONS_NEEDING_DESCRIPTION: tuple[str, ...] = ("Reparación o perfeccionamiento", "Otras causas")

#: Actividad económica que declara la factura en cada ítem (`TFHKAPayloadBuilder._build_items`).
#: El emisor es el mismo, así que el traslado declara la misma.
_CIIU_CODE: str = "0198"

#: Unidad de medida del catálogo 11 que manda la factura para todos sus ítems.
_UNIT_OF_MEASURE: str = "94"

#: Dónde vive cada dato de transporte según el doctype. El Delivery Note trae los suyos de
#: ERPNext; el Stock Entry, los que le agrega l10n_ve.
TRANSPORT_FIELDS: dict[str, dict[str, str]] = {
    "Delivery Note": {
        "transporter": "transporter",
        "driver": "driver",
        "vehicle_no": "vehicle_no",
        "vehicle_type": "ve_vehicle_type",
    },
    "Stock Entry": {
        "transporter": "ve_transporter",
        "driver": "ve_driver",
        "vehicle_no": "ve_vehicle_no",
        "vehicle_type": "ve_vehicle_type",
    },
}


def compact_tax_id(tax_id: str) -> str:
    """RIF sin separadores: «J-30909786-5» → «J309097865»."""
    return re.sub(r"[^0-9A-Za-z]", "", tax_id or "").upper()


def transport_value(doc, key: str) -> str:
    """Valor del dato de transporte `key` en el documento, según su doctype."""
    fieldname: str = TRANSPORT_FIELDS[doc.doctype][key]
    return str(doc.get(fieldname) or "").strip()


#: Líneas de la dirección renderizada que no son dirección: la plantilla les agrega el contacto.
_CONTACT_LINE = re.compile(r"^\s*(phone|tel[eé]fono|tel|fax|e-?mail|correo)\b", re.IGNORECASE)


def address_one_line(display: str) -> str:
    """Dirección renderizada en una línea, sin teléfono ni correo y sin líneas repetidas.

    Se parte de lo que ya resolvió la plantilla de dirección --los nombres legibles de
    ciudad y estado--, no de los campos sueltos, que pueden guardar un id en vez del nombre.
    """
    kept: list[str] = []
    for part in re.split(r"<br\s*/?>|\n", display or ""):
        line: str = strip_html(part)
        if not line or _CONTACT_LINE.match(line) or line in kept:
            continue
        kept.append(line)
    return ", ".join(kept)


def party_address_text(link_doctype: str, link_name: str) -> str:
    """Dirección principal de un tercero o de la empresa, en una sola línea."""
    if link_doctype == "Company":
        display: str = get_company_address(link_name).get("company_address_display") or ""
    else:
        address_name: str | None = get_default_address(link_doctype, link_name)
        display = (render_address(address_name, check_permissions=False) or "") if address_name else ""
    return address_one_line(display)


def _is_vat_row(tax) -> bool:
    """Fila de IVA en el sentido de la factura (`charge_type` "VAT" de l10n_ve, que suma)."""
    return (
        tax.get("charge_type") == "VAT"
        and (tax.get("add_deduct_tax") or "Add") == "Add"
        and flt(tax.get("rate")) > 0
    )


def delivery_note_tax_problems(doc) -> list[str]:
    """Impuestos de la nota que el 04 no puede declarar sin adivinar.

    El caso que importa es el primero, y no es raro: las plantillas de IVA de l10n_ve usan
    el tipo "VAT", que solo calcula el motor de la factura. El Delivery Note usa el
    calculador estándar de ERPNext, que no lo conoce: la fila queda con la alícuota y en
    cero, y la nota no cobra IVA. Medido el 21-sep-2026 en local.domina.galanet con la
    plantilla predeterminada «IVA 16%»: neto 25,00 = total 25,00.
    """
    problems: list[str] = []
    for tax in doc.get("taxes") or []:
        label: str = tax.get("description") or tax.get("account_head") or "?"
        amount: float = flt(tax.get("base_tax_amount")) or flt(tax.get("tax_amount"))
        if _is_vat_row(tax) and not amount:
            problems.append(
                f"La nota trae la plantilla de IVA «{label}», pero en la nota de entrega ese IVA "
                "no se calcula: queda en 0, porque el IVA venezolano lo calcula la factura. "
                "Quite la plantilla de impuestos y la orden de entrega se emite exenta, que es lo "
                "que la nota cobra."
            )
        elif not _is_vat_row(tax) and amount:
            problems.append(
                f"La nota tiene un impuesto que no es IVA («{label}»): el documento fiscal 04 solo "
                "se emite exento o gravado con IVA."
            )
    return problems


def apply_delivery_note_tax_regime(doc) -> None:
    """Fija en memoria el exento de la nota de entrega, que el Delivery Note no guarda.

    La factura sabe qué parte es exenta porque su calculador (el de l10n_ve) llena
    `total_exempt`/`base_total_exempt` y cada ítem trae `vat_exempt`. El Delivery Note no
    pasa por ese calculador ni tiene esos campos, así que el criterio sale de sus propias
    filas de impuesto, y solo hay dos casos que se pueden declarar sin adivinar:

    - **Sin impuestos**: la nota no cobra IVA y se declara exenta completa. Es lo que
      `_build_items` ya hace con cada ítem cuando no hay fila de IVA.
    - **Con IVA calculado y nada más**: gravada, igual que la factura.

    Lo demás se corta (`delivery_note_tax_problems`): declararlo exento o gravado sería
    elegir por el usuario un valor que sale impreso en el documento fiscal. La aprobación ya
    lo corta antes; esto lo repite por si la nota llegó al envío por otro camino.
    """
    problems: list[str] = delivery_note_tax_problems(doc)
    if problems:
        # Llevan la descripción de la fila de impuesto, que escribe el usuario: el diálogo es HTML.
        frappe.throw(
            "<br>".join(frappe.utils.escape_html(problem) for problem in problems),
            title=_("Impuestos no soportados en el 04"),
        )

    if any(_is_vat_row(tax) for tax in doc.get("taxes") or []):
        doc.total_exempt = 0.0
        doc.base_total_exempt = 0.0
    else:
        doc.total_exempt = flt(doc.net_total)
        doc.base_total_exempt = flt(doc.base_net_total, 2)


class DispatchNodesMixin:
    """Lo que el 04 agrega sobre cualquier documento: el nodo `GuiaDespacho`, la fecha de
    emisión y la información adicional.

    Requiere `self.doc`, `self.series_doc`, `self.branch_code` y `self.emission`.
    """

    doc: object
    series_doc: object
    branch_code: str
    emission: datetime.datetime

    # --- Identificación --------------------------------------------------------------

    def _emission_date_str(self) -> str:
        return self.emission.strftime("%d/%m/%Y")

    def _emission_time_str(self) -> str:
        return self.emission.strftime("%I:%M:%S %p").lower()

    def _is_third_party(self) -> bool:
        return getattr(self.series_doc, "operation_mode", "Internal") == "Third Party"

    def _dispatch_identification(self, currency: str) -> dict:
        """Campos de la identificación que en el 04 no salen de la fecha del documento.

        La fecha de emisión es la del envío: HKA emite con la fecha del día, igual que la
        factura. La diferencia es que acá NO se mueve el `posting_date` del documento, porque
        en una nota de entrega o un traslado esa fecha ordena el libro de inventario.
        """
        return {
            "TipoDocumento": DISPATCH_DOCUMENT_TYPE,
            "FechaEmision": self._emission_date_str(),
            "FechaVencimiento": self._emission_date_str(),
            "HoraEmision": self._emission_time_str(),
            # Contado/Crédito es una condición de pago: una entrega o un traslado no la tienen.
            "TipoDePago": None,
            "Moneda": hka_currency_code(currency),
        }

    # --- Nodo GuiaDespacho -----------------------------------------------------------

    def _is_dispatch_guide(self) -> bool:
        """"1" o "0" del documento. Sin tipo elegido se corta: el título del documento
        fiscal no se adivina."""
        kind: str = self.doc.get("ve_dispatch_document_kind") or ""
        if kind == DISPATCH_GUIDE:
            return True
        if kind == DELIVERY_ORDER:
            return False
        frappe.throw(
            _("{0} {1}: falta el tipo de documento de despacho ({2} o {3}).").format(
                self.doc.doctype, self.doc.name, DELIVERY_ORDER, DISPATCH_GUIDE
            ),
            title=_("Documento de despacho incompleto"),
        )

    def _build_guia_despacho(self) -> dict:
        description: str = " ".join(str(self.doc.get("ve_transfer_description") or "").split())
        return {
            "EsGuiaDespacho": "1" if self._is_dispatch_guide() else "0",
            # El catálogo 13 viaja como texto: HKA recibe la descripción, no un código.
            "MotivoTraslado": (self.doc.get("ve_transfer_reason") or "")[:55] or None,
            "DescripcionServicio": description[:255] or None,
            # Catálogo 14 (alcohol y cigarrillos): no aplica a esta mercancía.
            "TipoProducto": None,
            "OrigenProducto": self.doc.get("ve_product_origin") or None,
            "PesoOVolumenTotal": self._weight_or_volume(),
            "DestinoProducto": self.doc.get("ve_product_destination") or None,
            "Conductor": self._build_conductor(),
            "Vehiculo": self._build_vehiculo(),
            "Transportista": self._build_transportista(),
        }

    def _weight_or_volume(self) -> str | None:
        """El peso declarado a mano; si no hay, el peso neto de la nota cuando todos sus
        ítems lo expresan en la misma unidad (sumar kilos con libras no es un peso)."""
        explicit: str = (self.doc.get("ve_total_weight_volume") or "").strip()
        if explicit:
            return explicit[:55]
        total: float = flt(self.doc.get("total_net_weight"))
        if total <= 0:
            return None
        units: set = {item.get("weight_uom") for item in self.doc.get("items") or [] if flt(item.get("total_weight"))}
        if len(units) != 1 or not next(iter(units)):
            return None
        return f"{flt(total, 3):g} {next(iter(units))}"[:55]

    def _build_conductor(self) -> dict | None:
        driver_name: str = transport_value(self.doc, "driver")
        if not driver_name:
            return None
        driver = frappe.get_cached_doc("Driver", driver_name)
        return {
            "NombreCompleto": " ".join((driver.full_name or "").split())[:100],
            "TipoIdentificacion": (driver.get("ve_id_type") or "").strip().upper() or None,
            "NumeroIdentificacion": re.sub(r"[^0-9]", "", driver.get("ve_id_number") or "")[:12] or None,
            "TipoLicencia": (driver.get("ve_license_grade") or "").strip()[:55] or None,
            "InfoContacto": (driver.get("cell_number") or "").strip()[:255] or None,
        }

    def _build_vehiculo(self) -> dict | None:
        plate: str = re.sub(r"\s+", "", transport_value(self.doc, "vehicle_no")).upper()
        vehicle_type: str = transport_value(self.doc, "vehicle_type")
        if not (plate or vehicle_type):
            return None
        return {
            "TipoVehiculo": vehicle_type[:255] or None,
            "NumeroTransporte": None,
            "NumeroPlaca": plate[:12] or None,
        }

    def _build_transportista(self) -> dict:
        """El transportista es obligatorio en el 04. Sin uno externo el traslado es propio,
        y el que transporta es la empresa: eso es lo que se declara."""
        transporter: str = transport_value(self.doc, "transporter")
        if transporter:
            supplier = frappe.get_cached_doc("Supplier", transporter)
            name, tax_id = supplier.supplier_name, supplier.tax_id
            address: str = party_address_text("Supplier", transporter)
        else:
            company = frappe.get_cached_doc("Company", self.doc.company)
            name, tax_id = company.company_name, company.tax_id
            address = party_address_text("Company", self.doc.company)
        return {
            "RazonSocial": TFHKAPayloadBuilder._sanitize_razon_social(name)[:255],
            "NumeroIdentificacion": compact_tax_id(tax_id)[:12],
            "DomicilioFiscal": address[:255],
        }

    # --- Información adicional ---------------------------------------------------------

    def _info_adicional_pdf(self, extra: dict) -> list:
        """El nodo que lee la plantilla de impresión de HKA, con la misma codificación que
        la factura: un solo campo «PDF» con un dict en comillas simples."""
        serie: str = getattr(self.series_doc, "serie", "") or ""
        if not serie:
            frappe.throw(
                _(
                    "La serie de facturación no tiene el campo 'Serie' configurado. "
                    "Es obligatorio para la facturación electrónica."
                ),
                title=_("Serie Requerida"),
            )
        dict_pdf: dict = {"Serie": serie, "Documento": self.doc.get("ve_dispatch_document_kind") or ""}
        dict_pdf.update({key: value for key, value in extra.items() if value})
        sanitized: dict = {
            key: value.replace("'", "") if isinstance(value, str) else value
            for key, value in dict_pdf.items()
        }
        return [{"Campo": "PDF", "Valor": json.dumps(sanitized, ensure_ascii=False).replace('"', "'")}]


class DeliveryNotePayloadBuilder(DispatchNodesMixin, TFHKAPayloadBuilder):
    """04 de una nota de entrega: los montos, el comprador y los ítems son los de la factura.

    Antes de construirlo hay que llamar a `apply_delivery_note_tax_regime`, que fija el
    exento que el Delivery Note no guarda.
    """

    def __init__(
        self,
        doc,
        series_doc=None,
        branch_code: str = "",
        emission: datetime.datetime | None = None,
    ) -> None:
        super().__init__(doc, series_doc=series_doc, branch_code=branch_code, tasa_fecha=None)
        self.emission: datetime.datetime = emission or now_datetime()

    def build_payload(self) -> dict:
        self.items_payload = self._build_items()
        payload: dict = {
            "documentoElectronico": {
                "Encabezado": self._build_encabezado(),
                "DetallesItems": self.items_payload,
                "DetallesRetencion": None,
                "Viajes": None,
                "InfoAdicional": self._build_info_adicional(),
                "GuiaDespacho": self._build_guia_despacho(),
                "Transporte": None,
                "EsLote": None,
                "EsMinimo": None,
            }
        }
        return clean_payload(payload)

    def _get_tipo_documento(self) -> str:
        return DISPATCH_DOCUMENT_TYPE

    def _build_identificacion_documento(self) -> dict:
        identification: dict = super()._build_identificacion_documento()
        identification.update(self._dispatch_identification(self.doc.currency))
        return identification

    def _build_formas_pago(self, total_a_pagar_bsd: float) -> None:
        """Una entrega no es un cobro: no lleva formas de pago (el nodo es opcional)."""
        return

    def _resolve_tfhka_code(self, item_code: str) -> str:
        """El código PLU es opcional y admite hasta 20 caracteres. Lo que se entrega es un
        artículo y su código es el propio: se fija acá para que el reemplazo del ISP (el
        código del plan de suscripción, que vende un servicio) no alcance a la entrega."""
        return (item_code or "")[:20]

    def _build_info_adicional(self) -> list:
        extra: dict = {
            "DireccionEntrega": clean_address(self.doc.get("shipping_address") or self.doc.address_display or ""),
            "Nota": " ".join(str(self.doc.get("instructions") or "").split())[:255],
        }
        company_currency: str = frappe.get_cached_value("Company", self.doc.company, "default_currency")
        if self.doc.currency != company_currency and flt(self.doc.conversion_rate) > 0:
            rate_date = resolve_exchange_rate_date(flt(self.doc.conversion_rate), self.doc.currency)
            date_text: str = getdate(rate_date).strftime("%d/%m/%Y") if rate_date else self._emission_date_str()
            extra["TasaCambio"] = (
                f"Tasa de cambio publicado por el BCV Bs {flt(self.doc.conversion_rate, 4)} "
                f"por 1,00 {self.doc.currency} de fecha valor {date_text}."
            )
        return self._info_adicional_pdf(extra)


class StockEntryDispatchPayloadBuilder(DispatchNodesMixin):
    """04 de un traslado de material: la empresa se lo despacha a sí misma.

    El receptor es la empresa con la dirección del almacén de destino. Los ítems van a su
    costo de valoración y exentos --un traslado no es una venta, no causa IVA--, en la
    moneda de la empresa.
    """

    def __init__(
        self,
        doc,
        series_doc=None,
        branch_code: str = "",
        emission: datetime.datetime | None = None,
    ) -> None:
        self.doc = doc
        self.series_doc = series_doc
        self.branch_code = branch_code
        self.emission = emission or now_datetime()
        self.company_currency: str = frappe.get_cached_value("Company", doc.company, "default_currency")

    def build_payload(self) -> dict:
        items: list = self._build_items()
        payload: dict = {
            "documentoElectronico": {
                "Encabezado": {
                    "IdentificacionDocumento": self._build_identificacion_documento(),
                    "Vendedor": None,
                    "Comprador": self._build_comprador(),
                    "SujetoRetenido": None,
                    "Tercero": None,
                    "Totales": self._build_totales(items),
                    "TotalesRetencion": None,
                    "TotalesOtraMoneda": None,
                    "Orden": None,
                },
                "DetallesItems": items,
                "DetallesRetencion": None,
                "Viajes": None,
                "InfoAdicional": self._build_info_adicional(),
                "GuiaDespacho": self._build_guia_despacho(),
                "Transporte": None,
                "EsLote": None,
                "EsMinimo": None,
            }
        }
        return clean_payload(payload)

    def _build_identificacion_documento(self) -> dict:
        identification: dict = {
            "NumeroDocumento": "" if self._is_third_party() else (self.doc.get("bill_no") or ""),
            "Anulado": False,
            "Serie": getattr(self.series_doc, "serie", "") or "",
            "Sucursal": str(self.branch_code)[:6] if self.branch_code else "",
            "TipoDeVenta": "Interna",
            "TransaccionId": (
                build_transaction_id("".join(ch for ch in self.doc.name if ch.isalnum()), self.doc)
                if self._is_third_party() else None
            ),
        }
        identification.update(self._dispatch_identification(self.company_currency))
        return identification

    def _destination_address(self) -> str:
        """El almacén de destino; si no tiene dirección, la de la empresa."""
        display: str = self.doc.get("target_address_display") or ""
        if not display and self.doc.get("target_warehouse_address"):
            display = render_address(self.doc.target_warehouse_address, check_permissions=False) or ""
        text: str = clean_address(display)
        return text or clean_address(get_company_address(self.doc.company).get("company_address_display") or "")

    def _build_comprador(self) -> dict:
        company = frappe.get_cached_doc("Company", self.doc.company)
        id_type, id_number = TFHKAPayloadBuilder._parse_tax_id(company.tax_id)
        address: str = self._destination_address()
        if not address:
            frappe.throw(
                _(
                    "Ni el almacén de destino ni la empresa '{0}' tienen dirección. Es obligatoria "
                    "en el documento fiscal."
                ).format(company.company_name),
                title=_("Dirección de destino requerida"),
            )
        emails: list = notification_emails([company.email] if company.get("email") else [])
        return {
            "TipoIdentificacion": id_type,
            "NumeroIdentificacion": id_number,
            "RazonSocial": TFHKAPayloadBuilder._sanitize_razon_social(company.company_name),
            "Direccion": address,
            "Ubigeo": None,
            "Pais": "VE",
            "Notificar": None,
            "Telefono": [company.phone_no] if company.get("phone_no") else None,
            "Correo": emails or None,
            "OtrosEnvios": None,
        }

    def _build_items(self) -> list:
        """Cada ítem a su costo de valoración por unidad de stock, exento.

        Se usa la tasa de valoración redondeada y el importe se recalcula con ella, porque
        HKA verifica que precio unitario por cantidad sea el importe de la línea [1044].
        """
        def fmt(value: float) -> str:
            return f"{flt(value):.2f}"

        lines: list = []
        for idx, item in enumerate(self.doc.items, start=1):
            quantity: float = flt(item.transfer_qty) or flt(item.qty)
            unit_price: float = flt(item.basic_rate, 2)
            amount: float = flt(unit_price * quantity, 2)
            description: str = re.sub(r"(?i)\btotal\b", "", item.item_name or item.item_code or "").strip()
            lines.append({
                "NumeroLinea": str(idx),
                "CodigoCIIU": _CIIU_CODE,
                "CodigoPLU": (item.item_code or "")[:20],
                "IndicadorBienoServicio": "1",
                "Descripcion": description[:250],
                "Cantidad": str(cint(quantity)) if quantity == cint(quantity) else str(quantity),
                "UnidadMedida": _UNIT_OF_MEASURE,
                "PrecioUnitario": fmt(unit_price),
                "PrecioUnitarioDescuento": None,
                "MontoBonificacion": None,
                "DescripcionBonificacion": None,
                "DescuentoMonto": "0.00",
                "RecargoMonto": "0",
                "PrecioItem": fmt(amount),
                "PrecioAntesDescuento": fmt(amount),
                "CodigoImpuesto": "E",
                "TasaIVA": "0",
                "ValorIVA": "0.00",
                "ValorTotalItem": fmt(amount),
                "InfoAdicionalItem": [],
                "ListaItemOTI": None,
            })
        return lines

    def _build_totales(self, items: list) -> dict:
        def fmt(value: float) -> str:
            return f"{flt(value):.2f}"

        total: float = flt(sum(flt(line["PrecioItem"]) for line in items), 2)
        if total <= 0:
            frappe.throw(
                _(
                    "El traslado {0} no tiene valor: sus ítems están a costo cero. El documento "
                    "fiscal declara el valor de la mercancía trasladada."
                ).format(self.doc.name),
                title=_("Traslado sin valor"),
            )
        # El mismo texto que la factura; `_monto_en_letras` ya cae a `money_in_words` si falla.
        words: str = TFHKAPayloadBuilder._monto_en_letras(self, total, "VES")
        return {
            "NroItems": str(len(items)),
            "MontoGravadoTotal": "0.00",
            "MontoExentoTotal": fmt(total),
            "MontoPercibidoTotal": "0.00",
            "SubtotalAntesDescuento": fmt(total),
            "TotalDescuento": None,
            "TotalRecargos": None,
            "Subtotal": fmt(total),
            "TotalIVA": "0.00",
            "MontoTotalConIVA": fmt(total),
            "TotalAPagar": fmt(total),
            "MontoEnLetras": words,
            "ListaRecargo": None,
            "ListaDescBonificacion": None,
            "ImpuestosSubtotal": [{
                "CodigoTotalImp": "E",
                "AlicuotaImp": "00.00",
                "BaseImponibleImp": fmt(total),
                "ValorTotalImp": "00.00",
            }],
            "OtrosImpuestosSubtotal": None,
            "FormasPago": None,
            "TotalIGTF": None,
            "TotalIGTF_VES": None,
            "MontoTotalOTI": None,
            "MontoTotalIVAyOTI": None,
        }

    def _build_info_adicional(self) -> list:
        source: str = self.doc.get("from_warehouse") or next(
            (item.s_warehouse for item in self.doc.items if item.get("s_warehouse")), ""
        )
        target: str = self.doc.get("to_warehouse") or next(
            (item.t_warehouse for item in self.doc.items if item.get("t_warehouse")), ""
        )
        return self._info_adicional_pdf({
            "AlmacenOrigen": source,
            "AlmacenDestino": target,
            "DireccionOrigen": clean_address(self.doc.get("source_address_display") or ""),
            "Nota": " ".join(str(self.doc.get("remarks") or "").split())[:255],
        })
