# Copyright (c) 2026, Galanet Solution and contributors
# For license information, please see license.txt
"""Numeración fiscal: un solo lugar donde se toma el siguiente número.

Había tres implementaciones del mismo problema y ninguna tenía las cuatro propiedades
a la vez: la de Company (factura, notas y número de control) formateaba bien pero leía y
escribía el contador sin bloqueo, así que dos facturas simultáneas sacaban el mismo
número; la de los comprobantes de retención sí bloqueaba la fila, pero estaba duplicada en
IVA y en ISLR; y la de la serie digital incrementaba en SQL y después releía restando uno,
sin formato y sin comprobar duplicados.

Acá vive una sola: `take_next_number` bloquea la fila del origen, formatea, comprueba que
el número esté libre y avanza el contador **dentro del mismo bloqueo**. Lo único que cambia
entre la empresa, la serie digital y las retenciones es de dónde sale el contador y con qué
formato se imprime.

Dos reglas que conviene no perder de vista:

- **No hace commit.** El número sigue la suerte de la transacción que lo pidió: si el
  documento no llega a guardarse, el correlativo vuelve atrás y no queda hueco. Un commit
  acá rompería eso, que es justo lo que hacía `increment_control_number`.
- **Tomar es una sola operación.** No existe «mirar y después incrementar»: entre esos dos
  pasos cabe otra factura. Para mirar sin tomar --una vista previa-- están los `get_*`, que
  no tocan la base.

Y una trampa de MariaDB que se midió acá, porque no es evidente: con REPEATABLE READ, si la
transacción **ya leyó** la fila del contador --y en un submit de factura la empresa se lee
varias veces, incluso por caché-- el `SELECT ... FOR UPDATE` posterior no espera: falla con
`1020, Record has changed since last read`. Medido con 10 hilos x 10 tomas sobre `tabCompany`:
sin lectura previa, 100 de 100 y ningún repetido; con `get_doc` o con `get_cached_value`
antes, 9 de cada 10 hilos mueren. Por eso, cuando eso pasa, la toma se reintenta en una
**conexión aparte**, que no arrastra esa instantánea (100 de 100 medido igual). El precio es
que ese número se consume aunque el documento después falle; es el mal menor frente a
repetir un número fiscal o a tumbarle la emisión al usuario.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

#: Formato que se asume cuando la empresa no tiene uno configurado.
FORMATO_POR_DEFECTO: str = "#####"

#: Cuántos números se saltan buscando uno libre antes de rendirse. El bucle anterior era
#: `while True`: con un correlativo desalineado consumía correlativos sin fin y colgaba el
#: submit sin decir por qué.
INTENTOS_MAXIMOS: int = 50

#: Los nombres de tabla y columna se interpolan en el SQL (no admiten parámetros), así que
#: se exige que vengan de nuestro propio código y no de un dato del usuario.
_IDENTIFICADOR = re.compile(r"^[A-Za-z0-9_ ]+$")


def format_number(number_format: str | None, number: int) -> str:
    """Aplica el formato al número.

    Los `#` no siempre vienen en un solo bloque: el número de control venezolano se
    escribe `##-########` --así lo valida `HKA_CONTROL_RE` y así está impreso en
    producción, `00-00220248`--, o sea **un solo número repartido entre los grupos**, no un
    número por grupo. Por eso se rellena a lo ancho de todos los `#` juntos y después se
    consumen los dígitos de izquierda a derecha.

    Cuando el número ya no entra a lo ancho del formato, el excedente se lo lleva el primer
    grupo, para que el tramo de la derecha conserve el ancho que la imprenta espera.
    """
    number_format = number_format or ""

    if "#" not in number_format:
        return f"{number_format}{number}"

    num_placeholders: int = number_format.count("#")
    formatted_number: str = str(number).zfill(num_placeholders)

    # `zfill` no recorta: si el número es más largo que el formato, sobran dígitos.
    leftover: int = len(formatted_number) - num_placeholders
    parts: list[str] = []
    pos: int = 0

    # El patrón parte el formato en tramos alternados de `#` y de literales, sin dejar
    # huecos: todo carácter cae en uno o en otro.
    for chunk in re.finditer(r"#+|[^#]+", number_format):
        text: str = chunk.group()

        if not text.startswith("#"):
            parts.append(text)
            continue

        width: int = len(text) + leftover
        leftover = 0
        parts.append(formatted_number[pos : pos + width])
        pos += width

    return "".join(parts)


def format_withholding_number(number_format: str | None, number: int) -> str:
    """Número de comprobante de retención: `AAAAMM` + el correlativo relleno.

    El formato de la empresa (`##############`, 14 por defecto) da el ancho total; los
    seis primeros son el año y el mes, y el resto el correlativo.
    """
    hoy = getdate(nowdate())
    digitos: int = _digitos_de_retencion(number_format)
    return f"{hoy.year}{hoy.month:02d}{str(number).zfill(digitos)}"


def parse_withholding_counter(valor, number_format: str | None) -> int:
    """Lee el contador de retenciones, que se guarda como texto.

    Acepta dos formas porque en la base conviven las dos: el correlativo a secas y, de
    instalaciones viejas, el `voucher_number` completo con el año y el mes pegados
    adelante. En ese caso se queda con la cola.
    """
    digitos: int = _digitos_de_retencion(number_format)

    if not valor:
        return 1

    try:
        entero: int = int(str(valor).strip())
    except (TypeError, ValueError):
        return 1

    if entero > 10**digitos:
        cola: int = entero % (10**digitos)
        return cola or 1

    return entero or 1


def take_next_number(
    origin_doctype: str,
    origin_name: str,
    counter_field: str,
    *,
    format_field: str | None = None,
    formatter: Callable[[str | None, int], str] = format_number,
    parser: Callable[[object, str | None], int] | None = None,
    is_free: Callable[[str], bool] | None = None,
    max_tries: int = INTENTOS_MAXIMOS,
    store_as_text: bool = False,
) -> str:
    """Toma el siguiente número del contador de `origin_name` y lo avanza.

    Args:
        origin_doctype: de dónde sale el contador (`Company`, `VE Digital Billing Series`).
        origin_name: el registro concreto.
        counter_field: la columna del contador.
        format_field: la columna con el formato, si el origen lo tiene.
        formatter: cómo se imprime el número.
        parser: cómo se lee el contador guardado; por defecto, entero.
        is_free: devuelve False si ese número ya está tomado; entonces se prueba el
            siguiente, hasta `max_tries`.
        store_as_text: el contador se guarda como texto (los de retención lo son).

    Returns:
        El número ya formateado, listo para escribir en el documento.

    Raises:
        frappe.ValidationError: si el origen no existe o si tras `max_tries` no apareció
        ninguno libre --antes eso era un bucle infinito--.
    """
    if not (_IDENTIFICADOR.match(origin_doctype) and _IDENTIFICADOR.match(counter_field)):
        frappe.throw(_("Origen de numeración inválido: {0}.{1}").format(origin_doctype, counter_field))
    if format_field and not _IDENTIFICADOR.match(format_field):
        frappe.throw(_("Campo de formato inválido: {0}").format(format_field))

    try:
        numero = _tomar(
            frappe.db, origin_doctype, origin_name, counter_field, format_field,
            formatter, parser, is_free, max_tries, store_as_text,
        )
    except frappe.QueryDeadlockError:
        # 1020: la transacción ya había leído esta fila y otro documento la movió mientras
        # tanto. Reintentar acá no sirve --la instantánea es la misma--, así que se toma en
        # una conexión aparte. Ese número se consume aunque el documento falle después.
        frappe.logger("l10n_ve").warning(
            f"Numeración de {origin_doctype} «{origin_name}»: la transacción tenía una "
            f"lectura previa de la fila; se toma el número en una conexión aparte."
        )
        numero = _tomar_en_conexion_aparte(
            origin_doctype, origin_name, counter_field, format_field,
            formatter, parser, is_free, max_tries, store_as_text,
        )

    frappe.clear_document_cache(origin_doctype, origin_name)
    return numero


def _tomar(
    db,
    origin_doctype: str,
    origin_name: str,
    counter_field: str,
    format_field: str | None,
    formatter: Callable[[str | None, int], str],
    parser: Callable[[object, str | None], int] | None,
    is_free: Callable[[str], bool] | None,
    max_tries: int,
    store_as_text: bool,
) -> str:
    """La toma en sí, contra la conexión que se le pase."""
    columnas: str = f"`{counter_field}`"
    if format_field:
        columnas += f", `{format_field}`"

    # FOR UPDATE: el que llega segundo espera acá, no se lleva el mismo número. Es el
    # patrón que ya usaban los comprobantes de retención.
    fila: list[dict] = db.sql(
        f"SELECT {columnas} FROM `tab{origin_doctype}` WHERE name = %s FOR UPDATE",  # nosemgrep
        origin_name,
        as_dict=True,
    )
    if not fila:
        frappe.throw(
            _("No se encontró {0} «{1}» para tomar el número.").format(origin_doctype, origin_name)
        )

    datos: dict = fila[0]
    formato: str | None = datos.get(format_field) if format_field else None
    bruto = datos.get(counter_field)
    actual: int = parser(bruto, formato) if parser else _a_entero(bruto)

    numero: str = ""
    for _intento in range(max_tries):
        numero = formatter(formato, actual)
        if is_free is None or is_free(numero):
            break
        actual += 1
    else:
        frappe.throw(
            _(
                "No se encontró un número libre para {0} «{1}» después de {2} intentos "
                "(último probado: {3}). Revise el correlativo y el formato."
            ).format(origin_doctype, origin_name, max_tries, numero)
        )

    db.sql(
        f"UPDATE `tab{origin_doctype}` SET `{counter_field}` = %s WHERE name = %s",  # nosemgrep
        (str(actual + 1) if store_as_text else actual + 1, origin_name),
    )
    return numero


def _tomar_en_conexion_aparte(
    origin_doctype: str,
    origin_name: str,
    counter_field: str,
    format_field: str | None,
    formatter: Callable[[str | None, int], str],
    parser: Callable[[object, str | None], int] | None,
    is_free: Callable[[str], bool] | None,
    max_tries: int,
    store_as_text: bool,
) -> str:
    """Toma el número en una conexión propia, que no arrastra la instantánea del llamador."""
    from frappe.database import get_db

    conf = frappe.conf
    db = get_db(
        socket=conf.get("db_socket"),
        host=conf.get("db_host"),
        port=conf.get("db_port"),
        user=conf.get("db_name"),
        password=conf.get("db_password"),
        cur_db_name=conf.get("db_name"),
    )
    try:
        db.begin()
        numero: str = _tomar(
            db, origin_doctype, origin_name, counter_field, format_field,
            formatter, parser, is_free, max_tries, store_as_text,
        )
        db.commit()
        return numero
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


#: Campos de la empresa por tipo de retención.
CAMPOS_DE_RETENCION: dict[str, tuple[str, str]] = {
    "vat": ("vat_withholding_correlative", "vat_withholding_format"),
    "islr": ("islr_withholding_correlative", "islr_withholding_format"),
}


def take_withholding_number(company: str, kind: str) -> tuple[str, str]:
    """Número de comprobante de retención y su período fiscal.

    Returns:
        (`voucher_number`, `MM/AAAA`).
    """
    if kind not in CAMPOS_DE_RETENCION:
        frappe.throw(_("Tipo de retención desconocido: {0}").format(kind))

    counter_field, format_field = CAMPOS_DE_RETENCION[kind]
    numero: str = take_next_number(
        "Company",
        company,
        counter_field,
        format_field=format_field,
        formatter=format_withholding_number,
        parser=parse_withholding_counter,
        store_as_text=True,
    )

    hoy = getdate(nowdate())
    return numero, f"{hoy.month:02d}/{hoy.year}"


def _digitos_de_retencion(number_format: str | None) -> int:
    """Cuántos dígitos lleva el correlativo: el ancho del formato menos el `AAAAMM`."""
    plantilla: str = number_format or "##############"
    return max(len(plantilla) - 6, 1)


def _a_entero(valor) -> int:
    """El contador como entero; un campo vacío o en cero arranca en 1."""
    try:
        entero: int = int(valor or 0)
    except (TypeError, ValueError):
        entero = 0
    return entero if entero > 0 else 1
