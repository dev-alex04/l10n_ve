import frappe
from frappe import _
from frappe.utils import flt, getdate
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport


erpnext_get_columns = ReceivablePayableReport.get_columns
erpnext_prepare_ple_query = ReceivablePayableReport.prepare_ple_query
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
    from_date, _to_date = _resolve_date_range(self)
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

        # «Desde» filtra DOCUMENTOS por su fecha de contabilización, no pagos: la fila ya
        # trae todo el libro hasta «Hasta» y se descarta solo si el documento es anterior.
        # Vale igual para el anticipo sin aplicar (fila negativa): es un documento más.
        if must_consider and from_date and getdate(row.posting_date) < from_date:
            must_consider = False

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


def prepare_ple_query(self):
    """Wrapper sobre el ``prepare_ple_query`` estándar: el libro de pagos NO se recorta por «Desde».

    Hasta el 9-sep-2026 este wrapper inyectaba ``posting_date >= from_date`` en el libro de
    pagos, así que un cobro anterior a «Desde» no contaba para la factura que saldaba. Bajo
    emitir-al-pagar el cobro es casi siempre anterior a la factura, y el reporte de
    septiembre de 2026 mostraba 615 facturas pagadas (Bs 9,96 M) como impagas y 1.247 con
    pendiente de más (medido en producción el 9-sep-2026). Caso testigo: ACC-SINV-2026-20416,
    del 1-sep, pagada con un anticipo del 21-ago y un asiento cambiario del 1-ago, listada
    con la factura entera pendiente.

    La regla, fijada por Daniel el 9-sep-2026: «Desde» y «Hasta» eligen los DOCUMENTOS que
    originan la cuenta por cobrar por su fecha de contabilización; el pendiente de cada uno
    se calcula con todo lo que lo afecta hasta «Hasta», sea anterior o no a «Desde». El
    recorte por «Desde» vive en ``build_data``, sobre las filas ya calculadas. Aquí solo se
    sincroniza ``report_date`` con «Hasta».
    """
    _resolve_date_range(self)
    return erpnext_prepare_ple_query(self)


def get_return_entries(self):
    """Wrapper sobre ``get_return_entries`` estándar: sin recorte por «Desde».

    Una nota de crédito anterior a «Desde» aplicada a una factura del período tiene que
    clasificarse como nota de crédito y no como pago: misma regla que el libro de pagos.
    """
    _resolve_date_range(self)
    return erpnext_get_return_entries(self)


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
ReceivablePayableReport.prepare_ple_query = prepare_ple_query
ReceivablePayableReport.get_return_entries = get_return_entries
ReceivablePayableReport.is_invoice = custom_is_invoice
