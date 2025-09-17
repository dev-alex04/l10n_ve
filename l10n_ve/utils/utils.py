import frappe

@frappe.whitelist()
def get_company_address(company_name):
    if not company_name:
        return

    try:
        company_doc = frappe.get_doc("Company", company_name)
        address_link = company_doc.get("custom_company_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting company address")

@frappe.whitelist()
def get_supplier_address(supplier_name):
    if not supplier_name:
        return

    try:
        supplier_doc = frappe.get_doc("Supplier", supplier_name)
        address_link = supplier_doc.get("supplier_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting supplier address")



def check_gl_entries(gl_entries: list=[], do_exit: bool = True) -> None:
    # NO QUITAR PRINT SE USA PARA DEBUGEAR
    print('INICIO ASIENTO')

    debit = credit = 0

    data = {
        'gls': [],
        'info': {
            'DEBE': 0,
            'HABER': 0,
            'DIFERENCIA': 0,
        }
    }

    for gl in gl_entries:
        debit += gl['debit']
        credit += gl['credit']

        data['gls'].append(
            f'account: {gl.get("account")}, DEBE: {gl.get("debit")} HABER: {gl.get("credit")}'
        )

        print(
            'account: ', gl.get('account'),
            ' DEBE: ', gl.get('debit'),
            # ' debito USD ', gl.get('usd_debit'),
            ' HABER: ', gl.get('credit'),
            # 'credito USD ', gl.get('usd_credit'),
            # ' documento: ', gl.get('voucher_no'),
              # ' tipo documento: ', gl.get('voucher_type'),
              # ' contra doctype', gl.get('against_voucher_type'),
              # ' contra documento',  gl.get('against_voucher'),
              # ' contra cuenta',  gl.get('against'),
            #   gl.get('posting_date'), 'fecha ',
              )

    print('DEBE: ', debit,  'HABER: ', credit, ' DIFERENCIA: ', debit - credit)
    print('FIN ASIENTO')

    data['info']['DEBE'] = debit
    data['info']['HABER'] = credit
    data['info']['DIFERENCIA'] = debit - credit

    frappe.publish_realtime(
            "database_debug",
            {
                'data': data,
            },
        )

    if do_exit:
        exit()
