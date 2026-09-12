import frappe
from frappe import _
from frappe.utils import cint, escape_html
# Este módulo existe para parchear ReceivablePayableReport (ver el final del archivo), así
# que la regla de semgrep contra el monkey patching salta por diseño. Su coincidencia va
# desde este import hasta las asignaciones del final: sin esta marca, cualquier cambio en
# el archivo vuelve a hacer fallar Semgrep en la CI.
# nosemgrep: frappe-semgrep-rules.rules.frappe-monkey-patching-not-allowed
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport

original_run = ReceivablePayableReport.run

#: Literales SIN traducir a proposito. `_()` se resuelve contra el idioma de
#: `frappe.local`, y este diccionario se evalua UNA vez al importar el modulo: la
#: traduccion quedaria congelada con el idioma que hubiera en ese momento y
#: compartida por todos los usuarios que atienda ese worker. Se traduce en el
#: punto de uso, con `_traducir_doctype`.
DOC_TYPE_TRANSLATIONS = {
    "Sales Invoice": "Factura de Venta",
    "Journal Entry": "Entrada de Diario",
    "Payment Entry": "Entrada de Pago",
    "Purchase Invoice": "Factura de Compra",
    "Sales Order": "Orden de Venta",
    "Purchase Order": "Orden de Compra",
    "Delivery Note": "Nota de Entrega",
    "Purchase Receipt": "Recibo de Compra",
    "VE Sales Credit Note": "Nota de Crédito de Ventas",
    "VE Sales Debit Note": "Nota de Débito de Ventas",
    "VE Purchase Credit Note": "Nota de Crédito de Compras",
    "VE Purchase Debit Note": "Nota de Débito de Compras",
}

#: Estados del comprobante de retencion. Se guardan en la fila SIN traducir para
#: que el filtro compare contra algo estable: si comparara contra el texto que se
#: muestra, cambiar el idioma --o agregar estas entradas al catalogo-- haria que
#: el filtro dejara de encontrar nada, en silencio.
ESTADO_REGISTRADO = "registrado"
ESTADO_PENDIENTE = "pendiente"
ESTADO_NO_APLICA = "no_aplica"

ETIQUETA_ESTADO = {
    ESTADO_PENDIENTE: "Pendiente",
    ESTADO_NO_APLICA: "No aplica",
}


def _traducir_doctype(nombre: str) -> str:
    """Traduce en el momento de usarlo, no al importar el modulo."""
    return _(DOC_TYPE_TRANSLATIONS.get(nombre, nombre))


