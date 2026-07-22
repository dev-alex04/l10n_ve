// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Reconciliation", {
    refresh(frm) {
        // Inicializar campos de resumen a 0 al refrescar
        frm.set_value("custom_total_selected_invoices", 0);
        frm.set_value("custom_total_selected_payments", 0);
        frm.set_value("custom_reconciliation_difference", 0);
        update_selection_status(frm, 0, 0, 0);

        // Bindear eventos a las tablas
        bind_selection_events(frm);
    },
    onload(frm) {
        bind_selection_events(frm);
    }
});

function bind_selection_events(frm) {
    // Eventos para tabla de Facturas
    if (frm.fields_dict.invoices && !frm.custom_invoices_bound) {
        $(frm.fields_dict.invoices.wrapper).on("change", ".grid-row-check, .grid-heading-row input[type='checkbox']", function() {
            setTimeout(() => {
                recalculate_selection_balance(frm);
            }, 50);
        });
        frm.custom_invoices_bound = true;
    }

    // Eventos para tabla de Pagos
    if (frm.fields_dict.payments && !frm.custom_payments_bound) {
        $(frm.fields_dict.payments.wrapper).on("change", ".grid-row-check, .grid-heading-row input[type='checkbox']", function() {
            setTimeout(() => {
                recalculate_selection_balance(frm);
            }, 50);
        });
        frm.custom_payments_bound = true;
    }
}

function recalculate_selection_balance(frm) {
    let total_invoices = 0.0;
    let total_payments = 0.0;

    // Calcular facturas seleccionadas
    if (frm.fields_dict.invoices && frm.fields_dict.invoices.grid) {
        const selected_invoices = frm.fields_dict.invoices.grid.get_selected_children();
        selected_invoices.forEach(row => {
            total_invoices += flt(row.outstanding_amount);
        });
    }

    // Calcular pagos seleccionados
    if (frm.fields_dict.payments && frm.fields_dict.payments.grid) {
        const selected_payments = frm.fields_dict.payments.grid.get_selected_children();
        selected_payments.forEach(row => {
            total_payments += flt(row.amount);
        });
    }

    const difference = total_payments - total_invoices;

    // Actualizar campos en el DocType (sólo lectura)
    frm.set_value("custom_total_selected_invoices", flt(total_invoices, 2));
    frm.set_value("custom_total_selected_payments", flt(total_payments, 2));
    frm.set_value("custom_reconciliation_difference", flt(difference, 2));

    // Actualizar estado visual (HTML)
    update_selection_status(frm, difference, total_invoices, total_payments);
}

function update_selection_status(frm, difference, total_invoices, total_payments) {
    if (!frm.fields_dict.custom_selection_status_html) return;

    let html_content = "";

    if (total_invoices === 0 && total_payments === 0) {
        html_content = `
            <div style="padding: 10px; border-radius: 6px; background-color: var(--bg-light-gray, #f8f9fa); border: 1px solid var(--border-color, #d1d8dd); color: var(--text-muted, #8d99a6); font-weight: bold; text-align: center;">
                ℹ️ Seleccione facturas y pagos para calcular balance
            </div>
        `;
    } else {
        // Intentar obtener la moneda del primer documento seleccionado
        let currency = "";
        if (frm.fields_dict.invoices && frm.fields_dict.invoices.grid) {
            const selected = frm.fields_dict.invoices.grid.get_selected_children();
            if (selected.length) currency = selected[0].currency;
        }
        if (!currency && frm.fields_dict.payments && frm.fields_dict.payments.grid) {
            const selected = frm.fields_dict.payments.grid.get_selected_children();
            if (selected.length) currency = selected[0].currency;
        }
        if (!currency) {
            currency = frm.doc.company ? frappe.get_doc("Company", frm.doc.company).default_currency : "VES";
        }

        const formatted_diff = format_currency(Math.abs(difference), currency);

        if (Math.abs(difference) < 0.01) {
            html_content = `
                <div style="padding: 10px; border-radius: 6px; background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; font-weight: bold; text-align: center;">
                    ✔ Cuadrado exacto (Diferencia: ${format_currency(0, currency)})
                </div>
            `;
        } else if (difference > 0) {
            html_content = `
                <div style="padding: 10px; border-radius: 6px; background-color: #d1ecf1; border: 1px solid #bee5eb; color: #0c5460; font-weight: bold; text-align: center;">
                    🔵 Saldo a favor del cliente: +${formatted_diff}
                </div>
            `;
        } else {
            html_content = `
                <div style="padding: 10px; border-radius: 6px; background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; font-weight: bold; text-align: center;">
                    🔴 Pendiente por cubrir: -${formatted_diff}
                </div>
            `;
        }
    }

    frm.fields_dict.custom_selection_status_html.html(html_content);
}
