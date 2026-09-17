# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Reembolsos que quedaron sin enlazar con el cobro que devolvieron.

Un reembolso registrado suelto -- un «Pago» contra la cuenta de anticipos, o un asiento que la
debita -- deja los documentos y el mayor diciendo cosas distintas: el cobro sigue ofreciendo un
anticipo que ya salió del banco. Si esa plata todavía no pagó nada es un crédito que no existe;
si ya pagó una factura, la factura figura pagada y la deuda real del cliente se esconde en la
cuenta de anticipos, donde ni el portal ni el corte la ven (GRUPO VITALIS, 07-09-2026).

La detección no busca reembolsos: busca el descuadre. Para cada cliente compara lo que sus
cobros ofrecen sin aplicar contra lo que el mayor dice que tiene a favor. Recién cuando no
coinciden va a buscar de dónde viene, y ahí sí distingue entre un «Pago» y un asiento. Así
aparecen también los reembolsos asentados a mano, que el backfill de domina_galanet no ve.

La corrección hace lo mismo que se hace a mano, en una sola transacción:

1. Deshace la aplicación del cobro a la factura que se pagó con la plata devuelta.
2. Crea el asiento que enlaza el reembolso con el cobro, y le aplica el anticipo.
3. Si al deshacer se soltó de más -- lo habitual, porque lo devuelto se mezcla con plata buena
   en el mismo cruce --, le devuelve ese sobrante a la misma factura.

