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

1. Deshace la aplicación del cobro devuelto a la factura que pagó con esa plata.
2. Le aplica a esa factura el pago real del cliente, si tiene uno sin aplicar que la cubra.
3. Crea el asiento que enlaza el reembolso con el cobro, y le aplica el anticipo.

Al terminar comprueba que los documentos digan lo mismo que el mayor. Si no, no deja nada.
"""

import frappe
from erpnext.accounts.party import get_party_account
from frappe import _
from frappe.utils import flt, fmt_money, get_link_to_form, getdate, nowdate
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
    ]
    values: list = []
    conditions.append("pe.paid_from IN %s")
    values.append(tuple(accounts))
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
        advance_account=account,
        offered=available,
        ledger=balance,
        difference=flt(available - balance, 2),
        refunds=[],
        undo=None,
        payment_for_invoice=None,
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
        if not case.undo:
            case.problem = _(
                "Ninguna aplicación de un cobro a una factura suma exactamente lo que falta: el saldo "
                "devuelto se repartió entre varias facturas y hay que decidir de cuál se saca."
            )
            return case
        case.payment_for_invoice = _payment_for_invoice(case)
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
            "{0} está conciliado con un DEPÓSITO del banco ({1}): parece un cobro registrado como pago, "
            "y hay que anularlo y registrarlo como cobro."
        ).format(name, ", ".join(m.name for m in movements))
    return None


def _allocation_to_undo(case: dict) -> dict | None:
    """La aplicación de un cobro a una factura que usó el saldo ya devuelto.

    «Desconciliar pago» deshace la aplicación entera de ese cobro a esa factura, así que sirve
    solo si ese total es exactamente lo que falta. Se mira primero el cobro que tiene el mismo
    monto que un reembolso y después las aplicaciones más recientes.
    """
    missing: float = flt(case.difference - case.offered, 2)
    amounts: tuple = tuple({flt(r.amount, 2) for r in case.refunds})
    twins: list[str] = frappe.db.sql(
        """SELECT name FROM `tabPayment Entry`
        WHERE docstatus = 1 AND payment_type = 'Receive' AND party_type = 'Customer' AND party = %s
          AND company = %s AND paid_from = %s AND ROUND(paid_amount, 2) IN %s""",
        (case.party, case.company, case.advance_account, amounts),
        pluck=True,
    )

    candidates: list[dict] = []
    if twins:
        candidates += frappe.db.sql(
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
    candidates += frappe.db.sql(
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
    for row in candidates:
        key = (row.payment_entry, row.sales_invoice)
        if key in seen:
            continue
        seen.add(key)
        if flt(row.amount, 2) == missing:
            return row
    return None


def _payment_for_invoice(case: dict) -> dict | None:
    """Un cobro real del cliente, sin aplicar, que pueda pagar la factura que queda libre.

    Es el paso que salva al cliente que ya volvió a pagar: sin él, su pago queda flotando como
    anticipo y la factura, pendiente. Solo se propone cuando hay un único candidato que la cubre.
    """
    if not case.undo:
        return None
    candidates: list[dict] = frappe.db.sql(
        """SELECT name, posting_date, ROUND(unallocated_amount, 2) AS amount
        FROM `tabPayment Entry`
        WHERE docstatus = 1 AND payment_type = 'Receive' AND party_type = 'Customer' AND party = %s
          AND company = %s AND paid_from = %s AND unallocated_amount > 0
          AND name <> %s AND ROUND(unallocated_amount, 2) >= %s
        ORDER BY posting_date, creation""",
        (
            case.party,
            case.company,
            case.advance_account,
            case.undo.payment_entry,
            flt(case.undo.amount, 2),
        ),
        as_dict=True,
    )
    return candidates[0] if len(candidates) == 1 else None


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
    lines: list[str] = []
    if case.get("problem"):
        return {"can_fix": False, "problem": case["problem"], "lines": []}

    if case["undo"]:
        lines.append(
            _(
                "Se le quita a la factura {0} los {1} que pagó con dinero devuelto."
            ).format(
                case["undo"]["sales_invoice"], _money(case["undo"]["amount"], company)
            )
        )
    if case["payment_for_invoice"]:
        lines.append(
            _("Se le aplica a esa factura el cobro {0} del {1}, por {2}.").format(
                case["payment_for_invoice"]["name"],
                frappe.format(
                    case["payment_for_invoice"]["posting_date"], {"fieldtype": "Date"}
                ),
                _money(case["payment_for_invoice"]["amount"], company),
            )
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
    lines.append(
        _(
            "Al terminar, lo que los cobros ofrecen tiene que ser {0}, igual que el mayor."
        ).format(_money(case["ledger"], company))
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
            created.append(_unreconcile(case))
            if case["payment_for_invoice"]:
                _apply_payment_to_invoice(case)
        for refund in case["refunds"]:
            created.append(_link_refund(case, refund, posting))
        _verify(company, party, advance_account)
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
    return {"customer": party, "documents": created}


def _single_case(company: str, party: str, advance_account: str) -> dict:
    casos = [
        c
        for c in scan(company=company, party=party)
        if c["advance_account"] == advance_account
    ]
    if not casos:
        frappe.throw(
            _("{0} ya no tiene reembolsos sin enlazar en {1}.").format(
                party, advance_account
            )
        )
    return casos[0]


def _unreconcile(case: dict) -> str:
    """Deshace la aplicación del cobro devuelto a la factura, con «Desconciliar pago»."""
    undo = case["undo"]
    account: str = frappe.db.get_value(
        "Payment Entry Reference",
        {
            "parent": undo["payment_entry"],
            "reference_doctype": "Sales Invoice",
            "reference_name": undo["sales_invoice"],
        },
        "account",
    ) or get_party_account("Customer", case["party"], case["company"])

    doc = frappe.new_doc("Unreconcile Payment")
    doc.company = case["company"]
    doc.voucher_type = "Payment Entry"
    doc.voucher_no = undo["payment_entry"]
    doc.append(
        "allocations",
        {
            "reference_doctype": "Sales Invoice",
            "reference_name": undo["sales_invoice"],
            "allocated_amount": undo["amount"],
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


def _apply_payment_to_invoice(case: dict) -> None:
    """Le aplica a la factura liberada el cobro real del cliente que estaba sin aplicar."""
    payment = case["payment_for_invoice"]
    _reconcile(
        case["company"],
        case["party"],
        case["advance_account"],
        invoice=case["undo"]["sales_invoice"],
        payment=payment["name"],
        expected=flt(case["undo"]["amount"], 2),
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
    origin.add_comment(
        "Comment",
        text=_("Enlazado con el anticipo que devolvió mediante el asiento {0}.").format(
            get_link_to_form("Journal Entry", journal_entry.name)
        ),
    )
    return journal_entry.name


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
) -> None:
    """Aplica el anticipo del cliente a ese documento con la Conciliación de Pagos de ERPNext.

    Se le pasan solo las partidas que corresponden -- el documento destino y, cuando se indica,
    un cobro concreto -- para que no se lleve por delante otra factura del mismo cliente. Antes
    de conciliar se comprueba que vaya a aplicar exactamente lo esperado.
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
                "Después de corregir, los cobros de {0} ofrecen {1} y el mayor dice {2}. No se registró nada."
            ).format(party, _money(offered, company), _money(balance, company))
        )
