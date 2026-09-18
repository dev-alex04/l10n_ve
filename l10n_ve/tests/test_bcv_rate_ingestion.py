# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la ingesta de la tasa BCV: lectura de la FECHA VALOR y días que cubre.

Bug origen (sep-2026): el BCV movió la fecha valor de un `<time datetime>` a un
`<span class="date-display-single" content>`. `_extract_date_from_html` devolvía
None y, como el llamador descarta la lectura completa cuando falta la fecha, se
tiraban las tasas correctas que ya se habían extraído. Producción quedó cinco
días sin tasa (última fila 2026-09-04) mientras el BCV publicaba con normalidad.

El contenedor viejo `.views-field-field-fecha-del-indicador` sigue en la página
pero hoy trae la fecha de OTRO indicador, así que no sirve de respaldo: leerlo
estamparía las tasas de hoy con una fecha ajena. De ahí que el parser busque el
span hacia adelante desde el rótulo y que la fecha se valide contra hoy antes de
escribir nada.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup
from frappe.utils import add_days, getdate

from l10n_ve.tasks import (
    _extract_date_from_html,
    _extract_rates_from_html,
    _is_plausible_value_date,
    _process_rates,
    _resolve_target_dates,
)

# Marcado real del BCV al 2026-09-06: el rótulo precede al span, y el span del
# indicador viejo —con otra fecha— aparece más adelante en el documento.
CURRENT_MARKUP = """
<div id="dolar" class="col-sm-12 col-xs-12 ">
  <div class="row recuadrotsmc">
    <div class="col-sm-6 col-xs-6"><span> USD</span></div>
    <div class="col-sm-6 col-xs-6 centrado textp">
      <strong class="strong-tb">813,73610000</strong>
    </div>
  </div>
</div>
<div class="pull-right dinpro center">
Fecha Valor: <span class="date-display-single" property="dc:date"
 datatype="xsd:dateTime" content="2026-09-07T00:00:00-04:00">Lunes, 07 Septiembre  2026</span>
</div>
<div id="euro" class="col-sm-12 col-xs-12 ">
  <div class="row recuadrotsmc">
    <div class="col-sm-6 col-xs-6"><span> EUR</span></div>
    <div class="col-sm-6 col-xs-6 centrado textp">
      <strong class="strong-tb">945,65085917</strong>
    </div>
  </div>
</div>
<div class="views-field views-field-field-fecha-del-indicador">
  <span class="date-display-single" content="2026-08-01T00:00:00-04:00">01 Agosto</span>
</div>
"""

# El rótulo dentro del propio span.
LABEL_INSIDE_SPAN = """
<div><span class="date-display-single" content="2026-09-07T00:00:00-04:00">
Fecha Valor: Lunes, 07 Septiembre 2026</span></div>
"""

# El rótulo en un span hermano, y el del indicador viejo ANTES en el documento:
# buscar entre los descendientes del padre devolvería la fecha equivocada.
FOREIGN_SPAN_FIRST = """
<div class="wrapper">
  <span class="date-display-single" content="2026-08-01T00:00:00-04:00">01 Agosto</span>
  <span class="label">Fecha&nbsp;VALOR:</span>
  <span class="date-display-single" content="2026-09-07T00:00:00-04:00">07 Septiembre</span>
</div>
"""

# El rótulo sobrevive pero su span desaparece, y más abajo en la página hay el
# span de OTRO indicador: buscar hacia adelante sin límite lo tomaría.
LABEL_WITHOUT_ITS_SPAN = """
<div class="pull-right dinpro center">Fecha Valor:</div>
<div class="views-field views-field-field-fecha-del-indicador">
  <span class="date-display-single" content="2026-09-04T00:00:00-04:00">04 Septiembre</span>
</div>
"""

# El rótulo partido por espacios y salto de línea.
LABEL_WITH_ODD_WHITESPACE = """
<div>Fecha\n  Valor:
<span class="date-display-single" content="2026-09-07T00:00:00-04:00">07 Septiembre</span></div>
"""

# Sin fecha valor, pero con el contenedor viejo lleno de otra fecha.
NO_VALUE_DATE = """
<div id="dolar"><strong class="strong-tb">813,73610000</strong></div>
<div class="views-field views-field-field-fecha-del-indicador">
  <time datetime="2026-08-01T00:00:00-04:00">01 Agosto</time>
</div>
"""