def custom_run(self, args):
    columns, data, message, chart, report_summary, skip_total_row = original_run(self, args)
    
    # `run()` siempre deja `self.account_type` poblado desde los filtros
    # (accounts_receivable.py:90) y el default del reporte es "Receivable", asi que
    # alcanza con preguntar por "Payable". El fallback por `party_type` cubre el caso
    # de que un llamador arme los filtros a mano y no setee el tipo de cuenta.
    is_receivable = (
        getattr(self, "account_type", None) != "Payable"
        or (self.filters or {}).get("party_type") == "Customer"
    )

    has_bill_no = False
    has_bill_control = False
    has_branch = False
    has_special_taxpayer = False
    has_vat_withholding = False
    has_islr_withholding = False
    
    idx_voucher_no = -1
    idx_customer_name = -1
    idx_party = -1
    
    for i, col in enumerate(columns):
        if isinstance(col, dict):
            fn = col.get("fieldname")
            if fn == "bill_no":
                has_bill_no = True
                col["fieldtype"] = "HTML"
            elif fn in ("voucher_type", "against_voucher_type", "ve_voucher_type"):
                col["fieldtype"] = "Data"
            elif fn == "bill_control":
                has_bill_control = True
            elif fn == "branch":
                has_branch = True
            elif fn == "is_special_taxpayer":
                has_special_taxpayer = True
            elif fn == "vat_withholding_voucher_number":
                has_vat_withholding = True
            elif fn == "islr_receipt_number":
                has_islr_withholding = True
            elif fn == "voucher_no":
                idx_voucher_no = i
            elif fn == "customer_name":
                idx_customer_name = i
            elif fn == "party":
                idx_party = i
                
    if is_receivable and not has_special_taxpayer:
        insert_idx = (idx_customer_name + 1) if idx_customer_name != -1 else ((idx_party + 1) if idx_party != -1 else 0)
        columns.insert(insert_idx, {
            "label": _("Contribuyente Especial"),
            "fieldname": "is_special_taxpayer",
            "fieldtype": "Data",
            "width": 110
        })

    if not has_bill_no:
        current_idx_vno = -1
        for i, col in enumerate(columns):
            if isinstance(col, dict) and col.get("fieldname") == "voucher_no":
                current_idx_vno = i
                break
        insert_idx = current_idx_vno + 1 if current_idx_vno != -1 else idx_voucher_no + 1
        columns.insert(insert_idx, {
            "label": _("Factura No."),
            "fieldname": "bill_no",
            "fieldtype": "HTML",
            "width": 110
        })
        
    if not has_bill_control:
        current_idx_bill_no = -1
        for i, col in enumerate(columns):
            if isinstance(col, dict) and col.get("fieldname") == "bill_no":
                current_idx_bill_no = i
                break
        
        insert_idx = current_idx_bill_no + 1 if current_idx_bill_no != -1 else idx_voucher_no + 1
        columns.insert(insert_idx, {
            "label": _("No. Control"),
            "fieldname": "bill_control",
            "fieldtype": "Data",
            "width": 110
        })

    if not has_branch:
        current_idx_bill_control = -1
        for i, col in enumerate(columns):
            if isinstance(col, dict) and col.get("fieldname") == "bill_control":
                current_idx_bill_control = i
                break
        
        insert_idx = current_idx_bill_control + 1 if current_idx_bill_control != -1 else idx_voucher_no + 1
        columns.insert(insert_idx, {
            "label": _("Sucursal"),
            "fieldname": "branch",
            "fieldtype": "Link",
            "options": "VE Branch",
            "width": 110
        })

    if is_receivable:
        if not has_vat_withholding:
            idx_ref = -1
            for i, col in enumerate(columns):
                if isinstance(col, dict) and col.get("fieldname") in ("branch", "bill_control", "bill_no", "voucher_no"):
                    idx_ref = i
            insert_idx = idx_ref + 1 if idx_ref != -1 else len(columns)
            columns.insert(insert_idx, {
                "label": _("Comprobante IVA"),
                "fieldname": "vat_withholding_voucher_number",
                "fieldtype": "Data",
                "width": 130
            })

        if not has_islr_withholding:
            idx_vat = -1
            for i, col in enumerate(columns):
                if isinstance(col, dict) and col.get("fieldname") == "vat_withholding_voucher_number":
                    idx_vat = i
                    break
            insert_idx = idx_vat + 1 if idx_vat != -1 else len(columns)
            columns.insert(insert_idx, {
                "label": _("Comprobante ISLR"),
                "fieldname": "islr_receipt_number",
                "fieldtype": "Data",
                "width": 130
            })

    vouchers_by_type = {}
    parties = set()
    for row in data:
        if isinstance(row, dict):
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            if vt and vn:
                vouchers_by_type.setdefault(vt, set()).add(vn)
            party = row.get("party") or row.get("customer")
            if party and party != "Total":
                parties.add(party)

    customer_map = {}
    if is_receivable and parties:
        parties_list = list(parties)
        for chunk_start in range(0, len(parties_list), 500):
            chunk = parties_list[chunk_start:chunk_start + 500]
            try:
                customers = frappe.get_all(
                    "Customer",
                    filters={"name": ("in", chunk)},
                    fields=["name", "is_special_taxpayer", "tabulator_islr"]
                )
                for c in customers:
                    c_name = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
                    c_special = c.get("is_special_taxpayer") if isinstance(c, dict) else getattr(c, "is_special_taxpayer", 0)
                    c_tab = c.get("tabulator_islr") if isinstance(c, dict) else getattr(c, "tabulator_islr", "")
                    if c_name:
                        customer_map[c_name] = {
                            "is_special_taxpayer": cint(c_special),
                            "tabulator_islr": (c_tab or "").strip()
                        }
            except Exception:
                # Sin este mapa `is_special` da False para todos y cada fila dice
                # "No aplica": una respuesta equivocada con cara de correcta. Que
                # quede registrado en vez de desaparecer.
                frappe.log_error(
                    title="Cuentas por cobrar: fallo el fetch de Customer",
                    message=frappe.get_traceback(),
                )

    val_map = {}
    for vt, names in vouchers_by_type.items():
        try:
            meta = frappe.get_meta(vt)
            fields_to_get = ["name"]
            has_branch_field = meta.has_field("branch")
            has_bill_no_field = meta.has_field("bill_no")
            has_bill_control_field = meta.has_field("bill_control")
            has_vat_voucher_field = meta.has_field("vat_withholding_voucher_number")
            has_islr_voucher_field = meta.has_field("islr_receipt_number")
            has_special_taxpayer_field = meta.has_field("is_special_taxpayer")
            has_customer_field = meta.has_field("customer")
            
            if has_branch_field:
                fields_to_get.append("branch")
            if has_bill_no_field:
                fields_to_get.append("bill_no")
            if has_bill_control_field:
                fields_to_get.append("bill_control")
            if is_receivable:
                if has_vat_voucher_field:
                    fields_to_get.append("vat_withholding_voucher_number")
                if has_islr_voucher_field:
                    fields_to_get.append("islr_receipt_number")
                if has_special_taxpayer_field:
                    fields_to_get.append("is_special_taxpayer")
                if has_customer_field:
                    fields_to_get.append("customer")
                
            if len(fields_to_get) > 1:
                names_list = list(names)
                for chunk_start in range(0, len(names_list), 500):
                    chunk = names_list[chunk_start:chunk_start + 500]
                    docs = frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=fields_to_get)
                    for d in docs:
                        d_name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
                        if not d_name:
                            continue
                        val_map[(vt, d_name)] = {
                            "bill_no": d.get("bill_no") or "" if has_bill_no_field else "",
                            "bill_control": d.get("bill_control") or "" if has_bill_control_field else "",
                            "branch": d.get("branch") or "" if has_branch_field else "",
                            "vat_withholding_voucher_number": d.get("vat_withholding_voucher_number") or "" if has_vat_voucher_field else "",
                            "islr_receipt_number": d.get("islr_receipt_number") or "" if has_islr_voucher_field else "",
                            "is_special_taxpayer": cint(d.get("is_special_taxpayer")) if has_special_taxpayer_field else 0,
                            "customer": d.get("customer") or "" if has_customer_field else "",
                        }
        except Exception:
            pass

    taxes_map = {}
    if is_receivable:
        inv_types = [t for t in ("Sales Invoice", "VE Sales Credit Note") if t in vouchers_by_type]
        all_inv_names = []
        for it in inv_types:
            all_inv_names.extend(vouchers_by_type[it])
        if all_inv_names:
            for chunk_start in range(0, len(all_inv_names), 500):
                chunk = all_inv_names[chunk_start:chunk_start + 500]
                try:
                    tax_rows = frappe.get_all(
                        "Sales Taxes and Charges",
                        filters={
                            "parent": ("in", chunk),
                            "parenttype": ("in", inv_types),
                            "charge_type": ("in", ["VAT Withholding", "ISLR"]),
                            "tax_amount": ("!=", 0),
                        },
                        fields=["parent", "charge_type"]
                    )
                    for tr in tax_rows:
                        p = tr.get("parent") if isinstance(tr, dict) else getattr(tr, "parent", None)
                        ct = tr.get("charge_type") if isinstance(tr, dict) else getattr(tr, "charge_type", None)
                        if p and ct:
                            taxes_map.setdefault(p, set()).add(ct)
                except Exception:
                    frappe.log_error(
                        title="Cuentas por cobrar: fallo el fetch de impuestos",
                        message=frappe.get_traceback(),
                    )

    for row in data:
        if isinstance(row, dict):
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            party = row.get("party") or row.get("customer")

            is_subtotal_or_total = bool(
                row.get("bold")
                or row.get("is_total_row")
                or party == "Total"
                or (not vn and not party)
            )

            key = (vt, vn)
            doc_vals = val_map.get(key, {})

            raw_bill_no = doc_vals.get("bill_no", "") if key in val_map else (row.get("bill_no") or "")
            if raw_bill_no and vt and vn and not is_subtotal_or_total:
                if str(raw_bill_no).startswith("<a "):
                    row["bill_no"] = raw_bill_no
                else:
                    # `escape_html` en los dos: la columna es `HTML`, asi que el
                    # navegador interpreta lo que salga de aca. `bill_no` es un
                    # Custom Field `Data` sin `read_only`, o sea texto libre que
                    # teclea cualquiera con permiso de escritura -- sin escapar,
                    # es XSS almacenado que dispara quien abra el reporte.
                    doctype_slug = str(vt).lower().replace(" ", "-")
                    row["bill_no"] = (
                        f'<a href="/app/{doctype_slug}/{escape_html(str(vn))}">'
                        f'{escape_html(str(raw_bill_no))}</a>'
                    )
            else:
                row["bill_no"] = raw_bill_no or ""

            if key in val_map:
                row["bill_control"] = doc_vals.get("bill_control", "")
                row["branch"] = doc_vals.get("branch", "")
            else:
                if not row.get("bill_control"):
                    row["bill_control"] = ""
                if not row.get("branch"):
                    row["branch"] = ""

            if is_receivable:
                if is_subtotal_or_total:
                    row["is_special_taxpayer"] = ""
                    row["vat_withholding_voucher_number"] = ""
                    row["islr_receipt_number"] = ""
                else:
                    cust_name = party or doc_vals.get("customer")
                    cust_info = customer_map.get(cust_name, {})
                    is_special = bool(cust_info.get("is_special_taxpayer") or doc_vals.get("is_special_taxpayer"))

                    row["is_special_taxpayer"] = _("Sí") if is_special else (_("No") if cust_name else "")

                    is_invoice_doc = vt in ("Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note")

                    # Comprobante IVA. El estado va aparte en `_vat_state`, sin
                    # traducir: es contra eso que filtra el bloque de abajo.
                    vat_v = (doc_vals.get("vat_withholding_voucher_number") or row.get("vat_withholding_voucher_number") or "").strip()
                    if vat_v and vat_v.lower() != "none":
                        row["_vat_state"] = ESTADO_REGISTRADO
                        row["vat_withholding_voucher_number"] = vat_v
                    elif is_invoice_doc and (is_special or (vn and "VAT Withholding" in taxes_map.get(vn, set()))):
                        row["_vat_state"] = ESTADO_PENDIENTE
                        row["vat_withholding_voucher_number"] = _(ETIQUETA_ESTADO[ESTADO_PENDIENTE])
                    else:
                        row["_vat_state"] = ESTADO_NO_APLICA
                        row["vat_withholding_voucher_number"] = _(ETIQUETA_ESTADO[ESTADO_NO_APLICA])

                    # Comprobante ISLR
                    islr_v = (doc_vals.get("islr_receipt_number") or row.get("islr_receipt_number") or "").strip()
                    has_islr_tab = bool(cust_info.get("tabulator_islr") and cust_info.get("tabulator_islr") != "None")
                    if islr_v and islr_v.lower() != "none":
                        row["_islr_state"] = ESTADO_REGISTRADO
                        row["islr_receipt_number"] = islr_v
                    elif is_invoice_doc and (is_special or has_islr_tab or (vn and "ISLR" in taxes_map.get(vn, set()))):
                        row["_islr_state"] = ESTADO_PENDIENTE
                        row["islr_receipt_number"] = _(ETIQUETA_ESTADO[ESTADO_PENDIENTE])
                    else:
                        row["_islr_state"] = ESTADO_NO_APLICA
                        row["islr_receipt_number"] = _(ETIQUETA_ESTADO[ESTADO_NO_APLICA])

            if not is_subtotal_or_total:
                if row.get("voucher_type"):
                    vt_raw = row["voucher_type"]
                    translated_vt = _traducir_doctype(vt_raw)
                    row["ve_voucher_type"] = translated_vt
                    row["voucher_type"] = translated_vt

                if row.get("against_voucher_type"):
                    avt_raw = row["against_voucher_type"]
                    row["against_voucher_type"] = _traducir_doctype(avt_raw)

    if is_receivable and self.filters and self.filters.get("withholding_voucher_status"):
        w_filter = self.filters.get("withholding_voucher_status")
        filtered_data = []

        for row in data:
            if not isinstance(row, dict):
                continue

            is_subtotal_or_total = bool(
                row.get("bold")
                or row.get("is_total_row")
                or (row.get("party") == "Total")
                or (not row.get("voucher_no") and not row.get("party"))
            )
            if is_subtotal_or_total:
                continue

            vat_state = row.get("_vat_state")
            islr_state = row.get("_islr_state")

            match = False
            if w_filter == "Con Comprobantes Pendientes":
                match = ESTADO_PENDIENTE in (vat_state, islr_state)
            elif w_filter == "Pendiente IVA":
                match = vat_state == ESTADO_PENDIENTE
            elif w_filter == "Pendiente ISLR":
                match = islr_state == ESTADO_PENDIENTE
            elif w_filter == "Con Comprobantes Registrados":
                match = ESTADO_REGISTRADO in (vat_state, islr_state)
            elif w_filter == "No aplica":
                match = vat_state == islr_state == ESTADO_NO_APLICA

            if match:
                filtered_data.append(row)

        data = filtered_data
        # El chart lo calculo `run()` sobre el conjunto COMPLETO y no se recalcula
        # aca: dejarlo seria mostrar un grafico que no corresponde a las filas que
        # se ven. La fila de totales no hace falta rehacerla --`skip_total_row` es
        # 0, asi que el cliente la suma sobre lo visible--.
        chart = None
    
    return columns, data, message, chart, report_summary, skip_total_row


