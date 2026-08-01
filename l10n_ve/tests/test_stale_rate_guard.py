# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Una factura no puede certificarse con una tasa que no corresponde a su fecha.

Una vez emitida ante HKA el error no se deshace: hay que anularla con nota de crédito y
reemitirla. Por eso el chequeo es fail-closed y vive ANTES del envío.

Caso que lo motivó: `ACC-SINV-2026-13754` (01-ago-2026). Creada el 2 de julio para el
período 01-07 al 31-07 con la tasa del 1° de julio (633,3644). Su `posting_date` terminó
en 2026-08-01 --el movimiento no dejó versión en el historial, así que la causa sigue sin
identificarse-- y la tasa se quedó en la de julio. Salió ante el SENIAT con base
imponible Bs 109.200,76 cuando a la tasa de su fecha de emisión eran Bs 128.726,43:
unos Bs 19.526 de base y Bs 3.124 de IVA por debajo.

La comparación es por FECHA de la tasa y no por valor: en Currency Exchange conviven
tasas del mismo día que difieren ~1e-4, y compararlas por valor daría falsos positivos.

Sin base de datos: se simulan el catálogo de tasas y la moneda de la empresa.
"""

import unittest
from unittest.mock import patch

from frappe import _dict

MOD = "l10n_ve.digital_invoice.emission_rerate"

# Tasas reales de producción, con la fecha a la que corresponde cada una.
TASAS = {
    "2026-07-01": 633.3644,
    "2026-08-01": 746.6297,
}
POR_VALOR = {v: k for k, v in TASAS.items()}


def _factura(posting_date, tasa, **extra):
    doc = _dict(
        doctype="Sales Invoice",
        name="ACC-SINV-2026-13754",
        company="Galanet Solution C.A.",
        customer="RICHARD ANTONIO MARTINEZ",
        currency="USD",
        conversion_rate=tasa,
        posting_date=posting_date,
        is_return=0,
        is_debit_note=0,
    )
    doc.update(extra)
    return doc


def _motivo(doc, company_currency="VEF"):
    from l10n_ve.digital_invoice.emission_rerate import stale_rate_reason

    with patch(f"{MOD}.frappe.get_cached_value", return_value=company_currency), patch(
        f"{MOD}.get_exchange_rate", side_effect=lambda d, _c: TASAS.get(str(d), 0)
    ), patch(
        f"{MOD}.resolve_exchange_rate_date", side_effect=lambda r, _c: POR_VALOR.get(r)
    ):
        return stale_rate_reason(doc)


class TestStaleRateGuard(unittest.TestCase):
    def test_the_real_case_is_blocked(self):
        """Postea en agosto con la tasa del 1° de julio."""
        motivo = _motivo(_factura("2026-08-01", 633.3644))
        self.assertIsNotNone(motivo)
        self.assertIn("633.3644", motivo)
        self.assertIn("746.6297", motivo)
        self.assertIn("2026-08-01", motivo)

    def test_a_coherent_invoice_passes(self):
        """La misma factura antes de que le movieran la fecha."""
        self.assertIsNone(_motivo(_factura("2026-07-01", 633.3644)))

    def test_an_august_invoice_with_the_august_rate_passes(self):
        self.assertIsNone(_motivo(_factura("2026-08-01", 746.6297)))

    def test_a_credit_note_is_not_checked(self):
        """Una nota se expresa en la tasa del documento que corrige, no en la suya."""
        self.assertIsNone(_motivo(_factura("2026-08-01", 633.3644, is_return=1)))

    def test_a_debit_note_is_not_checked(self):
        self.assertIsNone(_motivo(_factura("2026-08-01", 633.3644, is_debit_note=1)))

    def test_an_invoice_in_bolivars_is_not_checked(self):
        """Sin carril en divisa no hay tasa que verificar."""
        doc = _factura("2026-08-01", 1.0)
        doc.currency = "VEF"
        self.assertIsNone(_motivo(doc))

    def test_it_does_not_block_when_the_rate_for_that_date_is_unknown(self):
        """No poder verificar no es motivo para frenar una emisión."""
        self.assertIsNone(_motivo(_factura("2026-09-15", 633.3644)))

    def test_a_document_without_rate_is_not_checked(self):
        self.assertIsNone(_motivo(_factura("2026-08-01", 0)))

    def test_rates_of_the_same_day_do_not_trigger_it(self):
        """En Currency Exchange conviven tasas del mismo día que difieren ~1e-4.
        Se compara por fecha, no por valor: sin esto habría falsos positivos."""
        from l10n_ve.digital_invoice.emission_rerate import stale_rate_reason

        casi = 746.6298
        with patch(f"{MOD}.frappe.get_cached_value", return_value="VEF"), patch(
            f"{MOD}.get_exchange_rate", return_value=746.6297
        ), patch(f"{MOD}.resolve_exchange_rate_date", return_value="2026-08-01"):
            self.assertIsNone(stale_rate_reason(_factura("2026-08-01", casi)))