class TestPageExtraction(unittest.TestCase):
    def test_reads_value_date_not_the_indicator_date(self):
        """La fecha sale del span rotulado 'Fecha Valor', no del otro indicador."""
        soup = BeautifulSoup(CURRENT_MARKUP, "html.parser")

        self.assertEqual(_extract_date_from_html(soup), "2026-09-07")

    def test_reads_rates_from_strong_with_class(self):
        """El <strong> del BCV hoy lleva class='strong-tb'; igual se lee."""
        soup = BeautifulSoup(CURRENT_MARKUP, "html.parser")

        rates = _extract_rates_from_html(soup)

        self.assertEqual(rates["USD"], "813.73610000")
        self.assertEqual(rates["EUR"], "945.65085917")

    def test_reads_label_nested_inside_the_span(self):
        soup = BeautifulSoup(LABEL_INSIDE_SPAN, "html.parser")

        self.assertEqual(_extract_date_from_html(soup), "2026-09-07")

    def test_skips_foreign_span_placed_before_the_label(self):
        """Se busca hacia adelante: un span anterior es de otro indicador.

        Cubre además mayúsculas distintas y el espacio duro del rótulo.
        """
        soup = BeautifulSoup(FOREIGN_SPAN_FIRST, "html.parser")

        self.assertEqual(_extract_date_from_html(soup), "2026-09-07")

    def test_does_not_reach_a_span_outside_the_label_container(self):
        """Si el span de la fecha valor desaparece, no se toma el del indicador
        de más abajo: su fecha cae dentro de la ventana admisible y pisaría una
        fila histórica sin que nada lo delate."""
        soup = BeautifulSoup(LABEL_WITHOUT_ITS_SPAN, "html.parser")

        self.assertIsNone(_extract_date_from_html(soup))

    def test_tolerates_whitespace_variants_in_the_label(self):
        soup = BeautifulSoup(LABEL_WITH_ODD_WHITESPACE, "html.parser")

        self.assertEqual(_extract_date_from_html(soup), "2026-09-07")

    def test_returns_none_instead_of_taking_a_foreign_date(self):
        """Fail-closed: antes de estampar la fecha de otro indicador, no se lee."""
        soup = BeautifulSoup(NO_VALUE_DATE, "html.parser")

        self.assertIsNone(_extract_date_from_html(soup))


@patch("frappe.log_error")
class TestValueDatePlausibility(unittest.TestCase):
    """Una fecha mal leída no falta: PISA una fila de Currency Exchange."""

    def test_accepts_next_business_day(self, _log):
        self.assertTrue(
            _is_plausible_value_date(date(2026, 9, 7), date(2026, 9, 6))
        )

    def test_accepts_a_stale_page_showing_yesterday(self, _log):
        self.assertTrue(
            _is_plausible_value_date(date(2026, 9, 5), date(2026, 9, 6))
        )

    def test_accepts_the_longest_real_holiday_gap(self, _log):
        """Carnaval y Semana Santa dejan saltos de 5 días entre semana."""
        self.assertTrue(
            _is_plausible_value_date(date(2027, 2, 10), date(2027, 2, 5))
        )

    def test_accepts_the_forward_boundary_and_rejects_beyond_it(self, _log):
        self.assertTrue(
            _is_plausible_value_date(date(2026, 9, 12), date(2026, 9, 6))
        )
        self.assertFalse(
            _is_plausible_value_date(date(2026, 9, 13), date(2026, 9, 6))
        )

    def test_accepts_the_backward_boundary_and_rejects_beyond_it(self, _log):
        self.assertTrue(
            _is_plausible_value_date(date(2026, 9, 3), date(2026, 9, 6))
        )
        self.assertFalse(
            _is_plausible_value_date(date(2026, 9, 2), date(2026, 9, 6))
        )

    def test_rejects_a_far_future_date(self, _log):
        self.assertFalse(
            _is_plausible_value_date(date(2026, 12, 31), date(2026, 9, 6))
        )

    def test_rejects_a_past_date_that_would_overwrite_history(self, _log):
        """El 1° de mes ancla a todo cliente natural: pisarlo desalinea el mes."""
        self.assertFalse(
            _is_plausible_value_date(date(2026, 8, 1), date(2026, 9, 6))
        )


