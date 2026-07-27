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
      on_change: _hq_mark_stale,
    },
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.month_start(),
      on_change: _hq_mark_stale,
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.month_end(),
      on_change: _hq_mark_stale,
    },
    {
      fieldname: "branch",
      label: __("Sucursal"),
      fieldtype: "Link",
      options: "VE Branch",
      get_query: () => ({
        filters: { company: frappe.query_report.get_filter_value("company") },
      }),
      on_change: _hq_mark_stale,
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
      on_change: _hq_mark_stale,
    },
    {
      // Ejecución manual: el reporte es pesado y Frappe re-ejecuta con cada
      // cambio de filtro. Como filtro de tipo Button queda dentro de la fila,
      // junto a Sucursal Principal.
      fieldname: "run_report",
      label: __("Ejecutar"),
      fieldtype: "Button",
      click: function () {
        const report = frappe.query_report;
        // get_filter_values() sin argumento no lanza por obligatorios vacíos:
        // la validación de abajo es la que da el mensaje entendible.
        const filters = report.get_filter_values();
        if (!filters.company || !filters.from_date || !filters.to_date) {
          frappe.msgprint({
            title: __("Filtros requeridos"),
            message: __("Seleccione Compañía, Fecha Desde y Fecha Hasta."),
            indicator: "orange",
          });
          return;
        }
        _hq_clear_stale(report);
        report.refresh();
      },
    },
  ],

  onload: function (report) {
    _hq_setup_manual_run(report);

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

// ── Ejecución manual ────────────────────────────────────────────────────────
//
// Frappe re-ejecuta el reporte con CADA cambio de filtro y en uno pesado eso
// son varias corridas completas para armar una sola consulta.
//
// `_no_refresh` NO sirve para esto: refresh_report() lo pone en true, invoca el
// onload y lo devuelve a false acto seguido (query_report.js:405-409), así que
// lo que se le asigne desde onload se pierde en la misma vuelta. El hook que sí
// aguanta es `on_change` en cada filtro: cuando está definido, Frappe lo llama
// EN VEZ de refresh() (query_report.js:564-568). Es el mismo mecanismo que usa
// el Mayor Analítico de excle_account, sólo que allá el callback está vacío y
// aquí además avisa que hay cambios sin aplicar.
const HQ_NOTICE_CLASS = "hq-stale-notice";

function _hq_notice(report) {
  return report.page.wrapper.find("." + HQ_NOTICE_CLASS);
}

// Se llama desde el `on_change` de cada filtro de datos.
function _hq_mark_stale() {
  const report = frappe.query_report;
  if (!report) return;

  // Al abrir el reporte, set_route_filters() carga los filtros que vengan en la
  // URL y eso también dispara este callback. Durante esa carga Frappe mantiene
  // _no_refresh en true (query_report.js:405-409), así que sirve para saber que
  // el cambio lo hizo el framework y no el usuario: sin esto el aviso saldría
  // apenas se abre el reporte.
  if (report._no_refresh) return;

  _hq_notice(report)
    .html(
      __(
        "Los filtros cambiaron. Presione <b>Ejecutar</b> para actualizar el reporte.",
      ),
    )
    .show();

  // El botón pasa a primario sólo cuando hay algo pendiente: así el color dice
  // si lo que está en pantalla corresponde o no a los filtros de arriba.
  _hq_run_button(report).removeClass("btn-default").addClass("btn-primary");
}

function _hq_clear_stale(report) {
  _hq_notice(report).hide();
  _hq_run_button(report).removeClass("btn-primary").addClass("btn-default");
}

function _hq_run_button(report) {
  return report.page.page_form.find('[data-fieldname="run_report"] .btn');
}

function _hq_setup_manual_run(report) {
  // setup_filters() rehace los controles en cada entrada al reporte; sin esto
  // se acumularía un aviso huérfano por visita.
  _hq_notice(report).remove();
  report.page.page_form.after(
    `<div class="form-message orange ${HQ_NOTICE_CLASS}" style="display:none;"></div>`,
  );

  // btn_class no siempre agarra en los filtros de tipo Button: se fuerza.
  _hq_run_button(report).removeClass("btn-default").addClass("btn-primary");

  // El icono de recargar corre el reporte sin pasar por el botón, que es
  // justo lo que se quiere evitar; queda una sola forma de ejecutarlo.
  // Se usa la referencia que guarda Frappe (query_report.js:94) y no un
  // selector por tooltip: ese texto pasa por __() y en español no matchearía.
  report.refresh_button && report.refresh_button.hide();
}

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
