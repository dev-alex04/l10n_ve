# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_defaults


class VEMunicipalityTaxDeclaration(Document):

    def on_cancel(self) -> None:
        """
        Evita la cancelación si ya se han cargado los datos de la declaración municipal.
        """

        if not self.num_declaration and not self.declaration_document:
            return

        frappe.throw(
            _("No se puede cancelar la declaración si ya se "
             "ha cargado el número o el documento de la declaración municipal."),
            title=_("Cancelación no permitida")
        )

    def before_insert(self) -> None:
        """
        Valida que no existan documentos con estado 'Sin adjuntar Declaración'
        antes de permitir la creación de uno nuevo.
        """

        incomplete_doc_name = frappe.db.get_value(
            "VE Municipality Tax Declaration",
            filters={
                "company": self.company,
                "docstatus": 1,
                "declaration_document": ["is", "not set"]
            },
            fieldname="name"
        )

        if incomplete_doc_name:
            doc_link = frappe.utils.get_link_to_form("VE Municipality Tax Declaration",
                                                      incomplete_doc_name)

            message = _("No se puede crear una nueva declaración. Primero debe"
                        " completar el documento pendiente: {0}").format(doc_link)

            frappe.throw(message, title=_("Declaración Pendiente"))

    def autoname(self) -> None:
        """
        Genera el nombre del documento basado en el mes y el año.
        """
        name_parts = ["Declaración Municipal"]
        if self.branch:
            name_parts.append(self.branch)
        
        name_parts.extend([self.company, self.declaration_month, self.declaration_year])
        
        self.name = " - ".join(str(p) for p in name_parts if p)

    def validate(self) -> None:
        """
        Valida que no exista otra declaración para el mismo período y compañía.
        """
        if not (self.is_new() and self.company and self.declaration_month and self.declaration_year):
            return

        existing_declaration = frappe.db.exists("VE Municipality Tax Declaration", {
            "company": self.company,
            "declaration_month": self.declaration_month,
            "declaration_year": self.declaration_year,
            "branch": self.branch,
            "docstatus": 1,
        })
        if existing_declaration:
            frappe.throw(
                _("Ya existe una declaración para {0} en {1} - {2}.").format(
                    self.company, self.declaration_month, self.declaration_year),
                title=_("Declaración Duplicada"))

        self.validate_branch()

        duplicate_branch = frappe.db.exists("VE Municipality Tax Declaration", {
            "company": self.company,
            "declaration_month": self.declaration_month,
            "declaration_year": self.declaration_year,
            "branch": self.branch,
            "name": ["!=", self.name],
            "docstatus": ["!=", 2]
        })

        if duplicate_branch:
            frappe.throw(
                f"Ya existe una declaración registrada para la sucursal <b>{self.branch}</b> "
                f"en el periodo {self.declaration_month} {self.declaration_year}."
            )

    def validate_branch(self) -> None:
        if frappe.db.exists("VE Branch", {"company": self.company}):
            if not self.branch:
                frappe.throw(_("El campo Sucursal es obligatorio para esta empresa."))


@frappe.whitelist()
def upload_declaration_data(docname, num_declaration, declaration_document) -> dict[str,str]:
    """
    Actualiza los campos num_declaration y declaration_document de una declaración.
    """

    frappe.db.set_value("VE Municipality Tax Declaration", docname, {
        "num_declaration": num_declaration,
        "declaration_document": declaration_document
    })
    return {"status": "success",
             "message": "Datos de declaración actualizados exitosamente."}