class TestTargetDates(unittest.TestCase):
    """La fecha valor apunta al próximo día hábil; los días sin BCV la heredan."""

    def test_saturday_covers_weekend_and_monday(self):
        published, fallback = _resolve_target_dates(
            date(2026, 9, 7), date(2026, 9, 5)
        )

        self.assertEqual(
            sorted(published),
            [date(2026, 9, 5), date(2026, 9, 6), date(2026, 9, 7)],
        )
        self.assertEqual(fallback, [])

    def test_sunday_covers_sunday_and_monday(self):
        published, fallback = _resolve_target_dates(
            date(2026, 9, 7), date(2026, 9, 6)
        )

        self.assertEqual(
            sorted(published), [date(2026, 9, 6), date(2026, 9, 7)]
        )
        self.assertEqual(fallback, [])

    def test_business_day_gets_the_previous_rate_not_the_next_one(self):
        """Viernes sin tasa tras una caída: el fin de semana toma la del lunes,
        pero el viernes va aparte, para cubrirse con la última conocida."""
        published, fallback = _resolve_target_dates(
            date(2026, 9, 7), date(2026, 9, 4)
        )

        self.assertNotIn(date(2026, 9, 4), published)
        self.assertEqual(fallback, [date(2026, 9, 4)])

    def test_a_weekday_holiday_on_the_first_of_month_is_preloaded(self):
        """1-ene-2027 es viernes y feriado, y esa fecha ancla la tasa de todo
        cliente natural: sin fila, `_validate_tasa_coherencia` bloquearía la
        certificación de enero entero. La lectura del jueves 31 ya la precarga
        con la tasa publicada, igual que al fin de semana que sigue."""
        published, fallback = _resolve_target_dates(
            date(2027, 1, 4), date(2026, 12, 31)
        )

        self.assertIn(date(2027, 1, 1), published)
        self.assertEqual(fallback, [date(2026, 12, 31)])

    def test_the_holiday_itself_without_preload_is_covered_backwards(self):
        """Si nadie precargó el 1-ene y el cron corre ese mismo día, desde el
        día en curso no se distingue un feriado de un día cuya tasa no se pudo
        leer: se cubre con la última conocida para que no quede sin fila."""
        published, fallback = _resolve_target_dates(
            date(2027, 1, 4), date(2027, 1, 1)
        )

        self.assertNotIn(date(2027, 1, 1), published)
        self.assertEqual(fallback, [date(2027, 1, 1)])

    def test_weekday_preload_leaves_today_as_fallback(self):
        published, fallback = _resolve_target_dates(
            date(2026, 9, 4), date(2026, 9, 3)
        )

        self.assertEqual(published, [date(2026, 9, 4)])
        self.assertEqual(fallback, [date(2026, 9, 3)])

    def test_intermediate_holidays_take_the_value_date_rate(self):
        """Si la fecha valor apunta más allá de mañana es porque el BCV no va a
        publicar esos días: son feriados, y como el fin de semana llevan la tasa
        del siguiente día hábil publicado. Solo el día en curso va aparte."""
        calendarios = [
            # (hoy, fecha valor, feriados intermedios)
            (date(2026, 2, 13), date(2026, 2, 18),
             [date(2026, 2, 16), date(2026, 2, 17)]),   # Carnaval
            (date(2026, 4, 1), date(2026, 4, 6),
             [date(2026, 4, 2), date(2026, 4, 3)]),     # Semana Santa
            (date(2026, 4, 30), date(2026, 5, 4),
             [date(2026, 5, 1)]),                       # 1° de mayo
            (date(2026, 9, 11), date(2026, 9, 15),
             [date(2026, 9, 14)]),                      # lunes 14-sep
        ]

        for today, api_date, holidays in calendarios:
            with self.subTest(today=today):
                published, fallback = _resolve_target_dates(api_date, today)

                self.assertEqual(fallback, [today])
                for holiday in holidays:
                    self.assertIn(holiday, published)
                # el tramo entero queda cubierto, cada día una sola vez
                covered = published + fallback
                self.assertEqual(len(covered), len(set(covered)))
                day = today
                while day < api_date:
                    self.assertIn(day, covered)
                    day = getdate(add_days(day, 1))

    def test_past_or_current_value_date_registers_only_that_day(self):
        self.assertEqual(
            _resolve_target_dates(date(2026, 9, 6), date(2026, 9, 6)),
            ([date(2026, 9, 6)], []),
        )


