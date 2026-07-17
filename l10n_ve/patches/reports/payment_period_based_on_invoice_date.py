import frappe
from frappe import _
import erpnext.accounts.report.payment_period_based_on_invoice_date.payment_period_based_on_invoice_date as pp

original_execute = pp.execute

def get_row_exchange_rate(entry: list, invoice_col_idx: int, invoice_data: dict[str, dict], posting_date_col_idx: int) -> float:
    from l10n_ve.utils.utils import get_exchange_rate
    from frappe.utils import flt

    inv_id: str | None = entry[invoice_col_idx] if len(entry) > invoice_col_idx else None
    inv_doc: dict | None = invoice_data.get(inv_id) if inv_id else None

    rate: float = 1.0
    if inv_doc:
        # Caso 1: Si la lista de precios es en USD, la tasa real de la transacción está en plc_conversion_rate
        if inv_doc.get("price_list_currency") == "USD" and flt(inv_doc.get("plc_conversion_rate")) > 0:
            rate = flt(inv_doc.get("plc_conversion_rate"))
        # Caso 2: Factura emitida directamente en USD, usamos su conversion_rate del sistema
        elif inv_doc.get("currency") == "USD" and flt(inv_doc.get("conversion_rate")) > 1:
            rate = flt(inv_doc.get("conversion_rate"))
        else:
            # Caso 3: Factura en VES sin tasa en el documento, buscamos la tasa histórica BCV de la fecha de factura
            inv_date: str | None = inv_doc.get("posting_date")
            try:
                rate = flt(get_exchange_rate(inv_date, "USD") or 1.0)
            except Exception:
                rate = 1.0
    else:
        # Caso 4: Sin factura asociada (ej. anticipo o Journal Entry), usamos la tasa de la fecha del pago
        pay_date: str | None = None
        if posting_date_col_idx != -1 and len(entry) > posting_date_col_idx:
            pay_date = entry[posting_date_col_idx]
            
        if pay_date:
            try:
                rate = flt(get_exchange_rate(pay_date, "USD") or 1.0)
            except Exception:
                rate = 1.0

    return rate if rate > 0 else 1.0


