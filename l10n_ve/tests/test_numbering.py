# Copyright (c) 2026, Galanet Solution and contributors
# See license.txt
"""La numeración fiscal centralizada: que no repita, que no deje huecos y que no gire.

Los tres males que había, cada uno en una implementación distinta:

- Company leía el correlativo en memoria y lo incrementaba aparte, sin bloqueo: dos
  facturas validadas a la vez se llevaban el mismo número. Eso es lo que fija
  `TestConcurrencia`, con hilos y conexiones de verdad.
- El bucle que buscaba un número libre era `while True`: con el correlativo desalineado
  no terminaba nunca. Ahora se rinde y lo dice.
- La serie digital releía el contador restando uno, sin formato ni comprobación.

Los tres comparten hoy `l10n_ve.numbering`.
"""

import threading
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.numbering import (
    format_number,
    format_withholding_number,
    parse_withholding_counter,
    take_next_number,
)

PREFIJO = "ZZTEST-NUM"
EMPRESA_DE_PRUEBA = "ZZTEST-EMPRESA-NUMERACION"
DOCTYPE_ORIGEN = "VE Digital Billing Series"


def _crear_serie(nombre: str, correlativo: int = 1) -> str:
    """Una serie de prueba como origen barato del contador.

    Se usa la serie y no una Company porque crear una empresa arrastra el plan de cuentas
    entero; el mecanismo que se prueba es el mismo, el origen da igual.

    Se inserta con `db_insert`, saltando la validación del DocType, porque el sitio base de
    la CI no tiene ninguna empresa y `company` es obligatorio. Lo que se prueba acá es el
    contador, no el alta de la serie.
    """
    doc = frappe.get_doc({
        "doctype": DOCTYPE_ORIGEN,
        "name": nombre,
        "company": EMPRESA_DE_PRUEBA,
        "operation_mode": "Internal",
        "status": "Active",
        "prefix": "00",
        "range_from": 1,
        "range_to": 999999,
        "invoice_number_correlative": correlativo,
        "credit_note_number_correlative": correlativo,
        "debit_note_number_correlative": correlativo,
        "start_operations": "2026-01-01",
    })
    doc.db_insert()
    return doc.name


def _borrar_serie(nombre: str) -> None:
    frappe.db.delete(DOCTYPE_ORIGEN, {"name": nombre})


class TestFormatos(unittest.TestCase):
    """El formateo, que antes vivía en Company y ahora comparten los tres."""

    def test_el_numero_se_reparte_entre_los_grupos(self):
        self.assertEqual(format_number("##-########", 220248), "00-00220248")

    def test_sin_formato_sale_pelado(self):
        # Es lo que usa la serie digital, que no tiene campo de formato.
        self.assertEqual(format_number(None, 7), "7")
        self.assertEqual(format_number("", 7), "7")

    def test_retencion_lleva_ano_y_mes_adelante(self):
        numero = format_withholding_number("##############", 455)
        hoy = frappe.utils.getdate(frappe.utils.nowdate())
        self.assertEqual(numero[:6], f"{hoy.year}{hoy.month:02d}")
        self.assertEqual(numero[6:], "00000455")
        self.assertEqual(len(numero), 14)

    def test_el_contador_heredado_se_lee_por_la_cola(self):
        """En la base conviven el correlativo a secas y el voucher_number completo."""
        self.assertEqual(parse_withholding_counter("455", "##############"), 455)
        self.assertEqual(parse_withholding_counter("20260400000455", "##############"), 455)
        self.assertEqual(parse_withholding_counter("", "##############"), 1)
        self.assertEqual(parse_withholding_counter("no es un número", "##############"), 1)


