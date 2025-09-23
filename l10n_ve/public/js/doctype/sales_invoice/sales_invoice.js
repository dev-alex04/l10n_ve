frappe.ui.form.on("Sales Invoice", {
    // La lógica de visualización inicial
    onload: function(frm) {
        // Lógica para limpiar campos en documentos nuevos
        if (frm.is_new()) {
            frm.set_value('bill_no', null);
            frm.set_value('credit_note_no', null);
            frm.set_value('debit_note_no', null);
            frm.set_value('bill_control', null);
        }

        // Llamamos a las funciones de visualización inicial
        toggle_document_number_fields(frm);
        toggle_vat_withholding_fields(frm);
    },

    refresh: function(frm) {
        toggle_vat_withholding_fields(frm);
    },

    customer: function(frm) {
        toggle_vat_withholding_fields(frm);
    },

    is_return: function(frm) {
        toggle_document_number_fields(frm);
    },

    is_debit_note: function(frm) {
        toggle_document_number_fields(frm);
    }
});

// Funciones de ayuda

function toggle_document_number_fields(frm) {
    const is_credit_note = frm.doc.is_return;
    const is_debit_note = frm.doc.is_debit_note;

    // Solo muestra el campo de número de factura, nota de crédito o débito
    frm.toggle_display(['bill_no'], !is_credit_note && !is_debit_note);
    frm.toggle_display(['credit_note_no'], is_credit_note);
    frm.toggle_display(['debit_note_no'], is_debit_note);
    
    // El número de control siempre es visible
    frm.toggle_display(['bill_control'], true); 
}

function toggle_vat_withholding_fields(frm) {
    const fields_to_toggle = [
        "vat_withholding_voucher_number",
        "withholding_date",
    ];
    
    frm.toggle_display(fields_to_toggle, false);

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