// Lógica para marcar producto exento en tablas hijas

const ITEM_DOCTYPES = [
    "Sales Invoice Item",
    "Purchase Invoice Item",
    "Sales Order Item",
    "Purchase Order Item",
    "Quotation Item",
    "Supplier Quotation Item"
];

function applyVatExemptLogic(frm, cdt, cdn) {
    const row = frappe.get_doc(cdt, cdn);

    if (row.item_code && !row.vat_exempt) {
        frappe.db.get_value(
            "Item",
            row.item_code,
            "vat_exempt",
            function (value) {
                if (value.vat_exempt) {
                    frappe.model.set_value(cdt, cdn, "vat_exempt", 1);
                }
            }
        );
    }
}

ITEM_DOCTYPES.forEach(doctype => {
    frappe.ui.form.on(doctype, {
        item_code: function (frm, cdt, cdn) {
            applyVatExemptLogic(frm, cdt, cdn);
        }
    });
});