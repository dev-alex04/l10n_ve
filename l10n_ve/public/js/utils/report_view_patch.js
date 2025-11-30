// Monkey patch to fix Report View for Script/Query Reports
// This handles the case where a user accesses a Script Report via the Report Builder view
// which causes a crash because doc.json is undefined.

(function () {
  // Wait for frappe.views.ReportView to be available
  const patch_report_view = function () {
    if (frappe.views && frappe.views.ReportView) {
      const original_get_report_doc =
        frappe.views.ReportView.prototype.get_report_doc;

      frappe.views.ReportView.prototype.get_report_doc = function () {
        return original_get_report_doc.call(this).then((doc) => {
          if (
            doc &&
            ["Script Report", "Query Report"].includes(doc.report_type)
          ) {
            frappe.set_route("query-report", this.report_name);

            // Return a dummy doc with valid JSON to prevent crash in the subsequent then() block
            // of setup_defaults() while the redirect happens.
            return {
              ...doc,
              json: JSON.stringify({
                filters: [],
                fields: [],
                order_by: "modified desc",
                add_totals_row: 0,
                page_length: 20,
                column_widths: {},
                group_by: null,
                chart_args: null,
              }),
            };
          }
          return doc;
        });
      };
    } else {
      // Retry if not yet loaded (though usually app_include_js loads after core)
      setTimeout(patch_report_view, 100);
    }
  };

  // Start the patch attempt
  $(document).ready(function () {
    patch_report_view();
  });
})();
