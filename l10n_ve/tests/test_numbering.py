# Copyright (c) 2026, Galanet Solution and contributors
# See license.txt
"""La numeración fiscal centralizada: que no repita, que no deje huecos y que no gire.

Los tres males que había, cada uno en una implementación distinta:

- Company leía el correlativo en memoria y lo incrementaba aparte, sin bloqueo: dos
  facturas validadas a la vez se llevaban el mismo número. Eso es lo que fija
  `TestConcurrency`, con hilos y conexiones de verdad.
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

PREFIX = "ZZTEST-NUM"
TEST_COMPANY = "ZZTEST-EMPRESA-NUMERACION"
ORIGIN_DOCTYPE = "VE Digital Billing Series"


def _create_series(name: str, counter: int = 1) -> str:
    """Una serie de prueba como origen barato del contador.

    Se usa la serie y no una Company porque crear una empresa arrastra el plan de cuentas
    entero; el mecanismo que se prueba es el mismo, el origen da igual.

    Se inserta con `db_insert`, saltando la validación del DocType, porque el sitio base de
    la CI no tiene ninguna empresa y `company` es obligatorio. Lo que se prueba acá es el
    contador, no el alta de la serie.
    """
    doc = frappe.get_doc({
        "doctype": ORIGIN_DOCTYPE,
        "name": name,
        "company": TEST_COMPANY,
        "operation_mode": "Internal",
        "status": "Active",
        "prefix": "00",
        "range_from": 1,
        "range_to": 999999,
        "invoice_number_correlative": counter,
        "credit_note_number_correlative": counter,
        "debit_note_number_correlative": counter,
        "start_operations": "2026-01-01",
    })
    doc.db_insert()
    return doc.name


def _delete_series(name: str) -> None:
    frappe.db.delete(ORIGIN_DOCTYPE, {"name": name})


class TestFormats(unittest.TestCase):
    """El formateo, que antes vivía en Company y ahora comparten los tres."""

    def test_number_is_split_across_all_groups(self):
        self.assertEqual(format_number("##-########", 220248), "00-00220248")

    def test_without_format_the_number_comes_out_plain(self):
        # Es lo que usa la serie digital, que no tiene campo de formato.
        self.assertEqual(format_number(None, 7), "7")
        self.assertEqual(format_number("", 7), "7")

    def test_withholding_number_carries_year_and_month(self):
        number = format_withholding_number("##############", 455)
        today = frappe.utils.getdate(frappe.utils.nowdate())
        self.assertEqual(number[:6], f"{today.year}{today.month:02d}")
        self.assertEqual(number[6:], "00000455")
        self.assertEqual(len(number), 14)

    def test_legacy_counter_is_read_from_its_tail(self):
        """En la base conviven el correlativo a secas y el voucher_number completo."""
        self.assertEqual(parse_withholding_counter("455", "##############"), 455)
        self.assertEqual(parse_withholding_counter("20260400000455", "##############"), 455)
        self.assertEqual(parse_withholding_counter("", "##############"), 1)
        self.assertEqual(parse_withholding_counter("no es un número", "##############"), 1)


class TestTakeNumber(FrappeTestCase):
    """`take_next_number` contra la base."""

    def setUp(self):
        self.addCleanup(frappe.db.rollback)
        self.series = _create_series(f"{PREFIX}-1")
        self.addCleanup(lambda: _delete_series(self.series))

    def _counter(self) -> int:
        return frappe.db.get_value(ORIGIN_DOCTYPE, self.series, "invoice_number_correlative")

    def test_returns_the_current_one_and_advances(self):
        self.assertEqual(take_next_number(ORIGIN_DOCTYPE, self.series, "invoice_number_correlative"), "1")
        self.assertEqual(self._counter(), 2)
        self.assertEqual(take_next_number(ORIGIN_DOCTYPE, self.series, "invoice_number_correlative"), "2")
        self.assertEqual(self._counter(), 3)

    def test_zero_counter_starts_at_one(self):
        frappe.db.set_value(ORIGIN_DOCTYPE, self.series, "invoice_number_correlative", 0)
        self.assertEqual(take_next_number(ORIGIN_DOCTYPE, self.series, "invoice_number_correlative"), "1")

    def test_skips_numbers_already_taken(self):
        taken = {"1", "2", "3"}
        number = take_next_number(
            ORIGIN_DOCTYPE, self.series, "invoice_number_correlative",
            is_free=lambda n: n not in taken,
        )
        self.assertEqual(number, "4")
        # El contador queda detrás del que se entregó, listo para el siguiente.
        self.assertEqual(self._counter(), 5)

    def test_gives_up_instead_of_spinning_forever(self):
        """El `while True` anterior consumía correlativos sin fin y colgaba el submit."""
        with self.assertRaises(frappe.ValidationError):
            take_next_number(
                ORIGIN_DOCTYPE, self.series, "invoice_number_correlative",
                is_free=lambda n: False, max_tries=5,
            )

    def test_missing_origin_raises(self):
        with self.assertRaises(frappe.ValidationError):
            take_next_number(ORIGIN_DOCTYPE, "NO-EXISTE-ESTA-SERIE", "invoice_number_correlative")

    def test_does_not_commit_so_it_leaves_no_gap(self):
        """Si el documento no llega a guardarse, el número vuelve a estar disponible."""
        self.assertEqual(take_next_number(ORIGIN_DOCTYPE, self.series, "invoice_number_correlative"), "1")
        frappe.db.rollback()
        # La serie se fue con el rollback; se rehace y el contador arranca donde debía.
        self.series = _create_series(f"{PREFIX}-1b")
        self.assertEqual(take_next_number(ORIGIN_DOCTYPE, self.series, "invoice_number_correlative"), "1")


class TestConcurrency(FrappeTestCase):
    """Lo adversarial: muchos documentos a la vez sobre el mismo contador.

    Cada hilo abre su propia conexión, como haría un worker distinto. Con el mecanismo
    anterior --leer en memoria e incrementar aparte-- dos hilos se llevaban el mismo
    número; con `FOR UPDATE` el segundo espera.
    """

    THREADS = 8
    PER_THREAD = 5

    def setUp(self):
        self.series = _create_series(f"{PREFIX}-CONC")
        frappe.db.commit()  # los otros hilos tienen que verla

    def tearDown(self):
        _delete_series(self.series)
        frappe.db.commit()

    def test_no_number_is_repeated_or_skipped(self):
        site = frappe.local.site
        series = self.series
        numbers: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()

        def worker():
            frappe.init(site=site)
            frappe.connect()
            try:
                for _ in range(self.PER_THREAD):
                    number = take_next_number(ORIGIN_DOCTYPE, series, "invoice_number_correlative")
                    frappe.db.commit()
                    with lock:
                        numbers.append(number)
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(repr(e))
            finally:
                frappe.destroy()

        threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
        for h in threads:
            h.start()
        for h in threads:
            h.join(timeout=120)

        total = self.THREADS * self.PER_THREAD
        self.assertEqual(errors, [], f"hilos con error: {errors}")
        self.assertEqual(len(numbers), total, "algún hilo no terminó")
        self.assertEqual(
            len(set(numbers)), total,
            f"se repitieron números: {sorted(n for n in numbers if numbers.count(n) > 1)}",
        )
        ints = sorted(int(n) for n in numbers)
        self.assertEqual(ints, list(range(1, total + 1)), "la numeración quedó con huecos")
        self.assertEqual(
            frappe.db.get_value(ORIGIN_DOCTYPE, series, "invoice_number_correlative"), total + 1
        )

    def test_survives_a_transaction_that_already_read_the_row(self):
        """El caso real: el llamador carga el documento del origen y después toma el número.

        Con REPEATABLE READ, el `SELECT ... FOR UPDATE` sobre una fila que la transacción ya
        leyó no espera: MariaDB la rechaza con `1020, Record has changed since last read` en
        cuanto otro la mueve. En un submit de factura la empresa se lee varias veces, así que
        este es el patrón que importa. `take_next_number` lo reintenta en una conexión aparte.
        """
        site = frappe.local.site
        series = self.series
        numbers: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()

        def worker():
            frappe.init(site=site)
            frappe.connect()
            try:
                for _ in range(self.PER_THREAD):
                    frappe.get_doc(ORIGIN_DOCTYPE, series)  # envenena la instantánea
                    number = take_next_number(ORIGIN_DOCTYPE, series, "invoice_number_correlative")
                    frappe.db.commit()
                    with lock:
                        numbers.append(number)
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(repr(e))
            finally:
                frappe.destroy()

        threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
        for h in threads:
            h.start()
        for h in threads:
            h.join(timeout=120)

        total = self.THREADS * self.PER_THREAD
        self.assertEqual(errors, [], f"hilos con error: {errors[:2]}")
        self.assertEqual(len(set(numbers)), total, "se repitió algún número")
        self.assertEqual(sorted(int(n) for n in numbers), list(range(1, total + 1)), "quedaron huecos")
