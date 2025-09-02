// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

// frappe.ui.form.on("VAT Withholding Voucher", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on('VAT Withholding Voucher', {
    refresh: function(frm) {
        // Accede al campo de la tabla hija usando su nombre de campo
        // Reemplaza 'nombre_de_tu_tabla' por el nombre del campo de tipo Tabla que creaste.
        let child_table = frm.fields_dict['vat_withholding_voucher_item'];
        console.log(child_table);

        // Si la tabla existe, establece la consulta en el campo 'purchase_invoice' dentro de ella
        // if (child_table) {
        //     child_table.grid.get_field('purchase_invoice').set_query(function(doc) {
        //         // Solo muestra las facturas de compra del proveedor seleccionado en el formulario padre
        //         console.log(doc);
        //         return {
        //             filters: {
        //                 'supplier': doc.supplier
        //             }
        //         };
        //     });
        // }
    }
});

frappe.ui.form.on('VAT Withholding Voucher Item', {
    pur: function(frm, cdt, cdn) {
        // Esta función se activa cuando se selecciona una factura en la tabla
        let row = locals[cdt][cdn];
        // console.log(row);

        if (row.purchase_invoice) {
            frappe.db.get_doc('Purchase Invoice', row.purchase_invoice)
                .then(doc => {
                    // Mapea los datos de la factura de compra a la tabla de retenci�n
                    frappe.model.set_value(cdt, cdn, 'bill_no', doc.bill_no);
                    frappe.model.set_value(cdt, cdn, 'bill_control', doc.bill_control); // Asume que este campo existe
                    frappe.model.set_value(cdt, cdn, 'bill_date', doc.bill_date); // Usa 'posting_date' como fecha de factura
                });
        }
    }
});