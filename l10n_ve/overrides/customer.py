import frappe
from frappe import _
from frappe.utils import flt
from erpnext.selling.doctype.customer.customer import Customer
from l10n_ve.utils.utils import validate_tax_id_format, validate_unique_tax_id, validate_taxpayer_and_person_type_consistency
from l10n_ve.utils.utils import link_address_to_party


class VECustomer(Customer):
    def validate(self):
        super().validate()

        validate_tax_id_format(self)
        validate_unique_tax_id(self)
        validate_taxpayer_and_person_type_consistency(self)

        if not self.is_special_taxpayer:
            self.tax_withholding_category = None
            self.ve_municipality = None
            self.economic_activity = None
            self.municipal_withholding_rate = 0.0
            self.municipality_tax = None
        elif self.municipal_withholding_rate is not None:
            rate = flt(self.municipal_withholding_rate)
            if rate < 0 or rate > 100:
                frappe.throw(_("La alícuota municipal debe estar entre 0% y 100%."))

    def on_update(self):
        super().on_update()

        if self.customer_primary_address:
            link_address_to_party(self.customer_primary_address,
                                  self.doctype,
                                  self.name)

        validate_taxpayer_and_person_type_consistency(self)

    def get_email_list(self) -> list[str]:
        if not self.email_id:
            return []
        return [email.strip() for email in self.email_id.split(",") if email.strip()]

def get_customer_emails(customer_name):
    """
    Busca un cliente por su ID y devuelve la lista de correos.
    """
    doc = frappe.get_doc("Customer", customer_name)
    if hasattr(doc, "get_email_list"):
        return doc.get_email_list()

    return VECustomer.get_email_list(doc)

def get_customer_dashboard_data(data: dict) -> dict:
    """
    Extiende el tablero de conexiones del Cliente para incluir
    VE Sales Credit Note y VE Sales Debit Note en el grupo de Órdenes.
    """
    for group in data.get("transactions", []):
        if group.get("label") in (_("Orders"), "Orders"):
            items: list[str] = group.get("items", [])
            for doctype in ["VE Sales Credit Note", "VE Sales Debit Note"]:
                if doctype not in items:
                    items.append(doctype)
            break

    return data


@frappe.whitelist()
def get_balance_summary(customer: str) -> dict:
    """
    Obtiene un resumen contable detallado y las facturas pendientes
    de un cliente para mostrar en la ficha del Cliente, manejando correctamente
    los anticipos no aplicados y la moneda de la cuenta contable.
    """
    # Obtener la moneda de la cuenta contable del cliente
    # Buscamos la cuenta contable de cuentas por cobrar predeterminada para el cliente
    company = frappe.defaults.get_user_default("Company") or frappe.db.get_value("Company", {}, "name")
    account_currency = None
    if company:
        # Buscar cuenta de cobro del cliente
        debit_to = frappe.db.get_value("Party Account", {"parent": customer, "parenttype": "Customer", "company": company}, "account")
        if not debit_to:
            debit_to = frappe.db.get_value("Company", company, "default_receivable_account")
        if debit_to:
            account_currency = frappe.db.get_value("Account", debit_to, "account_currency")
            
    if not account_currency:
        account_currency = frappe.db.get_value("Company", company, "default_currency") or "USD"

    # Obtener todas las partidas de GL Entry activas del cliente
    entries = frappe.db.sql(
        """
        SELECT 
            voucher_type,
            voucher_no,
            debit_in_account_currency,
            credit_in_account_currency
        FROM `tabGL Entry`
        WHERE party_type = 'Customer' AND party = %s AND is_cancelled = 0
        """,
        (customer,),
        as_dict=True
    )
    
    total_invoiced = 0.0
    total_paid = 0.0
    total_withholdings = 0.0
    total_credits = 0.0
    
    for entry in entries:
        debit = float(entry.debit_in_account_currency or 0)
        credit = float(entry.credit_in_account_currency or 0)
        
        if debit > 0:
            total_invoiced += debit
        if credit > 0:
            if entry.voucher_type in ("Payment Entry", "Journal Entry"):
                total_paid += credit
            elif entry.voucher_type == "VE Sales Credit Note" or (entry.voucher_type == "Sales Invoice" and "NC" in entry.voucher_no):
                total_credits += credit
            elif entry.voucher_type == "Sales Invoice":
                # Retenciones de IVA/ISLR registradas en la propia factura
                total_withholdings += credit
            else:
                total_paid += credit

    # Saldo contable neto del cliente
    net_balance = total_invoiced - total_paid - total_withholdings - total_credits
                
    # Obtener facturas abiertas
    open_invoices = frappe.db.sql(
        """
        SELECT 
            name,
            bill_no,
            posting_date,
            due_date,
            outstanding_amount,
            currency
        FROM `tabSales Invoice`
        WHERE customer = %s AND docstatus = 1 AND outstanding_amount > 0
        ORDER BY due_date ASC
        """,
        (customer,),
        as_dict=True
    )
    
    formatted_invoices = []
    open_invoices_total = 0.0
    for inv in open_invoices:
        due_date = inv.due_date
        today = frappe.utils.getdate()
        days_overdue = (today - due_date).days if today > due_date else 0
        
        # El outstanding_amount en ERPNext para facturas de clientes con cuenta VEF
        # se almacena en la moneda de la cuenta (VEF/Bs).
        outstanding = float(inv.outstanding_amount)
        open_invoices_total += outstanding
        
        formatted_invoices.append({
            "name": inv.name,
            "bill_no": inv.bill_no or inv.name,
            "posting_date": frappe.utils.format_date(inv.posting_date),
            "due_date": frappe.utils.format_date(inv.due_date),
            "outstanding_amount": outstanding,
            "currency": account_currency,  # Usamos la moneda de la cuenta contable
            "days_overdue": days_overdue
        })
        
    # Calcular anticipos o notas de crédito sin aplicar a facturas
    unapplied_credits = 0.0
    if open_invoices_total > net_balance:
        unapplied_credits = open_invoices_total - net_balance

    return {
        "account_currency": account_currency,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "total_withholdings": total_withholdings,
        "total_credits": total_credits,
        "net_balance": net_balance,
        "open_invoices_total": open_invoices_total,
        "unapplied_credits": unapplied_credits,
        "open_invoices": formatted_invoices
    }


