# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_first_day, get_last_day, flt, fmt_money

class VEConatelTaxDeclaration(Document):
    def autoname(self) -> None:
        """Genera el nombre del documento basado en el rango de fechas con un secuencial."""
        from frappe.model.naming import make_autoname
        base_name = f"CONATEL-{self.company}-{self.from_date}-{self.to_date}-.#####"
        self.name = make_autoname(base_name)

    def after_insert(self) -> None:
        """Set defaults after creation if not already set."""
        from frappe.utils import now_datetime, nowdate
        now = now_datetime()
        if not self.declaration_year:
            self.declaration_year = now.year
        if not self.declaration_date:
            self.declaration_date = nowdate()

    @frappe.whitelist()
    def make_journal_entry(self):
        """Crea un Asiento Contable (Journal Entry) basado en los tributos calculados."""
        if self.journal_entry:
            frappe.throw(_("Ya existe un asiento contable asociado: {0}").format(self.journal_entry))
        
        if self.status != "Declarado":
            frappe.throw(_("Solo se puede generar el asiento contable cuando el estado es 'Declarado'."))
        
        if not self.taxes:
            frappe.throw(_("No hay tributos calculados para generar el asiento."))
            
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = self.declaration_date
        je.user_remark = _("Declaración CONATEL {0} al {1}").format(self.from_date, self.to_date)
        
        if not self.tax_payable_account or not self.tax_expense_account:
            frappe.throw(_("Debe configurar la Cuenta de Pasivo y "
                           "Gasto en la sección de Integración Contable."))
            
        je.append("accounts", {
            "account": self.tax_expense_account,
            "debit_in_account_currency": self.total_to_pay,
            "cost_center": frappe.get_cached_value("Company", self.company, "cost_center")
        })
        
        je.append("accounts", {
            "account": self.tax_payable_account,
            "credit_in_account_currency": self.total_to_pay,
        })
            
        je.insert()
        je.submit()
        
        self.db_set("journal_entry", je.name)
        return je.name

    @frappe.whitelist()
    def cancel_journal_entry(self):
        """Cancela y desvincula el asiento contable asociado."""
        if not self.journal_entry:
            frappe.throw(_("No hay un asiento contable asociado para cancelar."))
            
        je_name = self.journal_entry
        
        self.db_set("journal_entry", None)
        self.journal_entry = None
        
        je = frappe.get_doc("Journal Entry", je_name)
        if je.docstatus == 1:
            je.cancel()
        elif je.docstatus == 0:
            je.delete()

    def validate(self) -> None:
        """Valida rango de fechas, duplicados y recalcula totales y estado."""
        if self.from_date > self.to_date:
            frappe.throw(_("La fecha 'Desde' no puede ser mayor a la fecha 'Hasta'"))

        self.total_taxable_base = flt(sum(flt(item.taxable_base) for item in self.items), 2)
        self.total_to_pay = flt(sum(flt(tax.amount) for tax in self.taxes), 2)

        if self.num_declaration and self.declaration_document:
            self.status = "Declarado"
        elif self.total_taxable_base > 0:
            self.status = "Por Declarar"
        else:
            self.status = "Por Procesar"

        if self.company:
            comp = frappe.get_doc("Company", self.company)
            if not self.tax_id:
                self.tax_id = comp.tax_id
            if not getattr(self, "legal_representative", None):
                self.legal_representative = getattr(comp, "legal_representative", None)
            if not self.currency:
                self.currency = comp.default_currency
            if not getattr(self, "fiscal_address", None) and getattr(comp, "custom_company_primary_address", None):
                self.fiscal_address = frappe.db.get_value("Address", comp.custom_company_primary_address, "address_line1")

        if self.is_new():
            self.tax_id = frappe.db.get_value("Company", self.company, "tax_id")
            
            overlap = frappe.db.sql("""
                SELECT name FROM `tabVE Conatel Tax Declaration`
                WHERE 
                    company = %s 
                    AND docstatus != 2
                    AND to_date >= %s
                    AND from_date <= %s
            """, (self.company, self.from_date, self.to_date))
            
            if overlap:
                frappe.msgprint(_("⚠️ **Advertencia**: El periodo seleccionado se solapa con una declaración existente: {0}. Verifica que no estés duplicando información.").format(overlap[0][0]), indicator='orange')