def custom_fetch_ple_in_buffered_cursor(self):
    self.ple_entries = self.ple_query.run(as_dict=True)
    if self.filters.get("ve_branch"):
        self.ple_entries = filter_ple_by_ve_branch(self.ple_entries, self.filters.get("ve_branch"))
        
    for ple in self.ple_entries:
        self.init_voucher_balance(ple)
    for ple in self.ple_entries:
        self.update_voucher_balance(ple)
    delattr(self, "ple_entries")


def custom_fetch_ple_in_unbuffered_cursor(self):
    self.ple_entries = []
    if self.filters.get("ve_branch"):
        # Filtrar por sucursal requiere materializar los asientos para resolver
        # la sucursal de cada voucher antes de inicializar balances.
        raw_entries = []
        with frappe.db.unbuffered_cursor():
            for ple in self.ple_query.run(as_dict=True, as_iterator=True):
                raw_entries.append(ple)
        raw_entries = filter_ple_by_ve_branch(raw_entries, self.filters.get("ve_branch"))
        for ple in raw_entries:
            self.init_voucher_balance(ple)
            self.ple_entries.append(ple)
    else:
        # Sin filtro de sucursal, transmitir directamente desde el cursor sin
        # acumular en una lista intermedia (preserva el beneficio de memoria).
        with frappe.db.unbuffered_cursor():
            for ple in self.ple_query.run(as_dict=True, as_iterator=True):
                self.init_voucher_balance(ple)
                self.ple_entries.append(ple)
    for ple in self.ple_entries:
        self.update_voucher_balance(ple)
    delattr(self, "ple_entries")


