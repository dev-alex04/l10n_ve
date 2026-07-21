import frappe
from frappe import _, scrub
from frappe.utils import flt, getdate
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport


erpnext_get_columns = ReceivablePayableReport.get_columns
erpnext_get_ple_entries = ReceivablePayableReport.get_ple_entries
erpnext_get_return_entries = ReceivablePayableReport.get_return_entries


def _resolve_date_range(self):
    """Resuelve el rango (from_date, to_date) y sincroniza report_date con to_date.

    El reporte estandar usa ``report_date`` como limite superior. Si el usuario
    define ``to_date`` lo usamos como limite superior y pisamos ``report_date``
    para que el resto del reporte (ageing, future payments, etc.) sea consistente.
    """
    from_date = self.filters.get("from_date")
    to_date = self.filters.get("to_date") or self.filters.report_date
    if from_date:
        from_date = getdate(from_date)
    if to_date:
        to_date = getdate(to_date)
        self.filters.report_date = to_date
    return from_date, to_date


def get_columns(self) -> None:
    erpnext_get_columns(self)

    for i, column in enumerate(self.columns):

        if column['fieldname'] == 'voucher_no':
            column['hidden'] = True

        if column['fieldname'] != 'voucher_type':
            continue

        column['hidden'] = True

        self.columns.insert(i + 1,
            {
                "label": _("Voucher Type"),
                "fieldname": "ve_voucher_type",
                "fieldtype": "Data",
            })

        self.columns.insert(i + 1,
            {
                "label": _("Voucher No."),
                "fieldname": "ve_voucher_no",
                "fieldtype": "HTML",
            })


def build_data(self) -> None:
    # set outstanding for all the accumulated balances
    # as we can use this to filter out invoices without outstanding
    for _key, row in self.voucher_balance.items():
        row.outstanding = flt(row.invoiced - row.paid - row.credit_note, self.currency_precision)
        row.outstanding_in_account_currency = flt(
            row.invoiced_in_account_currency
            - row.paid_in_account_currency
            - row.credit_note_in_account_currency,
            self.currency_precision,
        )

        row.invoice_grand_total = row.invoiced

        must_consider = False
        if self.filters.get("for_revaluation_journals"):
            if (abs(row.outstanding) >= 1.0 / 10**self.currency_precision) or (
                abs(row.outstanding_in_account_currency) >= 1.0 / 10**self.currency_precision
            ):
                must_consider = True
        else:
            if (abs(row.outstanding) >= 1.0 / 10**self.currency_precision) and (
                (abs(row.outstanding_in_account_currency) >= 1.0 / 10**self.currency_precision)
                or (row.voucher_no in self.err_journals)
            ):
                must_consider = True

        if must_consider:
            # non-zero oustanding, we must consider this row

            if self.is_invoice(row) and self.filters.based_on_payment_terms:
                # is an invoice, allocate based on fifo
                # adds a list `payment_terms` which contains new rows for each term
                self.allocate_outstanding_based_on_payment_terms(row)

                if row.payment_terms:
                    # make separate rows for each payment term
                    for d in row.payment_terms:
                        if d.outstanding > 0:
                            self.append_row(d)

                    # if there is overpayment, add another row
                    self.allocate_extra_payments_or_credits(row)
                else:
                    self.append_row(row)
            else:
                self.append_row(row)

        if row.get('voucher_type'):
            row.ve_voucher_type = _(row.voucher_type)

            doctype = row.voucher_type.lower().replace(' ', '-')

            if row.get('bill_no'):
                row.ve_voucher_no = f'<a href="/app/{doctype}/{row.voucher_no}">{row.bill_no}</a>'
            else:
                row.ve_voucher_no = f'<a href="/app/{doctype}/{row.voucher_no}">{row.voucher_no}</a>'

    if self.filters.get("group_by_party"):
        self.append_subtotal_row(self.previous_party)
        if self.data:
            self.data.append(self.total_row_map.get("Total", {}))


def get_ple_entries(self):
    """Wrapper sobre ``get_ple_entries`` estandar que anade ``posting_date >= from_date``."""
    from_date, _to_date = _resolve_date_range(self)
    if not from_date:
        return erpnext_get_ple_entries(self)

    # El estandar reconstruye qb_selection_filter dentro de prepare_conditions.
    # Parcheamos temporalmente ese metodo para inyectar la condicion extra sin
    # duplicar la logica original.
    ple = self.ple
    original_prepare_conditions = self.prepare_conditions

    def patched_prepare_conditions():
        original_prepare_conditions()
        self.qb_selection_filter.append(ple.posting_date.gte(from_date))

    self.prepare_conditions = patched_prepare_conditions
    try:
        return erpnext_get_ple_entries(self)
    finally:
        self.prepare_conditions = original_prepare_conditions


