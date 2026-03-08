import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport


erpnext_get_columns = ReceivablePayableReport.get_columns

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


def get_invoice_details(self):
    self.invoice_details = frappe._dict()
    if self.account_type == "Receivable":
        # nosemgrep
        si_list = frappe.db.sql(
            """
            select name, due_date, po_no, bill_no
            from `tabSales Invoice`
            where posting_date <= %s
                and company = %s
                and docstatus = 1
        """,
            (self.filters.report_date, self.filters.company),
            as_dict=1,
        )
        for d in si_list:
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
        for pi in frappe.db.sql(
            """
            select name, due_date, bill_no, bill_date
            from `tabPurchase Invoice`
            where
                posting_date <= %s
                and company = %s
                and docstatus = 1
        """,
            (self.filters.report_date, self.filters.company),
            as_dict=1,
        ):
            self.invoice_details.setdefault(pi.name, pi)

    # Invoices booked via Journal Entries
    # nosemgrep
    journal_entries = frappe.db.sql(
        """
        select name, due_date, bill_no, bill_date
        from `tabJournal Entry`
        where
            posting_date <= %s
            and company = %s
            and docstatus = 1
    """,
        (self.filters.report_date, self.filters.company),
        as_dict=1,
    )

    for je in journal_entries:
        if je.bill_no:
            self.invoice_details.setdefault(je.name, je)



ReceivablePayableReport.build_data = build_data
ReceivablePayableReport.get_columns = get_columns
ReceivablePayableReport.get_invoice_details = get_invoice_details
