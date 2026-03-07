frappe.ui.form.on("Stock Entry", {
	refresh: function(frm) {
        if (!frm.doc.reference_currency) {
            frappe.msgprint({
                title: __('Advertencia'),
                indicator: 'orange',
                message: __('La moneda de referencia para la compañía seleccionada no está configurada.')
            });
        }
	}
});