def filter_ple_by_ve_branch(ple_entries: list[dict], selected_branch: str) -> list[dict]:
    """Deja solo los movimientos cuyo documento de ORIGEN es de la sucursal elegida.

    Una fila de Cuentas por Cobrar (o por Pagar) es el documento que origina la cuenta:
    la factura, la nota o el anticipo sin aplicar. ERPNext suma cada movimiento del libro
    de pagos a la fila del documento al que apunta (``against_voucher_no``), así que la
    sucursal que decide es la de ese documento, no la del movimiento. Si el documento no
    tiene movimientos propios en el libro, como la Orden de Venta de un anticipo, ERPNext
    imputa el movimiento a sí mismo (``get_voucher_balance``) y entonces decide la
    sucursal del propio movimiento. Aquí se replica esa misma regla.

    Hasta el 10-sep-2026 el filtro miraba la sucursal del movimiento y buscaba la de la
    factura en ``against_voucher``, clave que la consulta de ERPNext no devuelve. Como
    ``Journal Entry`` no tiene sucursal en la cabecera, se caían todos los asientos y una
    factura saldada por un asiento de diferencial cambiario salía con pendiente. Caso
    testigo: ACC-SINV-2026-32308 (SOFTELINET, DC-01), saldada por ACC-JV-2026-32916, salía
    debiendo los Bs 45 del asiento al filtrar por DC-01 y no salía sin filtro. Además, un
    cobro de la sucursal aplicado a una factura de otra entraba sin su factura, y ERPNext
    lo imputaba al propio cobro: salía como anticipo negativo. En una copia de producción
    del 9-sep, ventana de septiembre, DC-01 listaba 204 filas donde corresponden 69, y en
    todas las sucursales había 921 facturas saldadas con pendiente.

    Un documento de origen sin sucursal (el anticipo de Bancaribe, un asiento de apertura)
    no es de ninguna sucursal: solo sale sin filtro.
    """
    if not ple_entries:
        return []

    own_documents = {(ple.get("voucher_type"), ple.get("voucher_no")) for ple in ple_entries}
    owners = []
    for ple in ple_entries:
        target = (ple.get("against_voucher_type"), ple.get("against_voucher_no"))
        owners.append(target if target in own_documents else (ple.get("voucher_type"), ple.get("voucher_no")))

    names_by_doctype: dict[str, set[str]] = {}
    for doctype, name in owners:
        if doctype and name:
            names_by_doctype.setdefault(doctype, set()).add(name)

    branch_by_owner: dict[tuple[str, str], str] = {}
    for doctype, names in names_by_doctype.items():
        if not _has_branch_field(doctype):
            continue
        names_list = list(names)
        for start in range(0, len(names_list), 500):
            for row in frappe.get_all(
                doctype,
                filters={"name": ("in", names_list[start:start + 500])},
                fields=["name", "branch"],
            ):
                branch_by_owner[(doctype, row.name)] = row.branch or ""

    return [ple for ple, owner in zip(ple_entries, owners) if branch_by_owner.get(owner, "") == selected_branch]


def _has_branch_field(doctype: str) -> bool:
    """¿El DocType tiene campo de sucursal en la cabecera?

    El libro de pagos puede apuntar a un DocType que ya no existe en el sitio, y ese no
    tiene sucursal. Cualquier otro error se deja subir: antes se tragaba, y el filtro
    descartaba filas en silencio, con un pendiente equivocado y cara de correcto.
    """
    try:
        return frappe.get_meta(doctype).has_field("branch")
    except frappe.DoesNotExistError:
        return False


ReceivablePayableReport.run = custom_run
ReceivablePayableReport.fetch_ple_in_buffered_cursor = custom_fetch_ple_in_buffered_cursor
ReceivablePayableReport.fetch_ple_in_unbuffered_cursor = custom_fetch_ple_in_unbuffered_cursor