class TestTomarNumero(FrappeTestCase):
    """`take_next_number` contra la base."""

    def setUp(self):
        self.addCleanup(frappe.db.rollback)
        self.serie = _crear_serie(f"{PREFIJO}-1")
        self.addCleanup(lambda: _borrar_serie(self.serie))

    def _correlativo(self) -> int:
        return frappe.db.get_value(DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative")

    def test_devuelve_el_actual_y_avanza_uno(self):
        self.assertEqual(take_next_number(DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative"), "1")
        self.assertEqual(self._correlativo(), 2)
        self.assertEqual(take_next_number(DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative"), "2")
        self.assertEqual(self._correlativo(), 3)

    def test_el_contador_en_cero_arranca_en_uno(self):
        frappe.db.set_value(DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative", 0)
        self.assertEqual(take_next_number(DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative"), "1")

    def test_se_salta_los_numeros_ya_tomados(self):
        tomados = {"1", "2", "3"}
        numero = take_next_number(
            DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative",
            is_free=lambda n: n not in tomados,
        )
        self.assertEqual(numero, "4")
        # El contador queda detrás del que se entregó, listo para el siguiente.
        self.assertEqual(self._correlativo(), 5)

    def test_se_rinde_en_vez_de_girar_para_siempre(self):
        """El `while True` anterior consumía correlativos sin fin y colgaba el submit."""
        with self.assertRaises(frappe.ValidationError):
            take_next_number(
                DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative",
                is_free=lambda n: False, max_tries=5,
            )

    def test_el_origen_inexistente_avisa(self):
        with self.assertRaises(frappe.ValidationError):
            take_next_number(DOCTYPE_ORIGEN, "NO-EXISTE-ESTA-SERIE", "invoice_number_correlative")

    def test_no_commitea_asi_que_no_deja_hueco(self):
        """Si el documento no llega a guardarse, el número vuelve a estar disponible."""
        self.assertEqual(take_next_number(DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative"), "1")
        frappe.db.rollback()
        # La serie se fue con el rollback; se rehace y el contador arranca donde debía.
        self.serie = _crear_serie(f"{PREFIJO}-1b")
        self.assertEqual(take_next_number(DOCTYPE_ORIGEN, self.serie, "invoice_number_correlative"), "1")


class TestConcurrencia(FrappeTestCase):
    """Lo adversarial: muchos documentos a la vez sobre el mismo contador.

    Cada hilo abre su propia conexión, como haría un worker distinto. Con el mecanismo
    anterior --leer en memoria e incrementar aparte-- dos hilos se llevaban el mismo
    número; con `FOR UPDATE` el segundo espera.
    """

    HILOS = 8
    POR_HILO = 5

    def setUp(self):
        self.serie = _crear_serie(f"{PREFIJO}-CONC")
        frappe.db.commit()  # los otros hilos tienen que verla

    def tearDown(self):
        _borrar_serie(self.serie)
        frappe.db.commit()

    def test_ningun_numero_se_repite_ni_se_salta(self):
        sitio = frappe.local.site
        serie = self.serie
        numeros: list[str] = []
        errores: list[str] = []
        candado = threading.Lock()

        def trabajador():
            frappe.init(site=sitio)
            frappe.connect()
            try:
                for _ in range(self.POR_HILO):
                    numero = take_next_number(DOCTYPE_ORIGEN, serie, "invoice_number_correlative")
                    frappe.db.commit()
                    with candado:
                        numeros.append(numero)
            except Exception as e:  # noqa: BLE001
                with candado:
                    errores.append(repr(e))
            finally:
                frappe.destroy()

        hilos = [threading.Thread(target=trabajador) for _ in range(self.HILOS)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=120)

        total = self.HILOS * self.POR_HILO
        self.assertEqual(errores, [], f"hilos con error: {errores}")
        self.assertEqual(len(numeros), total, "algún hilo no terminó")
        self.assertEqual(
            len(set(numeros)), total,
            f"se repitieron números: {sorted(n for n in numeros if numeros.count(n) > 1)}",
        )
        enteros = sorted(int(n) for n in numeros)
        self.assertEqual(enteros, list(range(1, total + 1)), "la numeración quedó con huecos")
        self.assertEqual(
            frappe.db.get_value(DOCTYPE_ORIGEN, serie, "invoice_number_correlative"), total + 1
        )

    def test_aguanta_aunque_la_transaccion_ya_haya_leido_la_fila(self):
        """El caso real: el llamador carga el documento del origen y después toma el número.

        Con REPEATABLE READ, el `SELECT ... FOR UPDATE` sobre una fila que la transacción ya
        leyó no espera: MariaDB la rechaza con `1020, Record has changed since last read` en
        cuanto otro la mueve. En un submit de factura la empresa se lee varias veces, así que
        este es el patrón que importa. `take_next_number` lo reintenta en una conexión aparte.
        """
        sitio = frappe.local.site
        serie = self.serie
        numeros: list[str] = []
        errores: list[str] = []
        candado = threading.Lock()

        def trabajador():
            frappe.init(site=sitio)
            frappe.connect()
            try:
                for _ in range(self.POR_HILO):
                    frappe.get_doc(DOCTYPE_ORIGEN, serie)  # envenena la instantánea
                    numero = take_next_number(DOCTYPE_ORIGEN, serie, "invoice_number_correlative")
                    frappe.db.commit()
                    with candado:
                        numeros.append(numero)
            except Exception as e:  # noqa: BLE001
                with candado:
                    errores.append(repr(e))
            finally:
                frappe.destroy()

        hilos = [threading.Thread(target=trabajador) for _ in range(self.HILOS)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=120)

        total = self.HILOS * self.POR_HILO
        self.assertEqual(errores, [], f"hilos con error: {errores[:2]}")
        self.assertEqual(len(set(numeros)), total, "se repitió algún número")
        self.assertEqual(sorted(int(n) for n in numeros), list(range(1, total + 1)), "quedaron huecos")