def custom_execute(filters: dict | None = None) -> tuple[list[dict], list[list]]:
    if not filters:
        filters = {}

    columns, data = original_execute(filters)

    # Corrección: el reporte core de ERPNext agrega 'delay_in_payment' solo si
    # invoice.due_date existe, causando filas con menos elementos que columnas.
    # Esto provoca IndexError en normalize_result. Normalizamos las filas aquí.
    expected_length: int = len(columns)
    for row in data:
        if isinstance(row, list) and len(row) < expected_length:
            row.extend([None] * (expected_length - len(row)))

    party_col_idx: int = -1
    party_type_col_idx: int = -1
    doc_type_col_idx: int = -1
    invoice_col_idx: int = -1

    for i, col in enumerate(columns):
        col_fieldname: str = col.get("fieldname") or ""
        if col_fieldname == "party":
            party_col_idx = i
        elif col_fieldname == "party_type":
            party_type_col_idx = i
        elif col_fieldname == "payment_document":
            doc_type_col_idx = i
        elif col_fieldname == "invoice":
            invoice_col_idx = i

    # Obtener información de las facturas (Sucursal, Nro. Factura, Nro. Control, Divisa, Tasa de Cambio)
    invoice_data: dict[str, dict] = {}
    if invoice_col_idx != -1:
        payment_type: str = filters.get("payment_type") or ""
        is_outgoing: bool = payment_type in ("Outgoing", "Saliente", _("Outgoing"))
        invoice_doctype: str = "Purchase Invoice" if is_outgoing else "Sales Invoice"

        # Extraer IDs de facturas únicos de los datos del reporte
        invoice_ids: list[str] = [
            row[invoice_col_idx]
            for row in data
            if len(row) > invoice_col_idx and row[invoice_col_idx]
        ]

        if invoice_ids:
            fields_to_get: list[str] = [
                "name", "branch", "bill_control", "bill_no", "currency", 
                "conversion_rate", "posting_date", "price_list_currency", "plc_conversion_rate"
            ]
            invoices_list: list[dict] = frappe.get_all(
                invoice_doctype,
                filters={"name": ["in", invoice_ids]},
                fields=fields_to_get
            )
            for inv in invoices_list:
                invoice_data[inv["name"]] = inv

    # Filtrar por sucursal (ve_branch) si el filtro está presente
    selected_branch: str | None = filters.get("ve_branch")
    if selected_branch and invoice_col_idx != -1:
        filtered_rows: list[list] = []
        for row in data:
            inv_id: str | None = row[invoice_col_idx] if len(row) > invoice_col_idx else None
            # Excluimos pagos que no corresponden a la sucursal seleccionada
            if inv_id and inv_id in invoice_data:
                if invoice_data[inv_id].get("branch") == selected_branch:
                    filtered_rows.append(row)
        data = filtered_rows

    # Conversión de montos a USD si se seleccionó en el filtro
    if filters.get("presentation_currency") == "USD" and invoice_col_idx != -1:
        from frappe.utils import flt

        amount_col_idx: int = -1
        range1_col_idx: int = -1
        range2_col_idx: int = -1
        range3_col_idx: int = -1
        range4_col_idx: int = -1

        for i, col in enumerate(columns):
            col_fieldname: str = col.get("fieldname") or ""
            if col_fieldname == "amount":
                amount_col_idx = i
            elif col_fieldname == "range1":
                range1_col_idx = i
            elif col_fieldname == "range2":
                range2_col_idx = i
            elif col_fieldname == "range3":
                range3_col_idx = i
            elif col_fieldname == "range4":
                range4_col_idx = i

        posting_date_col_idx: int = -1
        for i, col in enumerate(columns):
            if col.get("fieldname") == "posting_date":
                posting_date_col_idx = i
                break

        for row in data:
            if isinstance(row, list):
                rate: float = get_row_exchange_rate(row, invoice_col_idx, invoice_data, posting_date_col_idx)
                
                # Convertir montos dividiendo por la tasa
                if amount_col_idx != -1 and len(row) > amount_col_idx and row[amount_col_idx] is not None:
                    row[amount_col_idx] = flt(row[amount_col_idx]) / rate
                if range1_col_idx != -1 and len(row) > range1_col_idx and row[range1_col_idx] is not None:
                    row[range1_col_idx] = flt(row[range1_col_idx]) / rate
                if range2_col_idx != -1 and len(row) > range2_col_idx and row[range2_col_idx] is not None:
                    row[range2_col_idx] = flt(row[range2_col_idx]) / rate
                if range3_col_idx != -1 and len(row) > range3_col_idx and row[range3_col_idx] is not None:
                    row[range3_col_idx] = flt(row[range3_col_idx]) / rate
                if range4_col_idx != -1 and len(row) > range4_col_idx and row[range4_col_idx] is not None:
                    row[range4_col_idx] = flt(row[range4_col_idx]) / rate

        # Ajustar el formateo de las columnas a USD
        for col in columns:
            if col.get("fieldtype") == "Currency":
                col["options"] = "USD"

    # Filtrar por rango de antigüedad si el filtro está activo
    selected_range = filters.get("aging_range")
    if selected_range:
        range_field_map = {
            "0-30": "range1",
            "30-60": "range2",
            "60-90": "range3",
            "Superior a 90": "range4"
        }
        target_field = range_field_map.get(selected_range)
        if target_field:
            target_col_idx = -1
            for i, col in enumerate(columns):
                if col.get("fieldname") == target_field:
                    target_col_idx = i
                    break
            
            if target_col_idx != -1:
                from frappe.utils import flt
                data = [
                    row for row in data
                    if len(row) > target_col_idx and flt(row[target_col_idx]) != 0
                ]

    rif_inserted: bool = False
    if party_col_idx != -1:
        rif_col: dict = {
            "fieldname": "tax_id",
            "label": _("RIF"),
            "fieldtype": "Data",
            "width": 120,
        }
        columns.insert(party_col_idx + 1, rif_col)
        rif_inserted = True

        party_map: dict[str, set[str]] = {}
        for row in data:
            if len(row) > party_type_col_idx and len(row) > party_col_idx:
                ptype: str = row[party_type_col_idx]
                party: str = row[party_col_idx]
                if ptype and party:
                    party_map.setdefault(ptype, set()).add(party)

        tax_ids: dict[tuple[str, str], str] = {}
        for ptype, parties in party_map.items():
            if frappe.db.has_column(ptype, "tax_id"):
                docs: list[dict] = frappe.get_all(
                    ptype,
                    filters={"name": ["in", list(parties)]},
                    fields=["name", "tax_id"]
                )
                for doc in docs:
                    tax_ids[(ptype, doc["name"])] = doc.get("tax_id") or ""

        for row in data:
            if isinstance(row, list):
                ptype: str | None = row[party_type_col_idx] if len(row) > party_type_col_idx else None
                party: str | None = row[party_col_idx] if len(row) > party_col_idx else None
                
                tax_id_val: str = tax_ids.get((ptype, party), "")
                row.insert(party_col_idx + 1, tax_id_val)
                
                if ptype:
                    row[party_type_col_idx] = _(ptype)
                
                if len(row) > doc_type_col_idx and row[doc_type_col_idx]:
                    row[doc_type_col_idx] = _(row[doc_type_col_idx])

    # Insertar Sucursal, Nro. Factura y Nro. Control
    if invoice_col_idx != -1:
        actual_invoice_col_idx: int = invoice_col_idx + 1 if (rif_inserted and party_col_idx < invoice_col_idx) else invoice_col_idx

        branch_col: dict = {
            "fieldname": "branch",
            "label": _("Sucursal"),
            "fieldtype": "Link",
            "options": "VE Branch",
            "width": 120
        }
        bill_no_col: dict = {
            "fieldname": "bill_no",
            "label": _("Nro. Factura"),
            "fieldtype": "Data",
            "width": 120
        }
        bill_control_col: dict = {
            "fieldname": "bill_control",
            "label": _("Nro. Control"),
            "fieldtype": "Data",
            "width": 120
        }

        columns.insert(actual_invoice_col_idx + 1, branch_col)
        columns.insert(actual_invoice_col_idx + 2, bill_no_col)
        columns.insert(actual_invoice_col_idx + 3, bill_control_col)

        for row in data:
            if isinstance(row, list):
                inv_id: str | None = row[actual_invoice_col_idx] if len(row) > actual_invoice_col_idx else None
                inv_doc: dict | None = invoice_data.get(inv_id) if inv_id else None

                branch_val: str = inv_doc.get("branch") or "" if inv_doc else ""
                bill_no_val: str = inv_doc.get("bill_no") or "" if inv_doc else ""
                bill_control_val: str = inv_doc.get("bill_control") or "" if inv_doc else ""

                row.insert(actual_invoice_col_idx + 1, branch_val)
                row.insert(actual_invoice_col_idx + 2, bill_no_val)
                row.insert(actual_invoice_col_idx + 3, bill_control_val)

    return columns, data

pp.execute = custom_execute
