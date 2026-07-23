import frappe
from frappe import _, scrub
from frappe.utils import flt, getdate
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport


# Capturas "soft": ERPNext >=15.106 refactorizo el reporte AR y reemplazo
# ``get_ple_entries`` por ``prepare_ple_query`` + ``fetch_ple_in_*``. Capturamos
# con getattr para no romper el modulo en versiones anteriores.
erpnext_get_columns = getattr(ReceivablePayableReport, "get_columns", None)
erpnext_get_return_entries = getattr(ReceivablePayableReport, "get_return_entries", None)
erpnext_get_ple_entries = getattr(ReceivablePayableReport, "get_ple_entries", None)
erpnext_prepare_ple_query = getattr(ReceivablePayableReport, "prepare_ple_query", None)


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


def _is_usd_enabled(filters):
    """Interpreta el valor de `show_in_usd` sea Check (0/1/True/False) o
    Select ('Sí'/'No'/'1'/'0'). Devuelve True solo cuando el check/valor
    expresa positivamente USD."""
    val = filters.get("show_in_usd") if hasattr(filters, "get") else None
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip() in ("1", "True", "true", "Sí", "S\u00ed", "yes", "YES")


def get_columns(self) -> None:
    erpnext_get_columns(self)

    show_in_usd = _is_usd_enabled(self.filters)
    try:
        frappe.log_error(title="DEBUG_AR_GETCOLS", message=f"show_in_usd={show_in_usd}")
    except Exception:
        pass

    for i, column in enumerate(self.columns):

        if column['fieldname'] == 'voucher_no':
            column['hidden'] = True

        if column['fieldname'] != 'voucher_type':
            continue

        column['hidden'] = True

        self.columns.insert(i + 1,
            {
                "label": _("Tipo Comprobante"),
                "fieldname": "ve_voucher_type",
                "fieldtype": "Data",
            })

        self.columns.insert(i + 1,
            {
                "label": _("Comprobante"),
                "fieldname": "ve_voucher_no",
                "fieldtype": "HTML",
            })

    # Cuando show_in_usd esta activo, los valores de las columnas de monto
    # existentes se convierten a USD en build_data (dividiendo por la
    # conversion_rate de la propia factura). No se agregan columnas nuevas:
    # reutilizamos Facturado/Pagado/Nota de Credito/Saldo y los rangos de
    # ageing, forzando sus `options` a "USD" para que la UI muestre el
    # simbolo "$" en lugar de "Bs".
    if _is_usd_enabled(self.filters):
        usd_cols = {"invoiced", "paid", "credit_note", "outstanding",
                    "range1", "range2", "range3", "range4", "range5"}
        for column in self.columns:
            if column.get("fieldname") in usd_cols:
                column["options"] = "USD"


def build_data(self) -> None:
    # set outstanding for all the accumulated balances
    # as we can use this to filter out invoices without outstanding
    show_in_usd = _is_usd_enabled(self.filters)
    try:
        frappe.log_error(title="DEBUG_AR_BUILDDATA", message=f"show_in_usd={show_in_usd} | len voucher_balance={len(self.voucher_balance) if hasattr(self,'voucher_balance') else 'N/A'} | has invoice_details={hasattr(self,'invoice_details')}")
    except Exception:
        pass
    # Columnas de monto que convertimos a USD cuando el check esta activo.
    usd_fields = ("invoiced", "paid", "credit_note", "outstanding",
                  "range1", "range2", "range3", "range4", "range5")

    for _key, row in self.voucher_balance.items():
        row.outstanding = flt(row.invoiced - row.paid - row.credit_note, self.currency_precision)
        row.outstanding_in_account_currency = flt(
            row.invoiced_in_account_currency
            - row.paid_in_account_currency
            - row.credit_note_in_account_currency,
            self.currency_precision,
        )

        row.invoice_grand_total = row.invoiced

        # Conversion a USD de la propia factura (sin recalcular por la tasa
        # del dia). Solo las facturas con currency=USD tienen referencia
        # directa en USD; las VEF no aportan USD y se dejan en 0/None segun
        # corresponda para no inventar conversion.
        if show_in_usd:
            det = self.invoice_details.get(row.voucher_no, {}) if hasattr(self, "invoice_details") else {}
            inv_currency = det.get("currency")
            inv_rate = flt(det.get("conversion_rate")) or 0.0
            row._ve_usd_rate = inv_rate if (inv_currency == "USD" and inv_rate) else None
            row._ve_usd_factor = (1.0 / inv_rate) if (inv_currency == "USD" and inv_rate) else None

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
                            _convert_row_to_usd(d, show_in_usd, usd_fields, self.currency_precision)
                            self.append_row(d)

                    # if there is overpayment, add another row
                    self.allocate_extra_payments_or_credits(row)
                else:
                    _convert_row_to_usd(row, show_in_usd, usd_fields, self.currency_precision)
                    self.append_row(row)
            else:
                _convert_row_to_usd(row, show_in_usd, usd_fields, self.currency_precision)
                self.append_row(row)

        if row.get('voucher_type'):
            row.ve_voucher_type = _(row.voucher_type)

            doctype = row.voucher_type.lower().replace(' ', '-')

            if row.get('bill_no'):
                row.ve_voucher_no = f'<a href="/app/{doctype}/{row.voucher_no}">{row.bill_no}</a>'
            else:
                row.ve_voucher_no = f'<a href="/app/{doctype}/{row.voucher_no}">{row.voucher_no}</a>'

    # Conversion post-append_row: aqui convertimos TODOS los campos de monto
    # (invoiced, paid, credit_note, outstanding, range1..range5) a USD usando
    # la conversion_rate de la FACTURA del voucher. Se hace aca, despues de
    # append_row, porque set_ageing puebla range1..range5 y necesita los
    # valores en moneda base para distribuirlos.
    if show_in_usd:
        _converted = 0
        _total = 0
        _samples = []
        for r in self.data:
            if not isinstance(r, dict):
                continue
            _total += 1
            vn = r.get("voucher_no")
            det = self.invoice_details.get(vn, {}) if (vn and hasattr(self, "invoice_details")) else {}
            inv_rate = flt(det.get("conversion_rate")) or 0.0
            if inv_rate:
                _before = r.get("invoiced")
                for f in usd_fields:
                    if f in r and r[f] is not None:
                        r[f] = flt(r[f] / inv_rate, self.currency_precision)
                _converted += 1
                if len(_samples) < 3:
                    _samples.append({"vn": vn, "rate": inv_rate, "before": _before, "after": r.get("invoiced")})
            # Si no hay tasa valida (vouchers sin factura / conversion_rate 0),
            # dejamos la fila en moneda base para no inventar conversion.
        try:
            frappe.log_error(title="DEBUG_AR_CONVERT", message=f"total_rows={_total} converted={_converted} samples={_samples} | keys_invoice_details={list(self.invoice_details.keys())[:5] if hasattr(self,'invoice_details') else 'N/A'}")
        except Exception:
            pass

    if self.filters.get("group_by_party"):
        self.append_subtotal_row(self.previous_party)
        if self.data:
            self.data.append(self.total_row_map.get("Total", {}))


