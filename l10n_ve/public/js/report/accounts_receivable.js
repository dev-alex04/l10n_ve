(function () {
    const report = frappe.query_reports["Accounts Receivable"];
    if (!report || !report.filters) return;

    const has_ve_branch = report.filters.some(f => f.fieldname === "ve_branch");
    if (!has_ve_branch) {
        const company_idx = report.filters.findIndex(f => f.fieldname === "company");
        const insert_idx = company_idx !== -1 ? company_idx + 1 : report.filters.length;
        report.filters.splice(insert_idx, 0, {
            fieldname: "ve_branch",
            label: __("Sucursal VE"),
            fieldtype: "Link",
            options: "VE Branch",
        });
    }
})();