@frappe.whitelist()
def get_activities_from_sales_invoices(from_date, to_date, company, municipality, branch=None) -> list:
    """
    Busca en las Facturas de Venta, pero obtiene la actividad económica 
    directamente desde el Item (Producto) y no de la línea de la factura.
    """
    if not from_date or not to_date or not company or not municipality:
        return []

    branch_filter = ""
    query_args = {
        "from_date": from_date,
        "to_date": to_date,
        "company": company
    }

    if branch:
        branch_filter = " AND si.branch = %(branch)s"
        query_args["branch"] = branch

    invoice_items = frappe.db.sql(f"""
        SELECT 
            it.economic_activity as economic_activity,
            SUM(sii.base_amount) as taxable_base
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON sii.parent = si.name
        INNER JOIN `tabItem` it ON sii.item_code = it.name
        WHERE 
            si.docstatus = 1 
            AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
            AND si.company = %(company)s
            {branch_filter}
            AND it.economic_activity IS NOT NULL
            AND it.economic_activity != ''
        GROUP BY it.economic_activity
    """, query_args, as_dict=True)

    if not invoice_items:
        return []

    activity_names = [d.economic_activity for d in invoice_items]

    activity_details = frappe.get_all("VE Economic Activity",
        filters={"name": ["in", activity_names]},
        fields=["name", "code", "sector", "branch"]
    )
    activity_map = {d.name: d for d in activity_details}

    tax_details = frappe.get_all("VE Municipality Taxes",
        filters={
            "economic_activity": ["in", activity_names],
            "municipality": municipality
        },
        fields=["economic_activity", "aliquot", "mt_tcmmv"]
    )
    tax_details_map = {d.economic_activity: d for d in tax_details}

    missing_tax_activities = []
    final_list = []

    for item in invoice_items:
        details = activity_map.get(item.economic_activity)
        
        if not details:
            missing_tax_activities.append(item.economic_activity)
            continue
            
        item.update(details)
        
        tax_info = tax_details_map.get(item.economic_activity)

        if tax_info:
            item.update(tax_info)
            final_list.append(item)
        else:
            missing_tax_activities.append(details.code)

    if missing_tax_activities:
        link_to_taxes = "<a href='/app/ve-municipality-taxes'>Impuesto Municipal</a>"
        message = _("No se ha definido el impuesto municipal para las "
                    "siguientes actividades económicas en este "
                    "municipio: {0}. Por favor, agréguelo en {1}.").format(
                        f"<b>{', '.join(missing_tax_activities)}</b>", link_to_taxes)
        frappe.throw(message, title=_("Impuesto Municipal No Definido"))

    return final_list

@frappe.whitelist()
def get_exchange_rate(declaration_date, from_currency) -> float:

    to_currency = get_defaults().get("currency")
    if not declaration_date or not from_currency or not to_currency:
        return 0

    exchange_rate = frappe.db.get_value(
        "Currency Exchange",
        filters={
            "date": [">=", declaration_date],
            "from_currency": from_currency,
            "to_currency": to_currency,

        },
        fieldname="exchange_rate",
        order_by="date asc",
    )

    if not exchange_rate:
        exchange_rate = frappe.db.get_value(
            "Currency Exchange",
            filters={
                "date": ["<=", declaration_date],
                "from_currency": from_currency,
                "to_currency": to_currency,
            },
            fieldname="exchange_rate",
            order_by="date desc",
        )
    return exchange_rate or 0

@frappe.whitelist()
def get_company_details_for_declaration(company_name: str) -> dict:
    """
    Obtiene los detalles de la compañía y su dirección principal para la declaración.
    """
    if not company_name:
        return {}

    company = frappe.get_doc("Company", company_name, fields=[
        "tax_id", "num_license_economic", "legal_representative",
        "legal_representative_id", "municipality", "custom_company_primary_address"
    ])

    details = company.as_dict()
    details["address_details"] = None

    if company.custom_company_primary_address:
        try:
            address = frappe.get_doc("Address", company.custom_company_primary_address, fields=[
                "address_line1", "state", "parish", "phone", "email_id", "sector"
            ])
            address_details = address.as_dict()


            if address.state:
                address_details["state_name"] = frappe.db.get_value("VE State",
                                                                    address.state,
                                                                    "state")
            if address.parish:
                address_details["parish_name"] = frappe.db.get_value("VE Parish",
                                                                     address.parish,
                                                                     "parish")

            details["address_details"] = address_details

        except frappe.DoesNotExistError:
            frappe.log_error(
                f"La dirección '{company.custom_company_primary_address}' no fue encontrada.",
                "Error en get_company_details_for_declaration"
            )

    if company.municipality:
        details["municipality_name"] = frappe.db.get_value("VE Municipality",
                                                            company.municipality,
                                                            "municipality")

    return details


@frappe.whitelist()
def get_branch_details(branch_name):
    data = frappe.db.sql("""
        SELECT 
            m.municipality as municipality,
            m.name as municipality_id,
            s.state as state
        FROM `tabVE Branch` b
        JOIN `tabVE Municipality` m ON b.municipality = m.name
        JOIN `tabVE State` s ON b.state = s.name
        WHERE b.branch_name = %s
    """, (branch_name,), as_dict=1)

    return data[0] if data else {}
