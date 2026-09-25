"""Tests del documento fiscal 04: Orden de Entrega y Guía de Despacho.

Los del builder fijan la forma del payload que HKA Demo aceptó el 21-sep-2026 (traslado en
bolívares con transporte propio, nota en USD con transportista externo, nota emitida como
guía). Los de la integración fijan las reglas que no se ven en el payload: cuándo aplica,
qué se exige al aprobar, cómo se lee la respuesta y cuándo no se puede cancelar.
"""

import base64
import datetime
import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe import _
from frappe.utils import get_datetime

from l10n_ve.digital_invoice import dispatch_note_integration as integration
from l10n_ve.digital_invoice import dispatch_note_payload_builder as builder_module
from l10n_ve.digital_invoice.dispatch_note_payload_builder import (
    DeliveryNotePayloadBuilder,
    StockEntryDispatchPayloadBuilder,
    address_one_line,
    apply_delivery_note_tax_regime,
    compact_tax_id,
    delivery_note_tax_problems,
    hka_currency_code,
)
from l10n_ve.digital_invoice.tfhka_integration import HKARangeExhausted
from l10n_ve.tests.helpers import MockDoc

#: Sin zona horaria, como la devuelve `now_datetime()` del sitio.
EMISSION: datetime.datetime = get_datetime("2026-09-21 12:16:39")

_DRIVER = frappe._dict(full_name="Pedro Pérez", ve_id_type="V", ve_id_number="12.345.678",
                       ve_license_grade="5ta", cell_number="04141234567")
_CUSTOMER = frappe._dict(tax_id="V16369489", customer_name="Cliente de Prueba")
_SUPPLIER = frappe._dict(supplier_name="Transportes C.A.", tax_id="J-30742964-0")
_COMPANY = frappe._dict(company_name="Galanet Solution C.A.", tax_id="J309097865",
                        phone_no="04122413144", email=None)


_VE_SETTINGS = frappe._dict(igtf_rate=3.0)  # el builder de la factura lo lee para el IGTF
_FAKE_DOCS: dict = {"Driver": _DRIVER, "Customer": _CUSTOMER, "Supplier": _SUPPLIER, "Company": _COMPANY,
                    "Venezuela Account Settings": _VE_SETTINGS}
_ORIGINAL_GET_CACHED_DOC = frappe.get_cached_doc


def _cached_doc(doctype, *args, **kwargs):
    """Maestros del test; lo demás, a la función real.

    Frappe carga «System Settings» con esta misma función para saber cómo redondear, y `flt`
    convierte cualquier excepción en 0.0: un parche que no delega deja todos los montos en cero
    sin un solo error.
    """
    if doctype in _FAKE_DOCS:
        return _FAKE_DOCS[doctype]
    return _ORIGINAL_GET_CACHED_DOC(doctype, *args, **kwargs)


def _vat_row(amount: float) -> frappe._dict:
    return frappe._dict(charge_type="VAT", add_deduct_tax="Add", rate=16.0, description="IVA 16%",
                        account_head="IVA - TC", tax_amount=amount, base_tax_amount=amount * 800)


def _delivery_note(**overrides) -> MockDoc:
    data = {
        "doctype": "Delivery Note", "name": "MAT-DN-2026-00001", "company": "Test Company",
        "customer": "Cliente de Prueba", "customer_name": "Cliente de Prueba", "branch": "MIR-01",
        "posting_date": "2026-09-19", "posting_time": "08:00:00", "is_return": 0,
        "currency": "USD", "conversion_rate": 800.0,
        "address_display": "Calle 1, Los Teques<br>Miranda", "contact_mobile": "04123083167",
        "contact_email": "", "bill_no": "", "net_total": 25.0, "base_net_total": 20000.0,
        "discount_amount": 0.0, "base_discount_amount": 0.0, "taxes": [],
        "items": [frappe._dict(item_code="EQUIPO-01", item_name="Router", item_group="Antenas",
                               qty=1, rate=25.0, amount=25.0, base_net_amount=20000.0)],
        "ve_dispatch_document_kind": "Orden de Entrega", "driver": "HR-DRI-1",
        "vehicle_no": "ab 123 cd", "ve_vehicle_type": "Moto", "transporter": "",
        "creation": "2026-09-21 12:16:28",
    }
    data.update(overrides)
    return MockDoc(**data)


def _stock_entry(**overrides) -> MockDoc:
    data = {
        "doctype": "Stock Entry", "name": "MAT-STE-2026-00002", "company": "Test Company",
        "purpose": "Material Transfer", "ve_issue_dispatch_note": 1, "branch": "MIR-01",
        "from_warehouse": "Consumibles", "to_warehouse": "Reciclajes",
        "target_address_display": "Av Principal, Caracas", "bill_no": "",
        "ve_dispatch_document_kind": "Guía de Despacho",
        "ve_transfer_reason": "Traslado de depósito, almacenes o bodegas propio",
        "ve_driver": "HR-DRI-1", "ve_vehicle_no": "AB123CD", "ve_vehicle_type": "Camioneta",
        "ve_transporter": "", "remarks": "", "creation": "2026-09-21 12:15:52",
        "items": [frappe._dict(item_code="EQUIPO-01", item_name="Router", qty=2, transfer_qty=2,
                               basic_rate=850.0, s_warehouse="Consumibles", t_warehouse="Reciclajes")],
    }
    data.update(overrides)
    return MockDoc(**data)


