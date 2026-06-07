function _load_company_info(report) {
  const company = report && report.get_filter_value && report.get_filter_value("company");
  if (!company) {
    if (report) report.company_info = null;
    return;
  }
  frappe.db.get_value("Company", company, ["company_logo", "tax_id"]).then((r) => {
    report.company_info = (r && r.message) || {};
  });
}

frappe.query_reports["Sales book"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company"),
      on_change: () => _load_company_info(frappe.query_report),
    },
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.month_start(),
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.month_end(),
    },
    {
      fieldname: "branch",
      label: __("Sucursal"),
      fieldtype: "Link",
      options: "VE Branch",
      get_query: () => ({
        filters: { company: frappe.query_report.get_filter_value("company") },
      }),
    },
  ],

  onload: function (report) {
    _load_company_info(report);

    report.page.add_inner_button(
      __("Formato Detallado"),
      () => _export_excel(
        report,
        "l10n_ve.l10n_ve.report.sales_book.excel_builder.create_excel_file",
      ),
      __("Exportar Excel"),
    );

    report.page.add_inner_button(
      __("Formato Fiscal"),
      () => _export_excel(
        report,
        "l10n_ve.l10n_ve.report.sales_book.seniat_excel_builder.create_seniat_excel_file",
      ),
      __("Exportar Excel"),
    );
  },
};

function _export_excel(report, method) {
  frappe.dom.freeze();

  const filters = report.get_filter_values();
  if (!filters.company) {
    frappe.dom.unfreeze();
    frappe.throw(
      __("Por favor, selecciona una Compañía para generar el reporte."),
    );
    return;
  }

  frappe.call({
    method: method,
    args: { report_name: "Sales book", filters: JSON.stringify(filters) },
    callback: function (r) {
      frappe.dom.unfreeze();
      if (r.message && r.message.type === "download") {
        const byteCharacters = atob(r.message.filecontent);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const blob = new Blob([new Uint8Array(byteNumbers)], {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        });

        const a = document.createElement("a");
        a.style.display = "none";
        a.href = URL.createObjectURL(blob);
        a.download = r.message.filename;
        document.body.appendChild(a);
        a.click();
        URL.revokeObjectURL(a.href);
        document.body.removeChild(a);

        frappe.show_alert({
          message: __("Reporte Excel generado y descargado correctamente."),
          indicator: "green",
        });
      } else {
        frappe.throw(__("No se pudo generar el archivo de Excel."));
      }
    },
    error: function () {
      frappe.dom.unfreeze();
      frappe.throw(
        __("Ocurrió un error al generar el archivo. Por favor, revisa el Log de Errores."),
      );
    },
  });
}
