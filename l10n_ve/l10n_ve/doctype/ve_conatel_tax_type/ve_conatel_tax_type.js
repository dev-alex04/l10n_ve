frappe.ui.form.on("VE Conatel Tax Type", {
    setup: function (frm) {
        frm.set_query("tax_payable_account", function () {
            return {
                filters: {
                    is_group: 0
                }
            };
        });
        frm.set_query("tax_expense_account", function () {
            return {
                filters: {
                    is_group: 0
                }
            };
        });
    }
});