@frappe.whitelist()
def get_municipal_tax_info(customer: str) -> dict:
    """Retorna la información actual de retención municipal de un cliente.

    Pre-carga los valores guardados o intenta resolver el municipio predeterminado
    desde las direcciones del cliente.

    Args:
        customer: Nombre del Customer.

    Returns:
        Diccionario con municipality, economic_activity, municipality_tax,
        municipal_withholding_rate, la alícuota existente y el municipio sugerido.
    """
    doc = frappe.get_cached_doc("Customer", customer)

    suggested_municipality = ""
    # Intentar resolver el municipio predeterminado desde la dirección
    # Primero buscamos dirección predeterminada de facturación o envío
    address_name = frappe.db.get_value(
        "Dynamic Link",
        {"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
        "parent"
    )
    if address_name:
        addr = frappe.get_cached_doc("Address", address_name)
        if addr.county and frappe.db.exists("VE Municipality", addr.county):
            suggested_municipality = addr.county
        elif addr.parish:
            mun = frappe.db.get_value("VE Parish", addr.parish, "municipality")
            if mun and frappe.db.exists("VE Municipality", mun):
                suggested_municipality = mun

    result: dict = {
        "municipality": doc.get("ve_municipality") or suggested_municipality or "",
        "economic_activity": doc.get("economic_activity") or "",
        "municipality_tax": doc.get("municipality_tax") or "",
        "municipal_withholding_rate": float(doc.get("municipal_withholding_rate") or 0),
        "existing_aliquot": 0.0,
        "suggested_municipality": suggested_municipality,
    }

    # Intentar traer la alícuota del registro existente en VE Municipality Taxes
    municipality = result["municipality"]
    economic_activity = result["economic_activity"]
    if municipality and economic_activity:
        existing = frappe.db.get_value(
            "VE Municipality Taxes",
            {"municipality": municipality, "economic_activity": economic_activity},
            ["name", "aliquot"],
            as_dict=True,
        )
        if existing:
            result["municipality_tax"] = existing.name
            result["existing_aliquot"] = float(existing.aliquot or 0)

    return result


@frappe.whitelist()
def setup_or_update_municipal_tax(
    customer: str,
    municipality: str,
    economic_activity: str,
    aliquot: float,
    activity_code: str = None,
) -> dict:
    """Crea o actualiza el registro en VE Municipality Taxes y enlaza al cliente.

    Si se proporciona `activity_code`, busca el registro por su campo `code` o
    `name`, o crea una nueva actividad económica si no existe.

    Args:
        customer:          Nombre del Customer.
        municipality:      Nombre del registro VE Municipality.
        economic_activity: Nombre o código del registro VE Economic Activity.
        aliquot:           Alícuota de retención en % (ej: 1.5).
        activity_code:     Código de actividad editado por el usuario.

    Returns:
        Diccionario con el nombre del registro VE Municipality Taxes, alícuota y actividad.
    """
    frappe.has_permission("Customer", ptype="write", doc=customer, throw=True)

    aliquot = float(aliquot or 0)
    if aliquot < 0 or aliquot > 100:
        frappe.throw(_("La alícuota municipal debe estar entre 0% y 100%."))

    target_act_docname: str | None = None

    # 1. Intentar resolver la actividad económica por activity_code (por campo code o name)
    if activity_code:
        target_act_docname = frappe.db.get_value("VE Economic Activity", {"code": activity_code}, "name")
        if not target_act_docname and frappe.db.exists("VE Economic Activity", activity_code):
            target_act_docname = activity_code

    # 2. Si no se encontró por activity_code, buscar por el economic_activity recibido
    if not target_act_docname and economic_activity:
        if frappe.db.exists("VE Economic Activity", economic_activity):
            target_act_docname = economic_activity
        else:
            target_act_docname = frappe.db.get_value("VE Economic Activity", {"code": economic_activity}, "name")

    # 3. Si aún no existe y se ingresó un activity_code nuevo, crear la actividad económica
    if not target_act_docname and activity_code:
        orig = None
        if economic_activity and frappe.db.exists("VE Economic Activity", economic_activity):
            orig = frappe.get_doc("VE Economic Activity", economic_activity)

        if orig:
            new_act = frappe.get_doc({
                "doctype": "VE Economic Activity",
                "code": activity_code,
                "sector": orig.sector,
                "group": orig.group,
                "branch": orig.branch,
                "description": orig.description,
                "is_group": 0,
                "parent_ve_economic_activity": orig.parent_ve_economic_activity,
            })
        else:
            new_act = frappe.get_doc({
                "doctype": "VE Economic Activity",
                "code": activity_code,
                "sector": "TERCIARIO",
                "group": "SERVICIOS",
                "branch": "TELECOMUNICACIONES",
                "description": f"Actividad económica {activity_code}",
                "is_group": 0,
            })

        new_act.insert(ignore_permissions=True)
        frappe.db.commit()
        target_act_docname = new_act.name

    if not target_act_docname:
        frappe.throw(_("No se pudo encontrar ni crear la Actividad Económica especificada."))

    economic_activity = target_act_docname

    # Obtener state del municipio para el campo requerido en VE Municipality Taxes
    state = frappe.get_cached_value("VE Municipality", municipality, "state") or ""

    existing_name: str | None = frappe.db.get_value(
        "VE Municipality Taxes",
        {"municipality": municipality, "economic_activity": economic_activity},
        "name",
    )

    if existing_name:
        # Actualizar la alícuota si cambió
        frappe.db.set_value(
            "VE Municipality Taxes", existing_name, "aliquot", aliquot,
            update_modified=True
        )
        tax_name: str = existing_name
    else:
        # Crear el registro de impuesto municipal
        tax_doc = frappe.get_doc({
            "doctype": "VE Municipality Taxes",
            "state": state,
            "municipality": municipality,
            "economic_activity": economic_activity,
            "aliquot": aliquot,
        })
        tax_doc.flags.ignore_links = True
        tax_doc.insert(ignore_permissions=True)
        tax_name = tax_doc.name

    # Actualizar el Customer
    frappe.db.set_value("Customer", customer, {
        "ve_municipality": municipality,
        "economic_activity": economic_activity,
        "municipality_tax": tax_name,
        "municipal_withholding_rate": aliquot,
    }, update_modified=True)

    frappe.db.commit()

    return {
        "municipality_tax": tax_name,
        "aliquot": aliquot,
        "economic_activity": economic_activity,
    }


@frappe.whitelist()
def remove_municipal_tax(customer: str) -> dict:
    """Elimina la configuración de impuesto municipal del cliente (resetea los campos a vacío)."""
    frappe.has_permission("Customer", ptype="write", doc=customer, throw=True)

    frappe.db.set_value("Customer", customer, {
        "ve_municipality": "",
        "economic_activity": "",
        "municipality_tax": "",
        "municipal_withholding_rate": 0.0,
    }, update_modified=True)

    frappe.db.commit()

    return {"status": "success"}