def _series(mode: str = "Third Party") -> MockDoc:
    return MockDoc(name="SFD-2026-0001", serie="MAR-05", operation_mode=mode)


_ORIGINAL_GET_CACHED_VALUE = frappe.get_cached_value


def _company_currency(currency: str):
    """Parche de `frappe.get_cached_value` que solo contesta la moneda de la empresa.

    Todo lo demás va a la función real: Frappe la usa por dentro, entre otras cosas para el
    método de redondeo, y un parche que contesta lo mismo a todo deja `flt(x, 2)` en cero.
    """
    def fake(doctype, *args, **kwargs):
        if doctype == "Company":
            return currency
        return _ORIGINAL_GET_CACHED_VALUE(doctype, *args, **kwargs)
    return fake


class _BuilderPatches(unittest.TestCase):
    """Aísla los builders de la base: maestros, direcciones, moneda de la empresa y correos."""

    company_currency: str = "VEF"

    def setUp(self) -> None:
        patches = [
            patch("frappe.get_cached_doc", side_effect=_cached_doc),
            patch("frappe.get_cached_value", side_effect=_company_currency(self.company_currency)),
            patch.object(builder_module, "party_address_text", return_value="Av Fiscal 1, Caracas"),
            patch.object(builder_module, "resolve_exchange_rate_date", return_value="2026-09-01"),
            patch.object(builder_module, "notification_emails", side_effect=lambda emails: emails),
            patch("l10n_ve.digital_invoice.payload_builder.notification_emails", side_effect=lambda e: e),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def delivery_payload(self, series=None, **overrides) -> dict:
        doc = _delivery_note(**overrides)
        apply_delivery_note_tax_regime(doc)
        return DeliveryNotePayloadBuilder(doc, series_doc=series or _series(), branch_code="MIR-01",
                                          emission=EMISSION).build_payload()["documentoElectronico"]

    def transfer_payload(self, series=None, **overrides) -> dict:
        doc = _stock_entry(**overrides)
        return StockEntryDispatchPayloadBuilder(doc, series_doc=series or _series(), branch_code="MIR-01",
                                                emission=EMISSION).build_payload()["documentoElectronico"]


class TestDeliveryNotePayload(_BuilderPatches):
    def test_orden_de_entrega_sin_impuestos_va_exenta(self):
        payload = self.delivery_payload()
        ident = payload["encabezado"]["identificacionDocumento"]
        self.assertEqual(ident["tipoDocumento"], "04")
        self.assertEqual(payload["guiaDespacho"]["esGuiaDespacho"], "0")
        self.assertEqual([i["codigoImpuesto"] for i in payload["detallesItems"]], ["E"])
        totales = payload["encabezado"]["totales"]
        self.assertEqual(totales["montoExentoTotal"], "20000.00")
        self.assertEqual(totales["montoGravadoTotal"], "0.00")
        self.assertEqual(totales["totalIVA"], "0.00")
        self.assertEqual([i["codigoTotalImp"] for i in totales["impuestosSubtotal"]], ["E"])

    def test_una_entrega_no_lleva_formas_de_pago_ni_tipo_de_pago(self):
        payload = self.delivery_payload()
        self.assertNotIn("formasPago", payload["encabezado"]["totales"])
        self.assertNotIn("tipoDePago", payload["encabezado"]["identificacionDocumento"])

    def test_fecha_de_emision_es_la_del_envio_no_la_del_documento(self):
        ident = self.delivery_payload()["encabezado"]["identificacionDocumento"]
        self.assertEqual(ident["fechaEmision"], "21/09/2026")
        self.assertEqual(ident["horaEmision"], "12:16:39 pm")

    def test_divisa_manda_totales_en_la_otra_moneda(self):
        payload = self.delivery_payload()
        self.assertEqual(payload["encabezado"]["identificacionDocumento"]["moneda"], "USD")
        self.assertEqual(payload["encabezado"]["totalesOtraMoneda"]["montoExentoTotal"], "25.00")

    def test_nota_en_bolivares_manda_bsd_y_no_otra_moneda(self):
        payload = self.delivery_payload(currency="VEF", conversion_rate=1.0, net_total=20000.0)
        self.assertEqual(payload["encabezado"]["identificacionDocumento"]["moneda"], "BSD")
        self.assertNotIn("totalesOtraMoneda", payload["encabezado"])

    def test_iva_calculado_va_gravado(self):
        payload = self.delivery_payload(taxes=[_vat_row(4.0)])
        self.assertEqual(payload["detallesItems"][0]["codigoImpuesto"], "G")
        totales = payload["encabezado"]["totales"]
        self.assertEqual(totales["montoGravadoTotal"], "20000.00")
        self.assertEqual(totales["totalIVA"], "3200.00")

    def test_codigo_plu_es_el_del_articulo(self):
        self.assertEqual(self.delivery_payload()["detallesItems"][0]["codigoPLU"], "EQUIPO-01")

    def test_transportista_externo(self):
        guide = self.delivery_payload(transporter="TRANSPORTES")["guiaDespacho"]
        self.assertEqual(guide["transportista"]["razonSocial"], "Transportes C.A.")
        self.assertEqual(guide["transportista"]["numeroIdentificacion"], "J307429640")

    def test_sin_transportista_el_transporte_es_propio(self):
        guide = self.delivery_payload()["guiaDespacho"]
        self.assertEqual(guide["transportista"]["razonSocial"], "Galanet Solution C.A.")
        self.assertEqual(guide["transportista"]["numeroIdentificacion"], "J309097865")
        self.assertEqual(guide["transportista"]["domicilioFiscal"], "Av Fiscal 1, Caracas")

    def test_conductor_y_vehiculo(self):
        guide = self.delivery_payload()["guiaDespacho"]
        self.assertEqual(guide["conductor"]["numeroIdentificacion"], "12345678")
        self.assertEqual(guide["conductor"]["tipoIdentificacion"], "V")
        self.assertEqual(guide["vehiculo"]["numeroPlaca"], "AB123CD")

    def test_guia_de_despacho_desde_una_nota(self):
        guide = self.delivery_payload(ve_dispatch_document_kind="Guía de Despacho",
                                      ve_transfer_reason="Otras causas",
                                      ve_transfer_description="Equipo en comodato")["guiaDespacho"]
        self.assertEqual(guide["esGuiaDespacho"], "1")
        self.assertEqual(guide["motivoTraslado"], "Otras causas")
        self.assertEqual(guide["descripcionServicio"], "Equipo en comodato")

    def test_sin_tipo_de_documento_se_corta(self):
        with self.assertRaises(frappe.ValidationError):
            self.delivery_payload(ve_dispatch_document_kind="")

    def test_numero_propio_solo_en_modo_interno(self):
        ident = self.delivery_payload(series=_series("Internal"), bill_no="7")["encabezado"]["identificacionDocumento"]
        self.assertEqual(ident["numeroDocumento"], "7")
        self.assertNotIn("transaccionId", ident)
        ident = self.delivery_payload(bill_no="7")["encabezado"]["identificacionDocumento"]
        self.assertEqual(ident["numeroDocumento"], "")
        self.assertTrue(ident["transaccionId"].startswith("MATDN202600001"))

    def test_tasa_en_la_informacion_adicional(self):
        info = self.delivery_payload()["infoAdicional"][0]
        self.assertEqual(info["campo"], "PDF")
        self.assertIn("fecha valor 01/09/2026", info["valor"])


class TestStockEntryPayload(_BuilderPatches):
    def test_la_empresa_se_despacha_a_si_misma(self):
        comprador = self.transfer_payload()["encabezado"]["comprador"]
        self.assertEqual(comprador["tipoIdentificacion"], "J")
        self.assertEqual(comprador["numeroIdentificacion"], "309097865")
        self.assertEqual(comprador["direccion"], "Av Principal, Caracas")

    def test_items_a_costo_exentos_en_bolivares(self):
        payload = self.transfer_payload()
        item = payload["detallesItems"][0]
        self.assertEqual((item["cantidad"], item["precioUnitario"], item["precioItem"]), ("2", "850.00", "1700.00"))
        self.assertEqual(item["codigoImpuesto"], "E")
        self.assertEqual(payload["encabezado"]["identificacionDocumento"]["moneda"], "BSD")
        self.assertEqual(payload["encabezado"]["totales"]["montoExentoTotal"], "1700.00")
        self.assertNotIn("totalesOtraMoneda", payload["encabezado"])

    def test_importe_de_linea_es_precio_redondeado_por_cantidad(self):
        # HKA [1044]: precioItem = precioUnitario × cantidad. Con 3 decimales en la valoración,
        # el importe sale del precio ya redondeado (10,01 × 3 = 30,03), no de 10,006 × 3 = 30,02.
        item = self.transfer_payload(items=[frappe._dict(item_code="C", item_name="Cable", qty=3, transfer_qty=3,
                                                         basic_rate=10.006)])["detallesItems"][0]
        self.assertEqual((item["precioUnitario"], item["precioItem"]), ("10.01", "30.03"))

    def test_traslado_sin_valor_se_corta(self):
        with self.assertRaises(frappe.ValidationError):
            self.transfer_payload(items=[frappe._dict(item_code="C", item_name="Cable", qty=1, transfer_qty=1,
                                                      basic_rate=0.0)])

    def test_guia_con_motivo_y_transporte_propio(self):
        guide = self.transfer_payload()["guiaDespacho"]
        self.assertEqual(guide["esGuiaDespacho"], "1")
        self.assertEqual(guide["motivoTraslado"], "Traslado de depósito, almacenes o bodegas propio")
        self.assertEqual(guide["transportista"]["razonSocial"], "Galanet Solution C.A.")


class TestHelpers(unittest.TestCase):
    def test_address_one_line_descarta_contacto_y_repetidos(self):
        display = "Av 1<br>Caracas<br>El Hatillo<br>El Hatillo<br>Phone: 0800<br>Email: a@b.c<br>"
        self.assertEqual(address_one_line(display), "Av 1, Caracas, El Hatillo")

    def test_compact_tax_id(self):
        self.assertEqual(compact_tax_id("J-30909786-5"), "J309097865")

    def test_codigo_de_moneda(self):
        self.assertEqual([hka_currency_code(c) for c in ("VEF", "VES", "USD")], ["BSD", "BSD", "USD"])


class TestDeliveryNoteTaxRegime(unittest.TestCase):
    def test_plantilla_de_iva_en_cero_se_corta(self):
        # Lo que pasa con la plantilla «IVA 16%» en un Delivery Note: el tipo "VAT" no lo calcula ERPNext.
        problems = delivery_note_tax_problems(_delivery_note(taxes=[_vat_row(0.0)]))
        self.assertEqual(len(problems), 1)
        self.assertIn("Quite la plantilla", problems[0])

    def test_impuesto_que_no_es_iva_se_corta(self):
        other = frappe._dict(charge_type="On Net Total", rate=3.0, description="Otro", tax_amount=1.0,
                             base_tax_amount=800.0)
        self.assertEqual(len(delivery_note_tax_problems(_delivery_note(taxes=[other]))), 1)
        with self.assertRaises(frappe.ValidationError):
            apply_delivery_note_tax_regime(_delivery_note(taxes=[other]))

    def test_sin_impuestos_todo_exento(self):
        doc = _delivery_note()
        apply_delivery_note_tax_regime(doc)
        self.assertEqual((doc.total_exempt, doc.base_total_exempt), (25.0, 20000.0))

    def test_iva_calculado_nada_exento(self):
        doc = _delivery_note(taxes=[_vat_row(4.0)])
        self.assertEqual(delivery_note_tax_problems(doc), [])
        apply_delivery_note_tax_regime(doc)
        self.assertEqual((doc.total_exempt, doc.base_total_exempt), (0.0, 0.0))

    def test_el_mensaje_escapa_la_descripcion(self):
        # La descripción de la fila la escribe el usuario, y el diálogo la pinta como HTML.
        other = frappe._dict(charge_type="On Net Total", rate=3.0, description="<img src=x onerror=alert(1)>",
                             tax_amount=1.0, base_tax_amount=800.0)
        with patch("frappe.throw", side_effect=frappe.ValidationError) as throw, \
             self.assertRaises(frappe.ValidationError):
            apply_delivery_note_tax_regime(_delivery_note(taxes=[other]))
        message: str = throw.call_args.args[0]
        self.assertNotIn("<img", message)
        self.assertIn("&lt;img", message)


class TestDispatchNoteApplies(unittest.TestCase):
    def setUp(self) -> None:
        for target, value in (("dispatch_notes_enabled", True), ("company_uses_hk", True)):
            p = patch.object(integration, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_casos(self):
        self.assertTrue(integration.dispatch_note_applies(_delivery_note()))
        self.assertFalse(integration.dispatch_note_applies(_delivery_note(is_return=1)))
        self.assertTrue(integration.dispatch_note_applies(_stock_entry()))
        self.assertFalse(integration.dispatch_note_applies(_stock_entry(purpose="Material Receipt")))
        self.assertFalse(integration.dispatch_note_applies(_stock_entry(ve_issue_dispatch_note=0)))
        self.assertFalse(integration.dispatch_note_applies(MockDoc(doctype="Sales Invoice")))

    def test_interruptor_apagado(self):
        with patch.object(integration, "dispatch_notes_enabled", return_value=False):
            self.assertFalse(integration.dispatch_note_applies(_delivery_note()))


class TestDispatchNotesEnabled(unittest.TestCase):
    def meta(self, has_field: bool) -> MagicMock:
        meta = MagicMock()
        meta.has_field.return_value = has_field
        return meta

    def test_entre_el_deploy_y_el_migrate_no_lanza(self):
        # Sin el campo, get_single_value lanzaría; y esto corre al aprobar CUALQUIER nota de entrega.
        with patch("frappe.get_meta", return_value=self.meta(False)), \
             patch("frappe.db.get_single_value") as single:
            self.assertFalse(integration.dispatch_notes_enabled())
        single.assert_not_called()

    def test_encendido(self):
        with patch("frappe.get_meta", return_value=self.meta(True)), \
             patch("frappe.db.get_single_value", return_value=1):
            self.assertTrue(integration.dispatch_notes_enabled())


class TestDispatchNoteCompanies(unittest.TestCase):
    """La lista del boot: el formulario solo muestra el 04 en estas empresas."""

    def test_sitio_apagado_ninguna(self):
        with patch.object(integration, "dispatch_notes_enabled", return_value=False), \
             patch("frappe.get_all") as get_all:
            self.assertEqual(integration.dispatch_note_companies(), [])
        get_all.assert_not_called()

    def test_empresas_con_serie_activa_sin_repetir(self):
        # Varias series de la misma empresa (una por sucursal): la empresa va una sola vez.
        with patch.object(integration, "dispatch_notes_enabled", return_value=True), \
             patch("frappe.get_all", return_value=["Galanet", "Designet", "Galanet", None, ""]) as get_all:
            self.assertEqual(integration.dispatch_note_companies(), ["Designet", "Galanet"])
        self.assertEqual(get_all.call_args.kwargs["filters"], {"status": "Active"})

    def test_mismo_criterio_que_al_aprobar(self):
        # Una empresa de la lista es una en la que el 04 aplica, y viceversa: company_uses_hk
        # pide una serie activa de la empresa, que es lo que la lista junta.
        series = {"Galanet": "Active", "Otra": "Inactive"}
        with patch.object(integration, "dispatch_notes_enabled", return_value=True), \
             patch("frappe.get_all", return_value=[c for c, s in series.items() if s == "Active"]):
            companies = integration.dispatch_note_companies()
        with patch.object(integration, "dispatch_notes_enabled", return_value=True), \
             patch.object(integration, "company_uses_hk", side_effect=lambda c: series.get(c) == "Active"):
            for company in series:
                self.assertEqual(
                    company in companies,
                    integration.dispatch_note_applies(_delivery_note(company=company)),
                    company,
                )


class TestProcessFailure(unittest.TestCase):
    """Un throw del armado deja el documento en Error CON log, en el cron y en el botón."""

    def run_failing(self, raise_on_error: bool):
        doc = _stock_entry(docstatus=1)
        def no_series(**kwargs):
            frappe.throw(_("La sucursal no tiene serie digital activa"))
        patches = [
            patch.object(integration, "_acquire_hka_send_lock", return_value=True),
            patch.object(integration, "_release_hka_send_lock"),
            patch("frappe.get_doc", return_value=doc),
            patch.object(integration, "dispatch_note_applies", return_value=True),
            patch.object(integration, "validate_dispatch_data", return_value=[]),
            patch.object(integration, "get_active_billing_series", side_effect=no_series),
            patch.object(integration, "_set_error"),
            patch.object(integration, "_log_request"),
            patch("frappe.db.commit"),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        release, set_error, log = mocks[1], mocks[6], mocks[7]
        return integration.process_dispatch_note("Stock Entry", doc.name, raise_on_error=raise_on_error), \
            release, set_error, log

    def test_cron_devuelve_false_y_registra(self):
        ok, release, set_error, log = self.run_failing(raise_on_error=False)
        self.assertFalse(ok)
        set_error.assert_called_once()
        self.assertEqual(log.call_args.args[4], "Error")
        self.assertIn("serie digital", log.call_args.kwargs["notes"])
        release.assert_called_once()

    def test_boton_registra_y_relanza(self):
        with self.assertRaises(frappe.ValidationError):
            self.run_failing(raise_on_error=True)
        # los mocks siguen activos hasta el cleanup: el registro ocurrió antes de relanzar
        self.assertEqual(integration._log_request.call_args.args[4], "Error")
        integration._release_hka_send_lock.assert_called_once()

    def test_boton_escapa_los_errores_de_validacion(self):
        # Los errores traen datos del documento (códigos de ítem) y el diálogo es HTML.
        doc = _stock_entry(docstatus=1)
        patches = [
            patch.object(integration, "_acquire_hka_send_lock", return_value=True),
            patch.object(integration, "_release_hka_send_lock"),
            patch("frappe.get_doc", return_value=doc),
            patch.object(integration, "dispatch_note_applies", return_value=True),
            patch.object(integration, "validate_dispatch_data", return_value=["Ítems sin costo: <b>CABLE</b>"]),
            patch.object(integration, "get_active_billing_series", return_value=(_series(), "01")),
            patch.object(integration, "_set_error"),
            patch.object(integration, "_log_request"),
            patch("frappe.db.commit"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with patch("frappe.throw", side_effect=frappe.ValidationError) as throw, \
             self.assertRaises(frappe.ValidationError):
            integration.process_dispatch_note("Stock Entry", doc.name, raise_on_error=True)
        message: str = throw.call_args.args[0]
        self.assertIn("&lt;b&gt;CABLE&lt;/b&gt;", message)
        self.assertNotIn("<b>CABLE", message)


class TestPrepareOnSubmit(unittest.TestCase):
    """Al aprobar: el que emite el 04 queda Pendiente; el que no, sin tipo."""

    def test_sin_04_queda_sin_tipo(self):
        # Una devolución hereda el tipo de la nota original; no es un documento fiscal 04.
        doc = _delivery_note(is_return=1)
        with patch.object(integration, "dispatch_note_applies", return_value=False):
            integration.prepare_dispatch_note_on_submit(doc)
        self.assertIsNone(doc.ve_dispatch_document_kind)
        self.assertIsNone(doc.hka_status)

    def test_con_04_conserva_el_tipo_y_queda_pendiente(self):
        doc = _delivery_note(ve_dispatch_document_kind="Guía de Despacho")
        with patch.object(integration, "dispatch_note_applies", return_value=True), \
             patch.object(integration, "validate_dispatch_data", return_value=[]):
            integration.prepare_dispatch_note_on_submit(doc)
        self.assertEqual((doc.ve_dispatch_document_kind, doc.hka_status), ("Guía de Despacho", "Pendiente"))

    def test_con_04_y_datos_incompletos_corta(self):
        with patch.object(integration, "dispatch_note_applies", return_value=True), \
             patch.object(integration, "validate_dispatch_data", return_value=["Falta el conductor."]), \
             self.assertRaises(frappe.ValidationError):
            integration.prepare_dispatch_note_on_submit(_delivery_note())


class TestValidateDispatchData(unittest.TestCase):
    """Lo que se exige al aprobar. Los maestros tienen RIF y dirección salvo que el test diga otra cosa."""

    def setUp(self) -> None:
        self.driver_values: dict = {"full_name": "Pedro", "ve_id_type": "V", "ve_id_number": "123"}

        def get_value(doctype, name, fields, *args, **kwargs):
            if doctype == "Driver":
                return frappe._dict(self.driver_values)
            return "J123456789"  # tax_id de cliente, transportista o empresa
        patches = [
            patch("frappe.db.get_value", side_effect=get_value),
            patch.object(integration, "party_address_text", return_value="Av 1"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_orden_de_entrega_completa(self):
        self.assertEqual(integration.validate_dispatch_data(_delivery_note()), [])

    def test_orden_de_entrega_no_exige_motivo_ni_conductor(self):
        doc = _delivery_note(driver="", vehicle_no="")
        self.assertEqual(integration.validate_dispatch_data(doc), [])

    def test_guia_exige_motivo_conductor_y_placa(self):
        doc = _stock_entry(ve_transfer_reason="", ve_driver="", ve_vehicle_no="")
        errors = integration.validate_dispatch_data(doc)
        self.assertEqual(len(errors), 3)

    def test_otras_causas_exige_descripcion(self):
        doc = _stock_entry(ve_transfer_reason="Otras causas", ve_transfer_description="")
        self.assertTrue(any("describir" in e for e in integration.validate_dispatch_data(doc)))

    def test_conductor_sin_identificacion(self):
        self.driver_values = {"full_name": "Pedro", "ve_id_type": "", "ve_id_number": ""}
        errors = integration.validate_dispatch_data(_delivery_note())
        self.assertTrue(any("tipo de identificación" in e and "número" in e for e in errors))

    def test_sin_sucursal(self):
        self.assertTrue(any("sucursal" in e for e in integration.validate_dispatch_data(_stock_entry(branch=""))))

    def test_traslado_con_un_item_sin_costo(self):
        items = [frappe._dict(item_code="ROUTER", basic_rate=850.0), frappe._dict(item_code="CABLE", basic_rate=0.0)]
        errors = integration.validate_dispatch_data(_stock_entry(items=items))
        self.assertTrue(any("CABLE" in e and "ROUTER" not in e for e in errors))

    def test_nota_a_precio_cero(self):
        errors = integration.validate_dispatch_data(_delivery_note(base_net_total=0.0))
        self.assertTrue(any("precio cero" in e for e in errors))

    def test_nota_con_plantilla_de_iva_en_cero(self):
        errors = integration.validate_dispatch_data(_delivery_note(taxes=[_vat_row(0.0)]))
        self.assertTrue(any("Quite la plantilla" in e for e in errors))


class TestHandleResponse(unittest.TestCase):
    def setUp(self) -> None:
        self.set_value = MagicMock()
        patches = [
            patch("frappe.db.set_value", self.set_value),
            patch("frappe.db.get_value", return_value=None),  # sin bill_control: se puede marcar Error
            patch.object(integration, "_log_request"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def ok_response(self) -> dict:
        return {"codigo": "200", "resultado": {"numeroDocumento": "2", "numeroControl": "00-00066608",
                                               "serie": "MAR-05"}}

    def test_200_escribe_todo_en_un_solo_update(self):
        response = self.ok_response()
        self.assertTrue(integration._handle_dispatch_response(_delivery_note(), {}, response, _series()))
        self.set_value.assert_called_once()
        updates = self.set_value.call_args.args[2]
        self.assertEqual(updates, {"hka_status": "Emitida", "hka_series": "MAR-05",
                                   "bill_control": "00-00066608", "bill_no": "2",
                                   "hka_response": json.dumps(response, ensure_ascii=False, indent=2)})

    def test_200_en_modo_interno_conserva_el_numero_local(self):
        integration._handle_dispatch_response(_delivery_note(bill_no="5"), {}, self.ok_response(), _series("Internal"))
        self.assertNotIn("bill_no", self.set_value.call_args.args[2])

    def test_200_sobrevive_a_un_log_que_falla(self):
        """El log roto (esquema sin migrar) no deshace la emisión: los números ya se guardaron."""
        integration._log_request.side_effect = frappe.ValidationError("Tipo de Documento cannot be")
        with patch("frappe.log_error") as log_error:
            self.assertTrue(
                integration._handle_dispatch_response(_delivery_note(), {}, self.ok_response(), _series())
            )
        self.assertEqual(self.set_value.call_args.args[2]["bill_control"], "00-00066608")
        log_error.assert_called_once()

    def test_200_confirma_los_numeros_antes_del_log(self):
        """Fuera de tests hay commit entre guardar los números y escribir el log."""
        order: list[str] = []
        self.set_value.side_effect = lambda *a, **k: order.append("set_value")
        integration._log_request.side_effect = lambda *a, **k: order.append("log")
        with patch("frappe.db.commit", side_effect=lambda: order.append("commit")), \
             patch.dict(frappe.flags, {"in_test": False}):
            integration._handle_dispatch_response(_delivery_note(), {}, self.ok_response(), _series())
        self.assertEqual(order, ["set_value", "commit", "log"])

    def test_201_es_sospecha_de_duplicado(self):
        response = {"codigo": "201", "resultado": {"numeroDocumento": "9", "numeroControl": "00-1"}}
        self.assertFalse(integration._handle_dispatch_response(_delivery_note(), {}, response, _series()))
        self.set_value.assert_called_once()
        self.assertEqual(self.set_value.call_args.args[2:4], ("hka_status", "Error"))

    def test_sin_respuesta(self):
        self.assertFalse(integration._handle_dispatch_response(_delivery_note(), {}, {}, _series()))
        self.assertEqual(self.set_value.call_args.args[2:4], ("hka_status", "Error"))

    def test_rango_agotado_frena_la_serie(self):
        response = {"codigo": "400", "mensaje": "No hay rango de numeración disponible"}
        with self.assertRaises(HKARangeExhausted):
            integration._handle_dispatch_response(_delivery_note(), {}, response, _series())


class TestDispatchNotePdf(unittest.TestCase):
    """El panel «Documento Fiscal Digital» del 04: el PDF se pide a HKA como tipo 04."""

    def test_descarga_como_tipo_04_y_adjunta_con_su_prefijo(self):
        from l10n_ve.digital_invoice import tfhka_client

        response = json.dumps({"codigo": "200", "resultado": {
            "serie": "MAR-05", "numeroDocumento": "2", "numeroControl": "00-00066608"}})
        doc = MagicMock(hka_response=response)
        captured: dict = {}

        def fake_get_all(doctype, **kwargs):
            captured["pattern"] = kwargs["filters"]["file_name"][1]
            return []  # sin PDF adjunto: hay que bajarlo de HKA

        client = MagicMock()
        client.download_file.return_value = {"archivo": base64.b64encode(b"%PDF-1.4 guia").decode()}
        with patch.object(tfhka_client.frappe, "get_cached_doc", return_value=doc), \
             patch.object(tfhka_client.frappe, "has_permission", return_value=True), \
             patch.object(tfhka_client.frappe, "get_all", side_effect=fake_get_all), \
             patch.object(tfhka_client, "TFHKAClient", return_value=client), \
             patch("frappe.utils.file_manager.save_file") as save_file:
            result = tfhka_client.get_fiscal_invoice_pdf("MAT-DN-2026-00001", "Delivery Note")

        self.assertEqual(base64.b64decode(result["base64"]), b"%PDF-1.4 guia")
        client.download_file.assert_called_once_with(
            numero_documento="2", tipo_documento="04", tipo_archivo="pdf", serie="MAR-05"
        )
        # Ni la búsqueda ni el adjunto usan «Factura_»: no es una factura.
        self.assertEqual(captured["pattern"], "Despacho_%.pdf")
        self.assertTrue(save_file.call_args.kwargs["fname"].startswith("Despacho_MAT-DN-2026-00001_2"))


class TestDispatchNumber(unittest.TestCase):
    def setUp(self) -> None:
        p = patch("frappe.db.set_value")
        self.set_value = p.start()
        self.addCleanup(p.stop)

    def test_tercero_no_toma_numero(self):
        series = _series()
        series.take_dispatch_note_number = MagicMock()
        integration._ensure_dispatch_number(_delivery_note(), series)
        series.take_dispatch_note_number.assert_not_called()

    def test_interno_toma_numero(self):
        series = _series("Internal")
        series.take_dispatch_note_number = MagicMock(return_value="8")
        doc = _delivery_note()
        integration._ensure_dispatch_number(doc, series)
        self.assertEqual(doc.bill_no, "8")

    def test_interno_reintento_reutiliza_su_numero(self):
        series = _series("Internal")
        series.take_dispatch_note_number = MagicMock()
        integration._ensure_dispatch_number(_delivery_note(bill_no="8", hka_status="Error"), series)
        series.take_dispatch_note_number.assert_not_called()

    def test_interno_proceso_muerto_en_pendiente_no_quema_otro_numero(self):
        # Tomó el número (commiteado antes del viaje a HKA) y murió sin marcar el fallo.
        series = _series("Internal")
        series.take_dispatch_note_number = MagicMock()
        integration._ensure_dispatch_number(_delivery_note(bill_no="8", hka_status="Pendiente"), series)
        series.take_dispatch_note_number.assert_not_called()


class TestBlockCancel(unittest.TestCase):
    def test_emitido_no_se_cancela(self):
        with self.assertRaises(frappe.ValidationError):
            integration.block_cancel_if_emitted(_delivery_note(bill_control="00-1", hka_status="Emitida"))

    def test_anulado_ante_hka_si_se_cancela(self):
        integration.block_cancel_if_emitted(_delivery_note(bill_control="00-1", hka_status="Anulada"))

    def test_pendiente_se_cancela_si_no_se_esta_enviando(self):
        # El mutex queda tomado hasta que la cancelación se confirme o se revierta: soltarlo
        # antes deja que el cron emita el documento ante HKA mientras Frappe lo cancela.
        from frappe.utils import CallbackManager

        with patch.object(integration, "_acquire_hka_send_lock", return_value=True), \
             patch.object(integration, "_release_hka_send_lock") as release, \
             patch.object(CallbackManager, "add", autospec=True) as add:
            integration.block_cancel_if_emitted(_delivery_note(hka_status="Pendiente"))
            release.assert_not_called()
            managers = [call.args[0] for call in add.call_args_list]
            self.assertEqual(managers, [frappe.db.after_commit, frappe.db.after_rollback])
            add.call_args_list[0].args[1]()  # la cancelación se confirma
        release.assert_called_once_with("Delivery Note", "MAT-DN-2026-00001")

    def test_pendiente_en_pleno_envio_no_se_cancela(self):
        with patch.object(integration, "_acquire_hka_send_lock", return_value=False), \
             self.assertRaises(frappe.ValidationError):
            integration.block_cancel_if_emitted(_delivery_note(hka_status="Pendiente"))


class TestVoidDispatchNote(unittest.TestCase):
    """La anulación pide un 04 emitido y lo identifica ante HKA por serie, tipo y número."""

    def run_void(self, result: dict, **overrides):
        data: dict = {"docstatus": 1, "hka_status": "Emitida", "bill_no": "00000007",
                      "hka_series": "MAR-05", "bill_control": "00-00066612"}
        data.update(overrides)
        doc = _delivery_note(**data)
        doc.add_comment, doc.reload, doc.cancel = MagicMock(), MagicMock(), MagicMock()
        client = MagicMock()
        client.void_document.return_value = result
        patches = [
            patch("frappe.get_doc", return_value=doc),
            patch("frappe.has_permission", return_value=True),
            patch.object(integration, "TFHKAClient", return_value=client),
            patch.object(integration, "_log_request"),
            patch("frappe.db.set_value"),
            patch("frappe.db.commit"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return doc, client

    def test_emitido_sin_control_se_anula_por_numero(self):
        # Un 200 que llegó sin número de control: HKA lo anula igual, por serie, tipo y número.
        doc, client = self.run_void({"_http_ok": True, "codigo": "200"}, bill_control="")
        result = integration.void_dispatch_note("Delivery Note", doc.name, "Dirección equivocada")
        payload: dict = client.void_document.call_args.args[0]
        self.assertEqual((payload["serie"], payload["tipoDocumento"], payload["numeroDocumento"]),
                         ("MAR-05", "04", "00000007"))
        frappe.db.set_value.assert_called_once_with("Delivery Note", doc.name, "hka_status", "Anulada",
                                                    update_modified=False)
        doc.cancel.assert_called_once()
        self.assertEqual(result["status"], "success")

    def test_pendiente_no_se_anula(self):
        doc, client = self.run_void({"_http_ok": True}, hka_status="Pendiente", bill_no="", bill_control="")
        with self.assertRaises(frappe.ValidationError):
            integration.void_dispatch_note("Delivery Note", doc.name, "Motivo")
        client.void_document.assert_not_called()

    def test_rechazo_de_hka_no_cambia_nada(self):
        doc, _client = self.run_void({"_http_ok": False, "codigo": "500", "mensaje": "No existe"})
        with self.assertRaises(frappe.ValidationError):
            integration.void_dispatch_note("Delivery Note", doc.name, "Motivo")
        frappe.db.set_value.assert_not_called()
        doc.cancel.assert_not_called()
        self.assertEqual(integration._log_request.call_args.args[4], "Error")


class TestDeliveryNoteRate(unittest.TestCase):
    def setUp(self) -> None:
        p = patch("frappe.get_cached_value", side_effect=_company_currency("VEF"))
        p.start()
        self.addCleanup(p.stop)

    def check(self, expected_rate: float, **overrides) -> list:
        with patch.object(integration, "get_ve_exchange_rate_for_customer", return_value=expected_rate):
            return integration._validate_delivery_note_rate(_delivery_note(**overrides), EMISSION)

    def test_tasa_de_la_regla(self):
        self.assertEqual(self.check(800.0), [])

    def test_tasa_vieja_se_corta(self):
        self.assertEqual(len(self.check(847.4442)), 1)

    def test_sin_tasa_publicada_se_emite_con_la_que_porta(self):
        self.assertEqual(self.check(0.0), [])

    def test_nota_en_bolivares_no_aplica(self):
        self.assertEqual(self.check(847.4442, currency="VEF"), [])


class TestRerateHook(unittest.TestCase):
    def test_solo_retasa_si_el_04_aplica(self):
        doc = _delivery_note()
        doc._action = "submit"
        with patch.object(integration, "dispatch_note_applies", return_value=False), \
             patch("l10n_ve.digital_invoice.emission_rerate.rerate_juridical_on_submit") as rerate:
            integration.rerate_delivery_note_on_submit(doc)
        rerate.assert_not_called()

    def test_retasa_con_la_regla_de_la_factura(self):
        doc = _delivery_note()
        doc._action = "submit"
        with patch.object(integration, "dispatch_note_applies", return_value=True), \
             patch("l10n_ve.digital_invoice.emission_rerate.rerate_juridical_on_submit") as rerate:
            integration.rerate_delivery_note_on_submit(doc)
        rerate.assert_called_once()


class TestPendingQueries(unittest.TestCase):
    """Las consultas corren de verdad: un nombre de columna mal escrito solo se ve así."""

    def test_consultas_ejecutan(self):
        for doctype in integration.DISPATCH_DOCTYPES:
            if not frappe.db.has_column(doctype, "hka_status"):
                self.skipTest(f"{doctype} sin los campos del 04 en este sitio")
            self.assertIsInstance(integration._get_pending_dispatch_notes(doctype, "2026-04-01"), list)
        self.assertEqual(integration._get_pending_dispatch_notes("Sales Invoice", "2026-04-01"), [])
