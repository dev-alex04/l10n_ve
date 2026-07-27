// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

// Filtros y exportaciones del Reporte HQ de facturas de venta. Mismos filtros
// que el Libro de Ventas (Company / Fechas / Sucursal) para que sea
// intercambiable, más la sucursal principal; la diferencia está en el ACCESO
// (rol dedicado VE Sales Book HQ) y en las columnas HQ.

frappe.query_reports["VE Sales Invoices HQ"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      // Sin default a propósito: con un filtro obligatorio vacío Frappe no
      // ejecuta al abrir. Es lo que evita la corrida automática inicial en un
      // reporte pesado (mismo patrón que el Mayor Analítico de excle_account).
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
    {
      // Solo las sucursales de consolidación (las que cuelgan de la raíz).
      fieldname: "main_branch",
      label: __("Sucursal Principal"),
      fieldtype: "Link",
      options: "VE Branch",
      get_query: () => ({
        query:
          "l10n_ve.l10n_ve.report.ve_sales_invoices_hq.ve_sales_invoices_hq.get_main_branches",
      }),
    },
    {
      // Ejecución manual: el reporte es pesado y Frappe re-ejecuta con cada
      // cambio de filtro. Como filtro de tipo Button queda dentro de la fila,
      // junto a Sucursal Principal.
      fieldname: "run_report",
      label: __("Ejecutar"),
      fieldtype: "Button",
      click: function () {
        const filters = frappe.query_report.get_values();
        if (!filters.company || !filters.from_date || !filters.to_date) {
          frappe.msgprint({
            title: __("Filtros requeridos"),
            message: __("Seleccione Compañía, Fecha Desde y Fecha Hasta."),
            indicator: "orange",
          });
          return;
        }
        frappe.query_report.refresh();
      },
    },
  ],

  onload: function (report) {
    // El reporte es pesado (segundos por corrida). Por defecto Frappe lo
    // re-ejecuta con CADA cambio de filtro: con cinco filtros eso son cinco
    // corridas para armar una sola consulta. Con _no_refresh el usuario ajusta
    // todos los filtros y decide cuándo correrlo.
    report._no_refresh = true;

    // btn_class no siempre agarra en los filtros de tipo Button: se fuerza.
    report.page.page_form
      .find('[data-fieldname="run_report"] .btn')
      .removeClass("btn-default")
      .addClass("btn-primary");

    report.page.add_inner_button(__("Exportar Excel"), () =>
      _hq_export(report, {
        method:
          "l10n_ve.l10n_ve.report.ve_sales_invoices_hq.excel_export.download_hq_excel",
        loading: __("Generando el Excel..."),
        mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );

    // El resumen ejecutivo en PDF existe y funciona
    // (pdf_export.download_hq_pdf), pero NO se expone como botón: el motor de
    // PDF de Frappe es wkhtmltopdf, con un WebKit viejo que no ejecuta
    // JavaScript ni admite flex/grid, y el resultado no llega al acabado que
    // exige un documento que sale hacia afuera. Para reactivarlo basta con
    // volver a agregar el add_inner_button; no hace falta tocar el servidor.
  },
};

// Ambas exportaciones se arman en memoria en el servidor y viajan en base64:
// no queda ningún archivo en el disco del servidor que haya que limpiar.
// El indicador usa el logo de marca compartido (l10n_ve.brand): generar el
// archivo del período completo tarda segundos y, sin una señal visible, el
// usuario cree que no pasó nada y vuelve a pulsar el botón.
function _hq_export(report, options) {
  const filters = report.get_filter_values();

  if (!filters.company) {
    frappe.throw(__("Seleccione una Compañía para exportar el reporte."));
    return;
  }

  frappe.dom.freeze(
    l10n_ve.brand.loading(
      options.loading,
      __("Puede tardar según el rango de fechas"),
    ),
  );

  frappe.call({
    method: options.method,
    args: { filters: JSON.stringify(filters) },
    callback: function (r) {
      frappe.dom.unfreeze();

      if (!r.message || r.message.type !== "download") {
        frappe.msgprint({
          title: __("Error"),
          message: __("No se pudo generar el archivo."),
          indicator: "red",
        });
        return;
      }

      _hq_download_blob(r.message.filecontent, r.message.filename, options.mime);
      frappe.show_alert({ message: __("Archivo descargado."), indicator: "green" });
    },
    error: function () {
      frappe.dom.unfreeze();
      frappe.msgprint({
        title: __("Error"),
        message: __(
          "Ocurrió un error al generar el archivo. Revise el Log de Errores.",
        ),
        indicator: "red",
      });
    },
  });
}

// El blob se libera apenas dispara la descarga: en una exportación grande son
// megabytes retenidos por la pestaña si no se revoca el object URL.
function _hq_download_blob(base64_content, filename, mime) {
  const bytes = Uint8Array.from(atob(base64_content), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: mime });

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}