@frappe.whitelist()
def get_conatel_data(company, from_date, to_date, branch=None, cost_center=None, customer=None):
    """Obtiene los datos de ingresos y calcula tributos dinámicamente usando un rango de fechas.
    Unifica la fuente de verdad bimonetaria tanto para la Declaración como para el Reporte Detallado.
    """
    query_filters = [company, from_date, to_date]
    
    # Filtro de Sucursal
    branch_filter = ""
    if branch:
        if frappe.db.has_column("VE Branch", "lft") and frappe.db.has_column("VE Branch", "rgt"):
            b_info = frappe.db.get_value("VE Branch", branch, ["lft", "rgt"], as_dict=True)
            if b_info:
                branch_filter = "AND si.branch IN (SELECT name FROM `tabVE Branch` WHERE lft >= %s AND rgt <= %s)"
                query_filters.extend([b_info.lft, b_info.rgt])
        else:
            branch_filter = "AND si.branch = %s"
            query_filters.append(branch)

    # Filtro de Centro de Costos
    cost_center_filter = ""
    if cost_center:
        cost_center_filter = "AND sii.cost_center = %s"
        query_filters.append(cost_center)

    # Filtro de Cliente
    customer_filter = ""
    if customer:
        customer_filter = "AND si.customer = %s"
        query_filters.append(customer)

    detailed_query = f"""
        SELECT 
            si.name as invoice,
            si.posting_date,
            (CASE 
                WHEN si.is_return = 1 THEN 'Nota de Crédito'
                WHEN si.is_debit_note = 1 THEN 'Nota de Débito'
                ELSE 'Factura'
            END) as document_type,
            si.bill_control as control_no,
            si.customer,
            si.tax_id,
            si.branch,
            sii.cost_center,
            sii.item_code,
            sii.item_name,
            sii.base_amount,
            si.is_return,
            (CASE WHEN si.is_return = 1 THEN -sii.base_amount ELSE sii.base_amount END) as net_amount,
            i.is_conatel_service as is_conatel_service,
            si.conversion_rate,
            si.currency
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON sii.parent = si.name
        LEFT JOIN `tabItem` i ON sii.item_code = i.name
        WHERE 
            si.docstatus = 1 
            AND si.company = %s
            AND si.posting_date BETWEEN %s AND %s
            {branch_filter}
            {cost_center_filter}
            {customer_filter}
        ORDER BY si.posting_date ASC, si.name ASC
    """

    raw_data = frappe.db.sql(detailed_query, tuple(query_filters), as_dict=True)
    tax_types = frappe.get_all("VE Conatel Tax Type", fields=["name", "aliquot"])

    # Acumuladores para el Report Summary
    total_taxable_usd = 0.0
    total_taxable_ves = 0.0
    total_taxes_usd = 0.0
    total_taxes_ves = 0.0

    # Diccionario para agrupar los datos por Cliente, Sucursal, Centro de Costos, Producto y Documento (Detallado)
    grouped_data = {}
    unique_invoices = set()

    for row in raw_data:
        net_amount_usd = flt(row.net_amount)
        rate = flt(row.conversion_rate) if row.conversion_rate else 1.0
        net_amount_ves = net_amount_usd * rate

        # Sumar a las bases de CONATEL (todos los items se asumen sujetos por requerimiento)
        taxable_base_usd = net_amount_usd
        taxable_base_ves = net_amount_ves

        total_taxable_usd += taxable_base_usd
        total_taxable_ves += taxable_base_ves
        unique_invoices.add(row.invoice)

        # Clave única de agrupación por Factura (para mostrar exactamente una factura por línea)
        key = (row.invoice, row.posting_date, row.document_type, row.control_no, row.customer, row.tax_id, row.branch, row.cost_center)

        if key not in grouped_data:
            grouped_data[key] = {
                "invoice": row.invoice,
                "posting_date": row.posting_date,
                "document_type": row.document_type,
                "control_no": row.control_no,
                "customer": row.customer,
                "tax_id": row.tax_id,
                "branch": row.branch,
                "cost_center": row.cost_center,
                "item_codes": set(),
                "item_names": set(),
                "taxable_base_usd": 0.0,
                "taxable_base_ves": 0.0,
                "conversion_rate": rate
            }
            # Inicializar los tributos dinámicos en 0
            for t in tax_types:
                grouped_data[key][frappe.scrub(f"conatel_tax_{t.name}_usd")] = 0.0
                grouped_data[key][frappe.scrub(f"conatel_tax_{t.name}_ves")] = 0.0

        # Acumular
        grouped_entry = grouped_data[key]
        grouped_entry["taxable_base_usd"] += taxable_base_usd
        grouped_entry["taxable_base_ves"] += taxable_base_ves
        if row.item_code:
            grouped_entry["item_codes"].add(row.item_code)
        if row.item_name:
            grouped_entry["item_names"].add(row.item_name)

        # Calcular cada tributo dinámico en USD y VES y acumularlos
        for t in tax_types:
            aliquot = flt(t.aliquot)
            val_usd = flt(taxable_base_usd * (aliquot / 100.0), 2)
            val_ves = flt(taxable_base_ves * (aliquot / 100.0), 2)
            
            grouped_entry[frappe.scrub(f"conatel_tax_{t.name}_usd")] += val_usd
            grouped_entry[frappe.scrub(f"conatel_tax_{t.name}_ves")] += val_ves

            total_taxes_usd += val_usd
            total_taxes_ves += val_ves

    # Construir la lista final de datos detallada
    detailed_data = []
    for key, val in grouped_data.items():
        # Consolidar los códigos y nombres de ítems si la factura tuviera varios
        val["item_code"] = ", ".join(sorted(list(val["item_codes"])))
        val["item_name"] = ", ".join(sorted(list(val["item_names"])))

        del val["item_codes"]
        del val["item_names"]
        
        # Redondear
        val["taxable_base_usd"] = flt(val["taxable_base_usd"], 2)
        val["taxable_base_ves"] = flt(val["taxable_base_ves"], 2)
        for t in tax_types:
            f_usd = frappe.scrub(f"conatel_tax_{t.name}_usd")
            f_ves = frappe.scrub(f"conatel_tax_{t.name}_ves")
            val[f_usd] = flt(val[f_usd], 2)
            val[f_ves] = flt(val[f_ves], 2)

        detailed_data.append(val)

    # Recalcular el total consolidado de impuestos aplicando alícuotas sobre los totales de base imponible
    # para garantizar un cuadre idéntico centavo a centavo con la Declaración consolidada
    total_taxes_usd = 0.0
    total_taxes_ves = 0.0
    for t in tax_types:
        aliquot = flt(t.aliquot)
        total_taxes_usd += flt(total_taxable_usd * (aliquot / 100.0), 2)
        total_taxes_ves += flt(total_taxable_ves * (aliquot / 100.0), 2)

    def format_money_ve(val):
        formatted = f"{flt(val):,.2f}"
        return formatted.replace(",", "X").replace(".", ",").replace("X", ".")

    # Construir el Report Summary con formato limpio usando tipo de dato "Data"
    # para evitar que Frappe concatene automáticamente la conversión de monedas base en la vista
    report_summary = [
        {
            "value": f"$ {format_money_ve(total_taxable_usd)}",
            "indicator": "Green",
            "label": _("Total Ingresos Sujetos (USD)"),
            "datatype": "Data"
        },
        {
            "value": f"Bs. {format_money_ve(total_taxable_ves)}",
            "indicator": "Blue",
            "label": _("Total Ingresos Sujetos (Bs.)"),
            "datatype": "Data"
        },
        {
            "value": f"$ {format_money_ve(total_taxes_usd)}",
            "indicator": "Orange",
            "label": _("Total Impuestos CONATEL (USD)"),
            "datatype": "Data"
        },
        {
            "value": f"Bs. {format_money_ve(total_taxes_ves)}",
            "indicator": "Red",
            "label": _("Total Impuestos CONATEL (Bs.)"),
            "datatype": "Data"
        }
    ]

    # Consolidar para la pantalla de Declaración (retorna en bolívares reales la base)
    items_consolidated = []
    if unique_invoices:
        items_consolidated.append({
            "item_code": "Total Facturado",
            "item_name": "Resumen de Ventas del Periodo",
            "invoice_count": len(unique_invoices),
            "taxable_base": flt(total_taxable_ves, 2)
        })

    # Calcular los impuestos correspondientes para la pantalla de Declaración en bolívares
    calculated_taxes = []
    for t in tax_types:
        aliquot = flt(t.aliquot)
        amount = flt(total_taxable_ves * (aliquot / 100.0), 2)
        calculated_taxes.append({
            "tax_type": t.name,
            "aliquot": aliquot,
            "amount": amount
        })

    return {
        "items": items_consolidated,
        "taxes": calculated_taxes,
        "total_taxable_base": flt(total_taxable_ves, 2),
        "detailed_data": detailed_data,
        "report_summary": report_summary
    }
