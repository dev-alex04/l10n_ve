"""
Venezolanización de las descripciones (``remarks``) de los asientos del Mayor.

ERPNext arma el remark de cada GL Entry en ``get_gl_dict()`` copiando el campo
``remarks``/``remark`` del documento
(``erpnext/controllers/accounts_controller.py:1304``) y acto seguido invoca el
hook regional ``update_gl_dict_with_regional_fields(doc, gl_dict)``
(``accounts_controller.py:1320``), que en el core es un ``pass`` decorado con
``@erpnext.allow_regional``. Este módulo implementa ese hook para Venezuela
(registrado en ``hooks.py`` vía ``regional_overrides``, clave
``"Venezuela, Bolivarian Republic of"``) y reemplaza el remark por una
descripción detallada en español, adaptada a la operación, según el tipo de
documento.

Limitación del punto de enganche: ``gl_dict.update(args)`` ocurre DESPUÉS del
hook (``accounts_controller.py:1333``), por lo que aquí ``gl_dict`` todavía no
tiene ``account`` / ``party`` / ``debit`` / ``credit``. Por eso la descripción
es a nivel documento (la misma para todas las líneas del voucher), no por
cuenta. Diferenciar por rol de cuenta (CxC vs IVA débito) exigiría otro
mecanismo y queda fuera de esta fase.

Cubre: Sales Invoice, Purchase Invoice, Payment Entry y las notas fiscales VE
(VE Sales Credit/Debit Note, VE Purchase Credit/Debit Note). Journal Entry y las
líneas de stock quedan fuera por decisión del equipo.

En documentos de venta emitidos, el número fiscal (bill_no/bill_control) lo
asigna TFHKA DESPUÉS del submit; por eso ``refresh_gl_remarks`` se invoca al
certificar (l10n_ve.digital_invoice.tfhka_integration._sync_gl_entries_date)
para reescribir el remark del Mayor ya con el número fiscal.

Los ``builders`` operan sobre cualquier objeto con ``.get()`` (un doc real o un
``frappe._dict`` con los campos necesarios), de modo que el backfill los
reutiliza sin instanciar el documento completo.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, fmt_money, formatdate

# Campos que cada builder necesita del documento; permite leer con un solo
# get_value (sin instanciar el doc completo) desde el backfill y refresh_gl_remarks.
DOC_FIELDS: dict[str, list[str]] = {
    "Sales Invoice": [
        "customer", "customer_name", "tax_id",
        "bill_no", "bill_control", "grand_total", "currency", "is_return",
    ],
    "Purchase Invoice": [
        "supplier", "supplier_name", "tax_id",
        "bill_no", "bill_control", "grand_total", "currency", "is_return",
    ],
    "Payment Entry": [
        "payment_type", "party", "party_name",
        "paid_amount", "received_amount", "paid_from", "paid_to",
        "paid_from_account_currency", "paid_to_account_currency",
        "mode_of_payment", "reference_no", "reference_date", "custom_remarks",
    ],
    "VE Sales Credit Note": [
        "customer", "customer_name", "tax_id",
        "bill_no", "bill_control", "grand_total", "currency", "return_against",
    ],
    "VE Sales Debit Note": [
        "customer", "customer_name", "tax_id",
        "bill_no", "bill_control", "grand_total", "currency", "return_against",
    ],
    "VE Purchase Credit Note": [
        "supplier", "supplier_name", "tax_id",
        "bill_no", "bill_control", "grand_total", "currency", "return_against",
    ],
    "VE Purchase Debit Note": [
        "supplier", "supplier_name", "tax_id",
        "bill_no", "bill_control", "grand_total", "currency", "return_against",
    ],
}

# Descripciones que jamás se sobreescriben: las setean rutas ajenas al hook
# regional (líneas de stock, reversas de anulación, offsetting dimensional).
PROTECTED_REMARK_PREFIXES: tuple[str, ...] = (
    "Accounting Entry for Stock",
    "Stock Adjustment",
    "On cancellation of",
    "Offsetting for Accounting Dimension",
)


def update_gl_dict_with_regional_fields(doc, gl_dict) -> None:
    """Hook regional: reescribe ``gl_dict["remarks"]`` con la descripción VE.

    Se invoca una vez por cada línea del asiento; como la descripción solo
    depende del documento, se calcula una vez y se cachea en ``doc.flags``.
    """
    builder = _REMARKS_BUILDERS.get(doc.doctype)
    if not builder:
        return

    cached = doc.flags.get("_ve_gl_remarks")
    if cached is None:
        cached = doc.flags._ve_gl_remarks = builder(doc) or ""

    if cached:
        gl_dict["remarks"] = cached


def build_remarks_for(doctype: str, doc) -> str | None:
    """Devuelve la descripción VE para ``doc`` según su tipo, o ``None`` si no
    aplica (tipo no soportado, o Payment Entry con ``custom_remarks`` donde se
    respeta la nota del usuario). Reutilizable por el backfill."""
    builder = _REMARKS_BUILDERS.get(doctype)
    return builder(doc) if builder else None


def _gl_remarks_filter(doctype: str, voucher_no: str, new_remark: str):
    """Devuelve ``(where_sql, params)`` para las líneas GL de un voucher que
    deben recibir el remark VE: no anuladas, no protegidas (stock/reversa/
    dimensión) y distintas del texto nuevo (idempotencia)."""
    protected = " ".join(
        "AND COALESCE(remarks, '') NOT LIKE %s" for _ in PROTECTED_REMARK_PREFIXES
    )
    where = (
        "voucher_type = %s AND voucher_no = %s AND is_cancelled = 0 "
        f"{protected} AND COALESCE(remarks, '') <> %s"
    )
    params = (
        [doctype, voucher_no]
        + [f"{prefix}%" for prefix in PROTECTED_REMARK_PREFIXES]
        + [new_remark]
    )
    return where, params


def apply_gl_remarks(doctype: str, voucher_no: str, new_remark: str, dry_run: bool = False) -> int:
    """Cuenta (``dry_run``) o aplica el remark VE a las líneas GL de un voucher
    con un solo UPDATE. Idempotente. Devuelve las líneas afectadas.

    Única fuente de la lógica "qué líneas tocar", compartida por el hook de
    certificación (refresh_gl_remarks) y el backfill."""
    where, params = _gl_remarks_filter(doctype, voucher_no, new_remark)
    count = frappe.db.sql(f"SELECT COUNT(*) FROM `tabGL Entry` WHERE {where}", params)[0][0]
    if count and not dry_run:
        frappe.db.sql(
            f"UPDATE `tabGL Entry` SET remarks = %s WHERE {where}", [new_remark] + params
        )
    return count


def refresh_gl_remarks(doctype: str, voucher_no: str) -> None:
    """Recalcula el remark VE de los GL Entry de un comprobante y lo reescribe.

    Pensado para llamarse tras la certificación HKA (cuando ya existen bill_no/
    bill_control), de modo que el número fiscal aparezca en el Mayor sin esperar
    al backfill manual. Idempotente y defensivo: no propaga excepciones para no
    romper el flujo llamador (la certificación).
    """
    try:
        fields = DOC_FIELDS.get(doctype)
        if not fields:
            return
        row = frappe.db.get_value(doctype, voucher_no, fields, as_dict=True)
        if not row:
            return
        new_remark = build_remarks_for(doctype, row)
        if new_remark:
            apply_gl_remarks(doctype, voucher_no, new_remark)
    except Exception as exc:  # nunca romper la certificación por el remark
        frappe.logger("l10n_ve").error(
            f"refresh_gl_remarks {doctype} {voucher_no}: {exc}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _join(*parts: str) -> str:
    """Une las partes no vacías con un separador legible."""
    return " · ".join(part for part in parts if part)


def _money(amount, currency: str | None) -> str:
    """Formatea un monto (en magnitud) en su moneda; vacío si falta la moneda.

    Se usa abs() a propósito: la dirección la da el rótulo (Venta / Devolución /
    Nota de crédito…), no el signo. Una devolución trae grand_total negativo y
    no queremos mostrar "por USD -50,00".
    """
    if not currency:
        return ""
    return fmt_money(abs(flt(amount)), currency=currency)


def _date(value) -> str:
    return formatdate(value, "dd-MM-yyyy") if value else ""


def _party_label(name: str | None, fallback: str | None, rif: str | None) -> str:
    label = name or fallback or ""
    if label and rif:
        return f"{label} (RIF {rif})"
    return label


def _fiscal_label(bill_no: str | None, bill_control: str | None, doc_word: str) -> str:
    """Ej.: 'Doc. fiscal 00012345, control 00067890'."""
    if bill_no and bill_control:
        return f"{doc_word} {bill_no}, control {bill_control}"
    if bill_no:
        return f"{doc_word} {bill_no}"
    if bill_control:
        return f"Control {bill_control}"
    return ""


# ---------------------------------------------------------------------------
# Builders por tipo de documento
# ---------------------------------------------------------------------------

def _sales_invoice_remarks(doc) -> str | None:
    # No se consulta doc.remarks: en Sales Invoice ese campo no es una nota del
    # usuario, lo secuestra la certificación TFHKA (guarda ahí su respuesta JSON,
    # después del submit). La descripción del Mayor se genera siempre.
    tercero = _party_label(doc.get("customer_name"), doc.get("customer"), doc.get("tax_id"))
    fiscal = _fiscal_label(doc.get("bill_no"), doc.get("bill_control"), "Doc. fiscal")
    monto = _money(doc.get("grand_total"), doc.get("currency"))
    monto_part = f"por {monto}" if monto else ""

    if doc.get("is_return"):
        cabeza = f"Devolución en venta a {tercero}" if tercero else "Devolución en venta"
    else:
        cabeza = f"Venta a {tercero}" if tercero else "Venta"

    return _join(cabeza, fiscal, monto_part)


def _purchase_invoice_remarks(doc) -> str | None:
    # No se consulta doc.remarks: en Purchase Invoice ERPNext lo fija solo con el
    # auto-string "Against Supplier Invoice ..." (create_remarks, purchase_invoice.py:325),
    # no es una nota del usuario. La descripción del Mayor se genera siempre.
    tercero = _party_label(doc.get("supplier_name"), doc.get("supplier"), doc.get("tax_id"))
    fiscal = _fiscal_label(doc.get("bill_no"), doc.get("bill_control"), "Factura")
    monto = _money(doc.get("grand_total"), doc.get("currency"))
    monto_part = f"por {monto}" if monto else ""

    if doc.get("is_return"):
        cabeza = f"Devolución en compra a {tercero}" if tercero else "Devolución en compra"
    else:
        cabeza = f"Compra a {tercero}" if tercero else "Compra"

    return _join(cabeza, fiscal, monto_part)


def _payment_entry_remarks(doc) -> str | None:
    # custom_remarks=1 significa que el usuario redactó su propio remark.
    if doc.get("custom_remarks"):
        return None

    modo = doc.get("mode_of_payment")
    modo_part = f"vía {modo}" if modo else ""

    ref_no = doc.get("reference_no")
    ref_part = ""
    if ref_no:
        ref_date = _date(doc.get("reference_date"))
        ref_part = f"Ref. {ref_no} del {ref_date}" if ref_date else f"Ref. {ref_no}"

    payment_type = doc.get("payment_type")

    if payment_type == "Internal Transfer":
        monto = _money(doc.get("paid_amount"), doc.get("paid_from_account_currency"))
        cabeza = f"Transferencia interna de {doc.get('paid_from')} a {doc.get('paid_to')}"
        return _join(cabeza, f"por {monto}" if monto else "", ref_part)

    tercero = doc.get("party_name") or doc.get("party") or ""

    if payment_type == "Receive":
        amount = doc.get("paid_amount")
        currency = doc.get("party_account_currency") or doc.get("paid_from_account_currency")
        cabeza = f"Cobro a {tercero}" if tercero else "Cobro"
    else:  # Pay
        amount = doc.get("received_amount") or doc.get("paid_amount")
        currency = doc.get("party_account_currency") or doc.get("paid_to_account_currency")
        cabeza = f"Pago a {tercero}" if tercero else "Pago"

    monto = _money(amount, currency)
    monto_part = f"por {monto}" if monto else ""

    # Documentos a los que se aplicó el pago (recupera el detalle que el remark
    # nativo daba por línea). doc.references está en el doc vivo; el backfill lo
    # inyecta. Se capa para no inflar la descripción.
    ref_names = [
        r.get("reference_name")
        for r in (doc.get("references") or [])
        if r.get("reference_name")
    ]
    aplicado = ""
    if ref_names:
        aplicado = "aplicado a " + ", ".join(ref_names[:4])
        if len(ref_names) > 4:
            aplicado += f" y {len(ref_names) - 4} más"

    return _join(cabeza, monto_part, aplicado, modo_part, ref_part)


def _sales_note_remarks(doc, lead: str) -> str:
    """Descripción para notas fiscales de venta (crédito/débito). El rótulo
    lo determina el doctype (no se ramifica por is_return)."""
    tercero = _party_label(doc.get("customer_name"), doc.get("customer"), doc.get("tax_id"))
    fiscal = _fiscal_label(doc.get("bill_no"), doc.get("bill_control"), "Doc. fiscal")
    monto = _money(doc.get("grand_total"), doc.get("currency"))
    monto_part = f"por {monto}" if monto else ""
    afecta = f"afecta {doc.get('return_against')}" if doc.get("return_against") else ""
    cabeza = f"{lead} a {tercero}" if tercero else lead
    return _join(cabeza, fiscal, monto_part, afecta)


def _purchase_note_remarks(doc, lead: str) -> str:
    """Descripción para notas fiscales de compra (crédito/débito)."""
    tercero = _party_label(doc.get("supplier_name"), doc.get("supplier"), doc.get("tax_id"))
    fiscal = _fiscal_label(doc.get("bill_no"), doc.get("bill_control"), "Factura")
    monto = _money(doc.get("grand_total"), doc.get("currency"))
    monto_part = f"por {monto}" if monto else ""
    afecta = f"afecta {doc.get('return_against')}" if doc.get("return_against") else ""
    cabeza = f"{lead} a {tercero}" if tercero else lead
    return _join(cabeza, fiscal, monto_part, afecta)


_REMARKS_BUILDERS = {
    "Sales Invoice": _sales_invoice_remarks,
    "Purchase Invoice": _purchase_invoice_remarks,
    "Payment Entry": _payment_entry_remarks,
    "VE Sales Credit Note": lambda doc: _sales_note_remarks(doc, "Nota de crédito de venta"),
    "VE Sales Debit Note": lambda doc: _sales_note_remarks(doc, "Nota de débito de venta"),
    "VE Purchase Credit Note": lambda doc: _purchase_note_remarks(doc, "Nota de crédito de compra"),
    "VE Purchase Debit Note": lambda doc: _purchase_note_remarks(doc, "Nota de débito de compra"),
}
