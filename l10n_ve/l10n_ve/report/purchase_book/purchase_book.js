// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

/**
 * Descarga un archivo codificado en base64 desde el servidor.
 * @param {string} filename - Nombre del archivo a descargar.
 * @param {string} base64Content - Contenido codificado en base64.
 * @param {string} mimeType - Tipo MIME del archivo.
 */
function download_base64_file(filename, base64Content, mimeType) {
  const byteCharacters = atob(base64Content);
  const byteNumbers = new Array(byteCharacters.length);
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i);
  }
  const byteArray = new Uint8Array(byteNumbers);
  const blob = new Blob([byteArray], { type: mimeType });

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.style.display = "none";
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  URL.revokeObjectURL(url);
  document.body.removeChild(a);
}

frappe.query_reports["purchase_book"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company"),
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
  ],

  onload: function (report) {
    // Botón: Formato Detallado (formato actual)
    report.page.add_inner_button(
      __("Formato Detallado"),
      () =>
        _export_excel(
          report,
          "l10n_ve.l10n_ve.report.purchase_book.excel_builder.create_excel_file"
        ),
      __("Exportar Excel")
    );

    // Botón: Formato Fiscal (formato SENIAT)
    report.page.add_inner_button(
      __("Formato Fiscal"),
      () =>
        _export_excel(
          report,
          "l10n_ve.l10n_ve.report.purchase_book.seniat_excel_builder.create_seniat_excel_file"
        ),
      __("Exportar Excel")
    );

    // Botón: Generar XML ISLR
    report.page.add_inner_button(__("Generar XML ISLR"), function () {
      const filters = report.get_filter_values();
      if (!filters.company) {
        frappe.throw(
          __("Por favor, selecciona una Compañía para generar el XML.")
        );
        return;
      }

      frappe.dom.freeze();
      frappe.call({
        method:
          "l10n_ve.l10n_ve.report.purchase_book.purchase_book.generate_xml_islr_file",
        args: { filters: JSON.stringify(filters) },
        callback: function (r) {
          frappe.dom.unfreeze();
          if (r.message) {
            const blob = new Blob([r.message], { type: "text/xml" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "retenciones_islr.xml";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            frappe.show_alert({
              message: __("Reporte XML ISLR generado correctamente."),
              indicator: "green",
            });
          } else {
            frappe.msgprint(
              __(
                "No se encontraron datos de retención de ISLR para los filtros seleccionados."
              )
            );
          }
        },
        error: function () {
          frappe.dom.unfreeze();
          frappe.throw(
            __(
              "Ocurrió un error al generar el archivo XML. Por favor, revisa el Log de Errores."
            )
          );
        },
      });
    });

    // Botón: Descargar TXT
    report.page.add_inner_button(__("Descargar TXT"), function () {
      const filters = report.get_filter_values();
      if (!filters.company) {
        frappe.throw(
          __("Por favor, selecciona una Compañía para generar el TXT.")
        );
        return;
      }

      frappe.dom.freeze();
      frappe.call({
        method:
          "l10n_ve.l10n_ve.report.purchase_book.purchase_book.generate_txt_file",
        args: { filters: JSON.stringify(filters) },
        callback: function (r) {
          frappe.dom.unfreeze();
          if (r.message && r.message.type === "download") {
            download_base64_file(
              r.message.filename,
              r.message.filecontent,
              "text/plain;charset=utf-8"
            );
            frappe.show_alert({
              message: __("Archivo TXT generado y descargado con éxito."),
              indicator: "green",
            });
          } else {
            frappe.throw(
              __("Ocurrió un error inesperado al generar el archivo.")
            );
          }
        },
        error: function () {
          frappe.dom.unfreeze();
          frappe.throw(
            __(
              "Error al comunicarse con el servidor para generar el archivo."
            )
          );
        },
      });
    });
  },
};

/**
 * Helper compartido para exportar Excel (ambos formatos).
 */
function _export_excel(report, method) {
  frappe.dom.freeze();

  const filters = report.get_filter_values();
  if (!filters.company) {
    frappe.dom.unfreeze();
    frappe.throw(
      __("Por favor, selecciona una Compañía para generar el reporte.")
    );
    return;
  }

  frappe.call({
    method: method,
    args: {
      report_name: "Libro de Compra",
      filters: JSON.stringify(filters),
    },
    callback: function (r) {
      frappe.dom.unfreeze();
      if (r.message && r.message.type === "download") {
        download_base64_file(
          r.message.filename,
          r.message.filecontent,
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        );
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
        __(
          "Ocurrió un error al generar el archivo. Por favor, revisa el Log de Errores."
        )
      );
    },
  });
}