Al terminar comprueba que los documentos digan lo mismo que el mayor. Si no, no deja nada.
"""

from itertools import combinations

import frappe
from erpnext.accounts.party import get_party_account
from frappe import _
from frappe.utils import cint, flt, fmt_money, get_link_to_form, getdate, nowdate

from l10n_ve.overrides.advance_refund import _refund_dimensions

FIX_ROLES: tuple[str, ...] = (
    "Accounts Manager",
    "Accounts User",
    "ISP Finance Pro",
    "System Manager",
)


# ────────────────────────────────── Diagnóstico ────────────────────────────────── #


@frappe.whitelist()
def scan(
    company: str | None = None, party: str | None = None, tolerance: float = 1.0
) -> list[dict]:
    """Clientes cuyos cobros ofrecen MÁS anticipo del que dice el mayor.

    Solo interesa esa dirección: es la que deja al sistema ofreciendo plata que ya salió del
    banco. Al revés -- el mayor con más saldo a favor que los documentos -- son los ajustes por
    diferencia en cambio, que acreditan la cuenta de anticipos sin tocar ningún cobro.

    `tolerance` descarta las diferencias de céntimos, que son redondeos de esos mismos ajustes.
    Devuelve un caso por cliente y cuenta, con lo que se puede corregir solo y lo que hay que
    revisar a mano. No modifica nada.
    """
    frappe.has_permission("Payment Entry", throw=True)
    accounts: list[str] = _advance_accounts(company)
    if not accounts:
        return []

    offered: dict = _offered_by_party(accounts, company, party)
    ledger: dict = _ledger_by_party(accounts, company, party)

    cases: list[dict] = []
    for key in sorted(set(offered) | set(ledger)):
        available: float = flt(offered.get(key, 0.0), 2)
        balance: float = flt(ledger.get(key, 0.0), 2)
        if flt(available - balance, 2) < flt(tolerance, 2):
            continue
        cases.append(_build_case(key, available, balance))
    return cases


def _advance_accounts(company: str | None) -> list[str]:
    """Cuentas donde viven los anticipos de clientes, según los propios cobros."""
    filters: dict = {
        "docstatus": 1,
        "payment_type": "Receive",
        "party_type": "Customer",
        "book_advance_payments_in_separate_party_account": 1,
    }
    if company:
        filters["company"] = company
    return list(
        {
            row
            for row in frappe.get_all(
                "Payment Entry", filters=filters, pluck="paid_from"
            )
            if row
        }
    )


def _offered_by_party(
    accounts: list[str], company: str | None, party: str | None
) -> dict:
    """Lo que los cobros de cada cliente ofrecen sin aplicar, por empresa y cuenta."""
    conditions: list = [
        "pe.docstatus = 1",
        "pe.payment_type = 'Receive'",
        "pe.party_type = 'Customer'",
        "pe.paid_from IN %s",
    ]
    values: list = [tuple(accounts)]
    if company:
        conditions.append("pe.company = %s")
        values.append(company)
    if party:
        conditions.append("pe.party = %s")
        values.append(party)

    rows = frappe.db.sql(
        f"""SELECT pe.company, pe.party, pe.paid_from AS account,
            ROUND(SUM(pe.unallocated_amount), 2) AS offered
        FROM `tabPayment Entry` pe
        WHERE {" AND ".join(conditions)}
        GROUP BY pe.company, pe.party, pe.paid_from""",
        values,
        as_dict=True,
    )
    return {
        (r.company, r.party, r.account): flt(r.offered, 2)
        for r in rows
        if flt(r.offered, 2)
    }


def _ledger_by_party(
    accounts: list[str], company: str | None, party: str | None
) -> dict:
    """Saldo a favor de cada cliente en esas cuentas, según el mayor."""
    # Un movimiento sin cliente en esa cuenta es otra anomalía, no un reembolso sin enlazar.
    conditions: list = [
        "gl.party_type = 'Customer'",
        "gl.party IS NOT NULL",
        "gl.party != ''",
        "gl.is_cancelled = 0",
        "gl.account IN %s",
    ]
    values: list = [tuple(accounts)]
    if company:
        conditions.append("gl.company = %s")
        values.append(company)
    if party:
        conditions.append("gl.party = %s")
        values.append(party)

    rows = frappe.db.sql(
        f"""SELECT gl.company, gl.party, gl.account,
            ROUND(SUM(gl.credit) - SUM(gl.debit), 2) AS balance
        FROM `tabGL Entry` gl
        WHERE {" AND ".join(conditions)}
        GROUP BY gl.company, gl.party, gl.account""",
        values,
        as_dict=True,
    )
    return {(r.company, r.party, r.account): flt(r.balance, 2) for r in rows}


def _build_case(key: tuple, available: float, balance: float) -> dict:
    """Arma el caso de un cliente: de dónde viene el descuadre y qué se puede hacer."""
    company, party, account = key
    case = frappe._dict(
        company=company,
        party=party,
        # El nombre visible: `party` es el identificador de la base y no le dice nada a nadie.
        party_name=frappe.db.get_value("Customer", party, "customer_name") or party,
        advance_account=account,
        offered=available,
        ledger=balance,
        difference=flt(available - balance, 2),
        refunds=[],
        undo=None,
        tied_invoices=None,
        problem=None,
    )
    case.refunds = _refunds(company, party, account)
    if not case.refunds:
        case.problem = _(
            "No se encontró el reembolso que explica la diferencia: hay que revisar los movimientos "
            "de la cuenta de anticipos de este cliente."
        )
        return case

    refunded: float = flt(sum(flt(r.amount) for r in case.refunds), 2)
    if refunded != case.difference:
        case.problem = _(
            "Los reembolsos suman {0} y la diferencia es {1}: hay otros movimientos en la cuenta de "
            "anticipos que hay que revisar antes."
        ).format(_money(refunded, company), _money(case.difference, company))
        return case

    problems: list[str] = [r.problem for r in case.refunds if r.problem]
    if problems:
        case.problem = " ".join(problems)
        return case

    if case.offered < case.difference:
        # La plata devuelta ya pagó facturas: hay que soltar esa aplicación antes de enlazar.
        case.undo = _allocation_to_undo(case)
        if not case.undo and case.tied_invoices:
            case.problem = _(
                "Más de una aplicación encaja igual de bien, y sobre facturas distintas ({0}): "
                "hay que decidir de cuál factura se saca la deuda."
            ).format(", ".join(case.tied_invoices))
            return case
        if not case.undo:
            case.problem = _(
                "No hay ninguna aplicación de un cobro a una factura que alcance para liberar lo que "
                "falta: el saldo devuelto se repartió entre varias facturas y hay que decidir de cuál "
                "se saca."
            )
    return case


def _refunds(company: str, party: str, account: str) -> list[dict]:
    """Reembolsos que explican el descuadre: «Pago» sueltos y asientos que debitan anticipos."""
    refunds: list[dict] = []

    for row in frappe.db.sql(
        """SELECT name, posting_date, creation, ROUND(unallocated_amount, 2) AS amount
        FROM `tabPayment Entry`
        WHERE docstatus = 1 AND payment_type = 'Pay' AND party_type = 'Customer'
          AND party = %s AND company = %s AND paid_to = %s AND unallocated_amount > 0""",
        (party, company, account),
        as_dict=True,
    ):
        if _already_linked("Payment Entry", row.name):
            continue
        row.doctype = "Payment Entry"
        row.problem = _not_a_refund(
            row.name, _bank_movements("Payment Entry", row.name)
        )
        refunds.append(row)

    for row in frappe.db.sql(
        """SELECT ja.parent AS name, je.posting_date, je.creation, ROUND(ja.debit, 2) AS amount
        FROM `tabJournal Entry Account` ja
        JOIN `tabJournal Entry` je ON je.name = ja.parent
        WHERE ja.docstatus = 1 AND ja.party_type = 'Customer' AND ja.party = %s
          AND je.company = %s AND ja.account = %s AND ja.debit > 0""",
        (party, company, account),
        as_dict=True,
    ):
        if _already_linked("Journal Entry", row.name):
            continue
        row.doctype = "Journal Entry"
        row.problem = _not_a_refund(
            row.name, _bank_movements("Journal Entry", row.name)
        )
        refunds.append(row)

    return sorted(refunds, key=lambda r: (r.posting_date, r.creation))


def _already_linked(doctype: str, name: str) -> bool:
    """¿Ya existe el asiento que enlaza ese reembolso con su cobro?"""
    return bool(
        frappe.db.exists(
            "Journal Entry Account",
            {"reference_type": doctype, "reference_name": name, "docstatus": 1},
        )
    )


def _bank_movements(doctype: str, name: str) -> list[dict]:
    """Movimientos del extracto conciliados con ese documento."""
    return frappe.db.sql(
        """SELECT bt.name, bt.deposit, bt.withdrawal
        FROM `tabBank Transaction Payments` btp
        JOIN `tabBank Transaction` bt ON bt.name = btp.parent
        WHERE btp.payment_document = %s AND btp.payment_entry = %s AND bt.docstatus = 1""",
        (doctype, name),
        as_dict=True,
    )


def _not_a_refund(name: str, movements: list[dict]) -> str | None:
    """Por qué ese documento no parece un reembolso de verdad, o None si salió plata del banco."""
    if not movements:
        return _(
            "{0} no está conciliado con ningún movimiento del banco: puede ser la reversión contable "
            "de un cobro mal registrado, y hay que revisar el cobro original."
        ).format(name)
    if not any(flt(m.withdrawal) > 0 for m in movements):
        return _(
            "{0} está conciliado con un DEPÓSITO del banco ({1}): parece un cobro registrado como "
            "pago, y hay que anularlo y registrarlo como cobro."
        ).format(name, ", ".join(m.name for m in movements))
    return None


def _allocation_to_undo(case: dict) -> dict | None:
    """Qué aplicaciones hay que deshacer para que la factura vuelva a mostrar la deuda.

    «Desconciliar pago» deshace la aplicación entera de un cobro a una factura, así que casi
    nunca coincide con lo que falta. Se busca, en este orden: una aplicación por el monto justo;
    una combinación de aplicaciones a la MISMA factura que sume justo; o la aplicación más chica
    que alcance, deshaciendo de más y devolviéndole el sobrante a esa factura al final.

    Ese último caso es el que importa: sin él, cinco de cada seis casos de Galanet quedaban para
    revisar a mano, porque lo devuelto se había mezclado con plata buena dentro del mismo cruce.

    En cada nivel se junta a TODOS los que encajan, no al primero: ver :func:`_single_invoice`.
    """
    missing: float = flt(case.difference - case.offered, 2)
    candidates: list[dict] = _applications_after_refund(case)
    if not candidates:
        return None

    exact: list[dict] = [
        {
            "applications": [row],
            "invoice": row.sales_invoice,
            "undone": missing,
            "surplus": 0.0,
        }
        for row in candidates
        if flt(row.amount, 2) == missing
    ]
    if exact:
        return _single_invoice(case, exact)

    by_invoice: dict = {}
    for row in candidates:
        by_invoice.setdefault(row.sales_invoice, []).append(row)
    combos: list[dict] = [
        {
            "applications": list(combo),
            "invoice": invoice,
            "undone": missing,
            "surplus": 0.0,
        }
        for invoice, rows in by_invoice.items()
        for size in (2, 3)
        for combo in combinations(rows, size)
        if flt(sum(flt(row.amount) for row in combo), 2) == missing
    ]
    if combos:
        return _single_invoice(case, combos)

    bigger: list[dict] = sorted(
        (row for row in candidates if flt(row.amount, 2) > missing),
        key=lambda row: flt(row.amount, 2),
    )
    if not bigger:
        return None
    smallest: float = flt(bigger[0].amount, 2)
    return _single_invoice(
        case,
        [
            {
                "applications": [row],
                "invoice": row.sales_invoice,
                "undone": smallest,
                "surplus": flt(smallest - missing, 2),
            }
            for row in bigger
            if flt(row.amount, 2) == smallest
        ],
    )


def _single_invoice(case: dict, options: list[dict]) -> dict | None:
    """La opción elegida, siempre que las que empatan sean todas de la MISMA factura.

    Cuando dos aplicaciones encajan igual de bien, quedarse con la primera es elegir al azar de
    qué factura se saca la deuda, y nada lo atraparía después: :func:`_verify` solo compara el
    agregado del cliente contra el mayor, no la factura que se tocó. Elegir mal deja la factura
    buena mostrando deuda y la que sí se pagó con la plata devuelta intacta y marcada «Pagada»
    -- el mismo problema que esto viene a resolver, pero causado por la corrección.

    Si el empate es dentro de una misma factura da igual cuál se deshaga: el resultado en esa
    factura es el mismo. Si son facturas distintas, el caso se manda a revisar a mano.

    Hoy ninguno de los 19 casos de Galanet empata, así que esto no cambia lo que ya se corrige;
    es para lo que viene: la base tiene 603 grupos de aplicaciones del mismo cliente por el
    mismo monto, que es lo normal en facturación mensual.
    """
    if not options:
        return None
    invoices: set = {option["invoice"] for option in options}
    if len(invoices) > 1:
        case.tied_invoices = sorted(invoices)
        return None
    return options[0]


def _applications_after_refund(case: dict) -> list[dict]:
    """Aplicaciones de cobros a facturas que pudieron usar el saldo devuelto.

    Primero las del cobro que tiene el mismo monto que un reembolso -- es el que devolvieron, y
    si ya había pagado una factura, esa es la aplicación -- y después las hechas desde que se
    registró el reembolso, de la más reciente a la más vieja.
    """
    amounts: tuple = tuple({flt(r.amount, 2) for r in case.refunds})
    twins: list[str] = frappe.db.sql(
        """SELECT name FROM `tabPayment Entry`
        WHERE docstatus = 1 AND payment_type = 'Receive' AND party_type = 'Customer' AND party = %s
          AND company = %s AND paid_from = %s AND ROUND(paid_amount, 2) IN %s""",
        (case.party, case.company, case.advance_account, amounts),
        pluck=True,
    )

    rows: list[dict] = []
    if twins:
        rows += frappe.db.sql(
            """SELECT voucher_no AS payment_entry, against_voucher_no AS sales_invoice,
                ROUND(-SUM(amount), 2) AS amount, MAX(creation) AS applied_on
            FROM `tabPayment Ledger Entry`
            WHERE party_type = 'Customer' AND party = %s AND company = %s
              AND voucher_type = 'Payment Entry' AND against_voucher_type = 'Sales Invoice'
              AND delinked = 0 AND amount < 0 AND voucher_no IN %s
            GROUP BY voucher_no, against_voucher_no
            ORDER BY applied_on DESC""",
            (case.party, case.company, tuple(twins)),
            as_dict=True,
        )
    rows += frappe.db.sql(
        """SELECT voucher_no AS payment_entry, against_voucher_no AS sales_invoice,
            ROUND(-SUM(amount), 2) AS amount, MAX(creation) AS applied_on
        FROM `tabPayment Ledger Entry`
        WHERE party_type = 'Customer' AND party = %s AND company = %s
          AND voucher_type = 'Payment Entry' AND against_voucher_type = 'Sales Invoice'
          AND delinked = 0 AND amount < 0 AND creation > %s
        GROUP BY voucher_no, against_voucher_no
        ORDER BY applied_on DESC""",
        (case.party, case.company, min(r.creation for r in case.refunds)),
        as_dict=True,
    )

    seen: set = set()
    unique: list[dict] = []
    for row in rows:
        key = (row.payment_entry, row.sales_invoice)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _money(amount: float, company: str) -> str:
    return fmt_money(
        amount, currency=frappe.get_cached_value("Company", company, "default_currency")
    )


# ─────────────────────────────────── Corrección ─────────────────────────────────── #


@frappe.whitelist()
def describe(company: str, party: str, advance_account: str) -> dict:
    """Lo que la corrección va a hacer con ese cliente, en el idioma de quien la aprueba."""
    frappe.has_permission("Payment Entry", throw=True)
    case = _single_case(company, party, advance_account)
    if case.get("problem"):
        return {"can_fix": False, "problem": case["problem"], "lines": []}

    lines: list[str] = []
    undo = case["undo"]
    if undo:
        lines.append(
            _(
                "Se le quita a la factura {0} los {1} que tenía aplicados de {2}."
            ).format(
                undo["invoice"],
                _money(undo["undone"], company),
                ", ".join(a["payment_entry"] for a in undo["applications"]),
            )
        )
        if flt(undo["surplus"], 2) > 0:
            lines.append(
                _(
                    "De eso, {0} vuelven a esa misma factura: es plata buena que se soltó de más."
                ).format(_money(undo["surplus"], company))
            )
    for refund in case["refunds"]:
        lines.append(
            _(
                "Se crea el asiento que enlaza el reembolso {0} del {1} con el cobro que devolvió."
            ).format(
                refund["name"],
                frappe.format(refund["posting_date"], {"fieldtype": "Date"}),
            )
        )
    if undo:
        lines.append(
            _(
                "La factura {0} va a quedar pendiente por {1}, que es lo que se le devolvió."
            ).format(
                undo["invoice"],
                _money(flt(case["difference"] - case["offered"], 2), company),
            )
        )
    else:
        lines.append(
            _("Al terminar, sus cobros van a ofrecer {0}, igual que el mayor.").format(
                _money(case["ledger"], company)
            )
        )
    return {"can_fix": True, "problem": None, "lines": lines}


@frappe.whitelist()
def fix(
    company: str, party: str, advance_account: str, posting_date: str | None = None
) -> dict:
    """Corrige el caso de ese cliente. Todo o nada."""
    if not any(role in frappe.get_roles() for role in FIX_ROLES):
        frappe.throw(
            _("No tiene permiso para corregir reembolsos."), frappe.PermissionError
        )
    frappe.has_permission("Journal Entry", ptype="create", throw=True)
    frappe.has_permission("Journal Entry", ptype="submit", throw=True)

    case = _single_case(company, party, advance_account)
    if case.get("problem"):
        frappe.throw(case["problem"])

    posting = getdate(posting_date or nowdate())
    created: list[str] = []
    savepoint: str = "advance_refund_fix"
    frappe.db.savepoint(savepoint)
    try:
        if case["undo"]:
            for application in case["undo"]["applications"]:
                created.append(_unreconcile(case, application))
        for refund in case["refunds"]:
            created.append(_link_refund(case, refund, posting))
        if case["undo"] and flt(case["undo"]["surplus"], 2) > 0:
            _return_surplus(case)
        _verify(company, party, advance_account)
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
    return {"customer": party, "documents": created}


def _single_case(company: str, party: str, advance_account: str) -> dict:
    cases = [
        c
        for c in scan(company=company, party=party)
        if c["advance_account"] == advance_account
    ]
    if not cases:
        frappe.throw(
            _("{0} ya no tiene reembolsos sin enlazar en {1}.").format(
                party, advance_account
            )
        )
    return cases[0]


def _unreconcile(case: dict, application: dict) -> str:
    """Deshace una aplicación de un cobro a una factura, con «Desconciliar pago»."""
    account: str = frappe.db.get_value(
        "Payment Entry Reference",
        {
            "parent": application["payment_entry"],
            "reference_doctype": "Sales Invoice",
            "reference_name": application["sales_invoice"],
        },
        "account",
    ) or get_party_account("Customer", case["party"], case["company"])

    doc = frappe.new_doc("Unreconcile Payment")
    doc.company = case["company"]
    doc.voucher_type = "Payment Entry"
    doc.voucher_no = application["payment_entry"]
    doc.append(
        "allocations",
        {
            "reference_doctype": "Sales Invoice",
            "reference_name": application["sales_invoice"],
            "allocated_amount": flt(application["amount"], 2),
            "account": account,
            "party_type": "Customer",
            "party": case["party"],
            "account_currency": frappe.get_cached_value(
                "Account", account, "account_currency"
            ),
        },
    )
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc.name


def _return_surplus(case: dict) -> None:
    """Le devuelve a la factura el sobrante que se soltó de más al desconciliar.

    Cuando la aplicación que hay que deshacer es más grande que lo devuelto -- lo habitual,
    porque la plata devuelta se mezcla con plata buena en el mismo cruce --, la factura queda
    debiendo de más y el cliente con anticipo de sobra. Esto lo vuelve a cruzar, así la factura
    termina debiendo exactamente lo que se le devolvió al cliente y ni un bolívar más.
    """
    _reconcile(
        case["company"],
        case["party"],
        case["advance_account"],
        invoice=case["undo"]["invoice"],
        payment=None,
        expected=flt(case["undo"]["surplus"], 2),
        cap=True,
    )


def _link_refund(case: dict, refund: dict, posting_date) -> str:
    """Asiento de Cuentas por Cobrar contra Anticipos por el reembolso, con el anticipo aplicado."""
    receivable: str = get_party_account("Customer", case["party"], case["company"])
    amount: float = flt(refund["amount"], 2)
    origin = frappe.get_doc(refund["doctype"], refund["name"])
    dimensions: dict = (
        _refund_dimensions(origin)
        if refund["doctype"] == "Payment Entry"
        else _je_dimensions(origin)
    )

    journal_entry = frappe.new_doc("Journal Entry")
    journal_entry.voucher_type = "Journal Entry"
    journal_entry.company = case["company"]
    journal_entry.posting_date = posting_date
    journal_entry.user_remark = _(
        "Enlaza el reembolso {0} con el anticipo que devolvió"
    ).format(refund["name"])
    journal_entry.append(
        "accounts",
        {
            "account": receivable,
            "party_type": "Customer",
            "party": case["party"],
            "debit_in_account_currency": amount,
            **dimensions,
        },
    )
    journal_entry.append(
        "accounts",
        {
            "account": case["advance_account"],
            "party_type": "Customer",
            "party": case["party"],
            "credit_in_account_currency": amount,
            # La referencia al reembolso marca que ya se enlazó (ver `_already_linked`).
            "reference_type": refund["doctype"],
            "reference_name": refund["name"],
            **dimensions,
        },
    )
    journal_entry.insert(ignore_permissions=True)
    journal_entry.submit()

    _reconcile(
        case["company"],
        case["party"],
        case["advance_account"],
        invoice=journal_entry.name,
        payment=None,
        expected=amount,
    )
    _close_refund_receipt(refund, journal_entry.name, amount)
    origin.add_comment(
        "Comment",
        text=_("Enlazado con el anticipo que devolvió mediante el asiento {0}.").format(
            get_link_to_form("Journal Entry", journal_entry.name)
        ),
    )
    return journal_entry.name


def close_refund_receipts(company: str, execute: int | bool = False) -> list[dict]:
    r"""Cierra los recibos de los reembolsos que se enlazaron antes de que esto existiera.

    Los enlaces hechos hasta el 16-sep-2026 --los once clientes de la primera corrida-- dejaron
    el recibo del reembolso mostrando todo su monto como no asignado, que es lo que
    administración lee como saldo a favor. El enlace contable está bien; lo que falta es que el
    documento lo diga. De acá en adelante lo hace :func:`_link_refund` sola.

    Sin ``execute`` solo informa. Se corre a mano::

        bench --site <sitio> execute l10n_ve.overrides.advance_refund_audit.close_refund_receipts \
            --kwargs "{'company': 'Galanet Solution C.A.', 'execute': 1}"
    """
    pending: list[dict] = frappe.db.sql(
        """SELECT pe.name AS receipt, pe.party, ROUND(pe.paid_amount, 2) AS paid,
            ROUND(pe.unallocated_amount, 2) AS unallocated,
            jea.parent AS journal_entry, ROUND(jea.credit, 2) AS linked
        FROM `tabPayment Entry` pe
        JOIN `tabJournal Entry Account` jea
            ON jea.reference_type = 'Payment Entry' AND jea.reference_name = pe.name
        JOIN `tabJournal Entry` je ON je.name = jea.parent AND je.docstatus = 1
        WHERE pe.docstatus = 1 AND pe.payment_type = 'Pay' AND pe.party_type = 'Customer'
            AND pe.company = %s AND ROUND(pe.unallocated_amount, 2) > 0
        ORDER BY pe.posting_date""",
        company,
        as_dict=True,
    )
    if not cint(execute):
        return pending

    for row in pending:
        _close_refund_receipt(
            {"doctype": "Payment Entry", "name": row["receipt"]},
            row["journal_entry"],
            flt(row["linked"], 2),
        )
    frappe.db.commit()
    return pending


def _close_refund_receipt(refund: dict, journal_entry: str, amount: float) -> None:
    """Deja el recibo del reembolso diciendo a qué se aplicó.

    Un recibo de salida sin referencias muestra todo su monto como «no asignado», y
    administración lo lee como saldo a favor del cliente: es lo que reportó Aurelys el
    16-sep-2026 --«el cliente está saldado pero el recibo sigue saliendo con el monto»--
    después de corregir a ZAPATERIA GASOLINA EXTRA, y con razón. La plata ya estaba aplicada,
    pero el recibo no se enteraba: ERPNext solo recalcula esos campos cuando el documento se
    guarda, y un documento emitido no se vuelve a guardar.

    Por eso se escriben a mano la fila de referencia y los totales del documento. No se toca ni
    el libro mayor ni el libro de pagos, que es donde vive la verdad contable y donde ya estaba
    todo cuadrado; esto es lo que se ve en pantalla.

    Los reembolsos asentados como asiento de diario no pasan por acá: no tienen dónde mostrar
    un monto sin asignar.
    """
    if refund["doctype"] != "Payment Entry":
        return

    if frappe.db.exists(
        "Payment Entry Reference",
        {"parent": refund["name"], "reference_name": journal_entry},
    ):
        return

    receipt = frappe.db.get_value(
        "Payment Entry",
        refund["name"],
        [
            "unallocated_amount",
            "total_allocated_amount",
            "base_total_allocated_amount",
            "target_exchange_rate",
        ],
        as_dict=True,
    )
    allocated: float = min(flt(receipt.unallocated_amount, 2), flt(amount, 2))
    if allocated <= 0:
        return

    rate: float = flt(receipt.target_exchange_rate) or 1.0
    row = frappe.new_doc("Payment Entry Reference")
    row.update(
        {
            "parent": refund["name"],
            "parenttype": "Payment Entry",
            "parentfield": "references",
            "idx": frappe.db.count(
                "Payment Entry Reference", {"parent": refund["name"]}
            )
            + 1,
            "docstatus": 1,
            "reference_doctype": "Journal Entry",
            "reference_name": journal_entry,
            "total_amount": allocated,
            "outstanding_amount": 0,
            "allocated_amount": allocated,
            "exchange_rate": rate,
        }
    )
    row.db_insert()
    frappe.db.set_value(
        "Payment Entry",
        refund["name"],
        {
            "total_allocated_amount": flt(receipt.total_allocated_amount) + allocated,
            "base_total_allocated_amount": flt(receipt.base_total_allocated_amount)
            + allocated * rate,
            "unallocated_amount": flt(receipt.unallocated_amount, 2) - allocated,
        },
        update_modified=False,
    )


def _je_dimensions(journal_entry) -> dict:
    """Sucursal y centro de costo de la línea del cliente en el asiento del reembolso."""
    for row in journal_entry.accounts:
        if row.party and flt(row.debit):
            dimensions: dict = {}
            if row.cost_center:
                dimensions["cost_center"] = row.cost_center
            if row.get("branch"):
                dimensions["branch"] = row.branch
            return dimensions
    return {}


def _reconcile(
    company: str,
    party: str,
    advance_account: str,
    invoice: str,
    payment: str | None,
    expected: float,
    cap: bool = False,
) -> None:
    """Aplica el anticipo del cliente a ese documento con la Conciliación de Pagos de ERPNext.

    Se le pasan solo las partidas que corresponden -- el documento destino y, cuando se indica,
    un cobro concreto -- para que no se lleve por delante otra factura del mismo cliente. Con
    `cap`, recorta lo que se va a aplicar hasta `expected`, que es como vuelve el sobrante a su
    factura; sin él, exige que la conciliación aplique exactamente eso.
    """
    receivable: str = get_party_account("Customer", party, company)
    reconciliation = frappe.new_doc("Payment Reconciliation")
    reconciliation.update(
        {
            "company": company,
            "party_type": "Customer",
            "party": party,
            "receivable_payable_account": receivable,
            "default_advance_account": advance_account,
            "invoice_name": invoice,
            "invoice_limit": 10,
            "payment_limit": 1000,
        }
    )
    if payment:
        reconciliation.payment_name = payment
    reconciliation.get_unreconciled_entries()

    target = next(
        (r for r in reconciliation.invoices if r.invoice_number == invoice), None
    )
    payments: list = [
        p
        for p in reconciliation.payments
        if p.reference_type == "Payment Entry"
        and (not payment or p.reference_name == payment)
    ]
    payments.sort(key=lambda p: (p.posting_date, p.reference_name))
    if not target or not payments:
        frappe.throw(
            _(
                "La Conciliación de Pagos no ofrece con qué cruzar {0}. No se registró nada."
            ).format(invoice)
        )

    reconciliation.allocate_entries(
        frappe._dict(
            invoices=[target.as_dict()], payments=[p.as_dict() for p in payments]
        )
    )
    if cap:
        _cap_allocation(reconciliation, flt(expected, 2))

    allocated: float = flt(
        sum(flt(row.allocated_amount) for row in reconciliation.allocation), 2
    )
    if allocated != flt(expected, 2):
        frappe.throw(
            _(
                "Se iban a aplicar {0} contra {1} y correspondían {2}. No se registró nada."
            ).format(_money(allocated, company), invoice, _money(expected, company))
        )

    muted = frappe.flags.mute_messages
    frappe.flags.mute_messages = True
    try:
        reconciliation.reconcile()
    finally:
        frappe.flags.mute_messages = muted


def _cap_allocation(reconciliation, limit: float) -> None:
    """Recorta las asignaciones para que sumen exactamente `limit`."""
    remaining: float = flt(limit, 2)
    kept: list = []
    for row in reconciliation.allocation:
        if remaining <= 0:
            break
        row.allocated_amount = min(flt(row.allocated_amount, 2), remaining)
        remaining = flt(remaining - row.allocated_amount, 2)
        kept.append(row)
    reconciliation.allocation = kept
    for index, row in enumerate(reconciliation.allocation, start=1):
        row.idx = index


def _verify(company: str, party: str, advance_account: str) -> None:
    """Después de corregir, los documentos tienen que decir lo mismo que el mayor."""
    offered = _offered_by_party([advance_account], company, party).get(
        (company, party, advance_account), 0.0
    )
    balance = _ledger_by_party([advance_account], company, party).get(
        (company, party, advance_account), 0.0
    )
    if flt(offered, 2) != flt(balance, 2):
        frappe.throw(
            _(
                "Después de corregir, los cobros de {0} ofrecen {1} y el mayor dice {2}. No se "
                "registró nada."
            ).format(party, _money(offered, company), _money(balance, company))
        )