def get_return_entries(self):
    """Wrapper sobre ``get_return_entries`` estandar que filtra por rango."""
    from_date, _to_date = _resolve_date_range(self)
    if not from_date:
        return erpnext_get_return_entries(self)

    doctype = "Sales Invoice" if self.account_type == "Receivable" else "Purchase Invoice"
    filters = [
        ["posting_date", "<=", self.filters.report_date],
        ["posting_date", ">=", from_date],
        ["is_return", "=", 1],
        ["docstatus", "=", 1],
        ["company", "=", self.filters.company],
        ["update_outstanding_for_self", "=", 0],
    ]

    or_filters = {}
    if party_type := self.filters.party_type:
        party_field = scrub(party_type)
        if parties := self.filters.get("party"):
            or_filters.update({party_field: ["in", parties]})

    self.return_entries = frappe._dict(
        frappe.get_all(
            doctype, filters=filters, or_filters=or_filters, fields=["name", "return_against"], as_list=1
        )
    )


def get_invoice_details(self):
    from_date, _to_date = _resolve_date_range(self)
    self.invoice_details = frappe._dict()

    def _block(fields_to_select, table):
        """Construye un bloque SQL `select ... from <table> where ...` con su
        tupla de parametros asociada, ya con from_date embebido si aplica."""
        select_cols = ", ".join(fields_to_select)
        params = [self.filters.report_date, self.filters.company]
        from_clause = ""
        if from_date:
            from_clause = "and posting_date >= %s"
            # el from_date se inserta DESPUES del primer %s (report_date)
            params = [self.filters.report_date, from_date, self.filters.company]
        sql = f"""
            select {select_cols}
            from `{table}`
            where posting_date <= %s
                {from_clause}
                and company = %s
                and docstatus = 1
        """
        return sql, tuple(params)

    def _union(blocks):
        """Encadena bloques con UNION ALL y returns (sql, params)."""
        sql_parts = []
        all_params = ()
        for sql, params in blocks:
            sql_parts.append(sql)
            all_params += params
        return "\n            union all\n".join(sql_parts), all_params

    if self.account_type == "Receivable":
        # nosemgrep
        sql, params = _block(["name", "due_date", "po_no", "bill_no"], "tabSales Invoice")
        si_list = frappe.db.sql(sql, params, as_dict=1)
        for d in si_list:
            self.invoice_details.setdefault(d.name, d)

        # Get Custom VE Sales Debit/Credit Notes
        sql, params = _union([
            _block(["name", "due_date", "po_no", "bill_no"], "tabVE Sales Debit Note"),
            _block(["name", "due_date", "po_no", "bill_no"], "tabVE Sales Credit Note"),
        ])
        custom_si = frappe.db.sql(sql, params, as_dict=1)
        for d in custom_si:
            self.invoice_details.setdefault(d.name, d)

        # Get Sales Team
        if self.filters.show_sales_person:
            # nosemgrep
            sales_team = frappe.db.sql(
                """
                select parent, sales_person
                from `tabSales Team`
                where parenttype = 'Sales Invoice'
            """,
                as_dict=1,
            )
            for d in sales_team:
                self.invoice_details.setdefault(d.parent, {}).setdefault("sales_team", []).append(
                    d.sales_person
                )

    if self.account_type == "Payable":
        # nosemgrep
        sql, params = _block(["name", "due_date", "bill_no", "bill_date"], "tabPurchase Invoice")
        for pi in frappe.db.sql(sql, params, as_dict=1):
            self.invoice_details.setdefault(pi.name, pi)

        # Get Custom VE Purchase Debit/Credit Notes
        sql, params = _union([
            _block(["name", "posting_date as due_date", "bill_no", "bill_date"], "tabVE Purchase Debit Note"),
            _block(["name", "posting_date as due_date", "bill_no", "bill_date"], "tabVE Purchase Credit Note"),
        ])
        custom_pi = frappe.db.sql(sql, params, as_dict=1)
        for d in custom_pi:
            self.invoice_details.setdefault(d.name, d)

    # Invoices booked via Journal Entries
    # nosemgrep
    je_sql, je_params = _block(["name", "due_date", "bill_no", "bill_date"], "tabJournal Entry")
    journal_entries = frappe.db.sql(je_sql, je_params, as_dict=1)

    for je in journal_entries:
        if je.bill_no:
            self.invoice_details.setdefault(je.name, je)


def custom_is_invoice(self, ple):
    custom_doctypes = ["VE Sales Debit Note", "VE Sales Credit Note", "VE Purchase Debit Note", "VE Purchase Credit Note"]
    if ple.voucher_type in ("Sales Invoice", "Purchase Invoice") or ple.voucher_type in custom_doctypes:
        return True
    return False


ReceivablePayableReport.build_data = build_data
ReceivablePayableReport.get_columns = get_columns
ReceivablePayableReport.get_invoice_details = get_invoice_details
ReceivablePayableReport.get_ple_entries = get_ple_entries
ReceivablePayableReport.get_return_entries = get_return_entries
ReceivablePayableReport.is_invoice = custom_is_invoice