@patch("l10n_ve.utils.utils.clear_exchange_rate_cache")
@patch("l10n_ve.tasks._upsert_exchange_rate")
@patch("frappe.log_error")
class TestProcessRates(unittest.TestCase):
    """Lo que de verdad se escribe en Currency Exchange."""

    def _run(self, rates_data, today="2026-09-06", existing=(), last_rate=None):
        db = MagicMock()
        db.exists.side_effect = (
            lambda _dt, filters: filters["date"] in existing
        )
        db.get_value.return_value = last_rate

        with patch("frappe.db", db), patch(
            "l10n_ve.tasks.nowdate", return_value=today
        ):
            _process_rates(rates_data)

    def test_a_zero_rate_is_never_written(self, _log, upsert, _cache):
        """`"0.00000000"` es una cadena verdadera; `set_value` además saltea la
        validación `exchange_rate > 0` de ERPNext."""
        self._run({"date": "2026-09-07", "rates": {"USD": "0.00000000"}})

        upsert.assert_not_called()

    def test_an_implausible_date_writes_nothing(self, _log, upsert, cache):
        self._run({"date": "2026-08-01", "rates": {"USD": "813.73610000"}})

        upsert.assert_not_called()
        cache.assert_not_called()

    def test_weekend_rows_are_written_with_the_value_date_rate(
        self, _log, upsert, _cache
    ):
        self._run({"date": "2026-09-07", "rates": {"USD": "813.73610000"}})

        written = {call.args[4]: call.args[5] for call in upsert.call_args_list}
        self.assertEqual(
            sorted(written), [date(2026, 9, 6), date(2026, 9, 7)]
        )
        self.assertEqual(set(written.values()), {"813.73610000"})

    def test_an_existing_derived_row_is_not_overwritten(
        self, _log, upsert, _cache
    ):
        """El cron corre cada 3 h: pisar la fila borraría una corrección hecha
        a mano y el contador no podría ganar nunca."""
        self._run(
            {"date": "2026-09-07", "rates": {"USD": "813.73610000"}},
            existing={date(2026, 9, 6)},
        )

        written = [call.args[4] for call in upsert.call_args_list]
        self.assertEqual(written, [date(2026, 9, 7)])

    def test_today_without_rate_is_covered_with_the_last_known(
        self, _log, upsert, _cache
    ):
        """Viernes en curso sin fila tras una caída: desde acá no se distingue
        un feriado de una lectura fallida, así que se cubre hacia atrás."""
        self._run(
            {"date": "2026-09-07", "rates": {"USD": "813.73610000"}},
            today="2026-09-04",
            last_rate="807.38620000",
        )

        written = {call.args[4]: call.args[5] for call in upsert.call_args_list}
        self.assertEqual(written[date(2026, 9, 4)], "807.38620000")
        self.assertEqual(written[date(2026, 9, 7)], "813.73610000")

    def test_intermediate_holidays_are_written_with_the_value_date_rate(
        self, _log, upsert, _cache
    ):
        """Miércoles de Semana Santa: jueves y viernes el BCV no publica, igual
        que sábado y domingo, y los cuatro llevan la tasa del lunes. Solo el
        miércoles, hábil y sin fila, va con la última conocida."""
        self._run(
            {"date": "2026-04-06", "rates": {"USD": "813.73610000"}},
            today="2026-04-01",
            last_rate="807.38620000",
        )

        written = {call.args[4]: call.args[5] for call in upsert.call_args_list}
        self.assertEqual(written[date(2026, 4, 1)], "807.38620000")
        for day in (date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 4),
                    date(2026, 4, 5), date(2026, 4, 6)):
            self.assertEqual(written[day], "813.73610000")

    def test_a_monday_holiday_takes_the_value_date_rate(
        self, log, upsert, _cache
    ):
        """Caso del 11-sep-2026: el BCV publicó el viernes con fecha valor martes
        15 porque el lunes 14 no fue bancario. Sábado, domingo y lunes llevan la
        del martes. Antes el lunes iba a «la última conocida», que encontraba la
        fila del domingo recién escrita, y el log decía lo contrario."""
        self._run(
            {"date": "2026-09-15", "rates": {"USD": "842.20670000"}},
            today="2026-09-11",
            existing={date(2026, 9, 11)},
            last_rate="832.48830000",
        )

        written = {call.args[4]: call.args[5] for call in upsert.call_args_list}
        self.assertEqual(
            sorted(written),
            [date(2026, 9, 12), date(2026, 9, 13), date(2026, 9, 14),
             date(2026, 9, 15)],
        )
        self.assertEqual(set(written.values()), {"842.20670000"})
        mensaje = log.call_args.args[1]
        self.assertIn("2026-09-14", mensaje)
        self.assertNotIn("última conocida", mensaje)

    def test_a_past_value_date_never_overwrites_an_existing_row(
        self, _log, upsert, _cache
    ):
        self._run(
            {"date": "2026-09-05", "rates": {"USD": "813.73610000"}},
            existing={date(2026, 9, 5)},
        )

        upsert.assert_not_called()