def _convert_row_to_usd(row, show_in_usd, usd_fields, prec=2):
    """No-op. La conversion REAL se hace despues de append_row en build_data
    (ver el bloque post-append_row) porque set_ageing necesita los valores en
    moneda base para repartirlos en `range1`..`range5`. Mantengo la firma para
    no romper las llamadas."""
    return


def _wrap_ple_method(self):
    """Inyecta ``posting_date >= from_date`` (y el filtro ve_branch cuando aplique)
    en la lectura de PLE, cualquiera que sea la API de la version de ERPNext.

    - ERPNext moderno: ``prepare_ple_query`` (arma el query) -> se patchea
      via ``prepare_conditions``.
    - ERPNext clasico: ``get_ple_entries`` (arma el query + ejecuta) -> se
      patchea la condicion en ``qb_selection_filter``.
    """
    from_date, _to_date = _resolve_date_range(self)
    ple = self.ple

    if from_date:
        original_prepare_conditions = self.prepare_conditions

        def patched_prepare_conditions():
            original_prepare_conditions()
            self.qb_selection_filter.append(ple.posting_date.gte(from_date))

        self.prepare_conditions = patched_prepare_conditions
    return from_date


def prepare_ple_query(self):  # noqa: D401 (legacy API name kept for clarity)
    _wrap_ple_method(self)
    if erpnext_prepare_ple_query is None:
        return None
    try:
        return erpnext_prepare_ple_query(self)
    finally:
        pass


def get_ple_entries(self):
    """Wrapper sobre el ``get_ple_entries`` clasico.

    Anade ``posting_date >= from_date`` y, si esta activo ``ve_branch``, filtra
    las PLE por sucursal (leyendo ``branch`` del voucher al que apunta cada PLE).
    """
    from_date, _to_date = _resolve_date_range(self)
    ple = self.ple

    original_prepare_conditions = self.prepare_conditions
    if from_date:
        def patched_prepare_conditions():
            original_prepare_conditions()
            self.qb_selection_filter.append(ple.posting_date.gte(from_date))
        self.prepare_conditions = patched_prepare_conditions

    try:
        erpnext_get_ple_entries(self)
    finally:
        self.prepare_conditions = original_prepare_conditions

    # Filtro por sucursal VE (post-query): en versiones sin fetch_ple_in_*,
    # el filtro por ve_branch se aplica aqui sobre self.ple_entries ya cargado.
    if self.filters.get("ve_branch"):
        from l10n_ve.patches.reports.receivable_payable import filter_ple_by_ve_branch
        self.ple_entries = filter_ple_by_ve_branch(self.ple_entries, self.filters.get("ve_branch"))


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
        # Traemos currency/conversion_rate/grand_total/base_grand_total para
        # poder expresar los montos en USD leyendo directamente de la factura
        # (sin recalcular por la tasa del dia).
        sql, params = _block(
            ["name", "due_date", "po_no", "bill_no",
             "currency", "conversion_rate", "grand_total", "base_grand_total"],
            "tabSales Invoice",
        )
        si_list = frappe.db.sql(sql, params, as_dict=1)
        for d in si_list:
            self.invoice_details.setdefault(d.name, d)

        # Get Custom VE Sales Debit/Credit Notes
        sql, params = _union([
            _block(["name", "due_date", "po_no", "bill_no",
                    "currency", "conversion_rate", "grand_total", "base_grand_total"],
                   "tabVE Sales Debit Note"),
            _block(["name", "due_date", "po_no", "bill_no",
                    "currency", "conversion_rate", "grand_total", "base_grand_total"],
                   "tabVE Sales Credit Note"),
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
if erpnext_get_columns is not None:
    ReceivablePayableReport.get_columns = get_columns
ReceivablePayableReport.get_invoice_details = get_invoice_details
if erpnext_prepare_ple_query is not None:
    ReceivablePayableReport.prepare_ple_query = prepare_ple_query
if erpnext_get_ple_entries is not None:
    ReceivablePayableReport.get_ple_entries = get_ple_entries
if erpnext_get_return_entries is not None:
    ReceivablePayableReport.get_return_entries = get_return_entries
ReceivablePayableReport.is_invoice = custom_is_invoice
