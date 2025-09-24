frappe.ui.form.on("Sales Invoice", {

    onload: function(frm) {
        if (frm.is_new()) {

            frm.set_value('bill_no', null);
            frm.set_value('credit_note_no', null);
            frm.set_value('debit_note_no', null);
            frm.set_value('bill_control', null);
        }

        frm.set_df_property('vat_withholding_voucher_number', 'read_only', 1);
        frm.set_df_property('withholding_date', 'read_only', 1);
        frm.set_df_property('voucher_image', 'read_only', 1);

        toggle_document_number_fields(frm);
        toggle_vat_withholding_fields(frm);
    },

    refresh: function(frm) {
        toggle_vat_withholding_fields(frm);

        if (!frm.doc.__islocal && !frm.custom_buttons["Cargar Comprobante de Retencion"]) {

            if (frm.doc.customer) {
                frappe.db
                    .get_value("Customer", frm.doc.customer, "is_special_taxpayer")
                    .then(r => {
                        if (r.message && r.message.is_special_taxpayer) {

                            frm.add_custom_button(__('Cargar Comprobante de Retencion'), () => {

                                const dialog = new frappe.ui.Dialog({
                                    title: __('Cargar Comprobante de Pago y Número'),
                                    fields: [
                                        {
                                            label: __('Número de Comprobante'),
                                            fieldname: 'vat_withholding_voucher_number',
                                            fieldtype: 'Data',
                                            reqd: 0
                                        },
                                        {
                                            label: __('Fecha de Comprobante'),
                                            fieldname: 'withholding_date',
                                            fieldtype: 'Date',
                                            reqd: 0
                                        },
                                        {
                                            label: __('Imagen/PDF del Comprobante'),
                                            fieldname: 'voucher_image',
                                            fieldtype: 'Attach',
                                            reqd: 0
                                        },
                                        {
                                            fieldname: 'invoice_id',
                                            fieldtype: 'Data',
                                            hidden: 1,
                                            default: frm.doc.name
                                        }
                                    ],
                                    primary_action_label: __('Subir y Guardar'),
                                    primary_action: (values) => {


                                        frappe.call({
                                            method: 'l10n_ve.overrides.sales_invoice.upload_voucher_data',
                                            args: {
                                                docname: frm.doc.name,
                                                voucher_number: values.vat_withholding_voucher_number,
                                                withholding_date: values.withholding_date,
                                                file_url: values.voucher_image
                                            },
                                            callback: function(r) {
                                                if (r.message && r.message.status === 'success') {
                                                    frappe.msgprint(__('Comprobante cargado y datos guardados exitosamente.'));
                                                    frm.reload_doc(); // Recargar el formulario
                                                    dialog.hide();
                                                } else if (r.message && r.message.status === 'error') {
                                                    frappe.msgprint(__('Error al guardar: ' + r.message.msg), 'Error');
                                                 }
                                    }
                                });
                            }
                        });
                        dialog.show();
                    });
                 }
            });
         }
        }
    },

    customer: function(frm) {
        toggle_vat_withholding_fields(frm);
        frm.refresh();
    },

    is_return: function(frm) {
        toggle_document_number_fields(frm);
    },

    is_debit_note: function(frm) {
        toggle_document_number_fields(frm);
    }
});


function toggle_document_number_fields(frm) {
    const is_credit_note = frm.doc.is_return;
    const is_debit_note = frm.doc.is_debit_note;

    frm.toggle_display(['bill_no'], !is_credit_note && !is_debit_note);
    frm.toggle_display(['credit_note_no'], is_credit_note);
    frm.toggle_display(['debit_note_no'], is_debit_note);

    frm.toggle_display(['bill_control'], true);
}


function toggle_vat_withholding_fields(frm) {
    const fields_to_toggle = [
        "vat_withholding_voucher_number",
        "withholding_date",
        "voucher_image",
    ];

    frm.toggle_display(fields_to_toggle, false);

    const has_voucher_data = frm.doc.vat_withholding_voucher_number;

    if (has_voucher_data) {
        frm.toggle_display(fields_to_toggle, true);
        return;
    }

    if (frm.doc.customer) {
        frappe.db
            .get_value("Customer", frm.doc.customer, "is_special_taxpayer")
            .then(r => {
                if (r.message && r.message.is_special_taxpayer) {
                    frm.toggle_display(fields_to_toggle, true);
                }
            });
    }
}