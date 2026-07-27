// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

// Filtros del Reporte HQ de facturas de venta. Mismos filtros que el Libro de
// Ventas (Company / Fechas / Sucursal) para que sea intercambiable; la
// diferencia está en el ACCESO (rol dedicado VE Sales Book HQ) y en que aquí
// irán las columnas HQ (serie-número, municipio/sucursal) sin tocar el libro.

// Indicador de progreso de la exportación. Generar el Excel del período
// completo toma ~15s (y ~45s proyectado a 30.000 facturas): sin una señal
// visible el usuario cree que no pasó nada y vuelve a pulsar el botón.
const HQ_EXPORT_SPINNER = `
  <div style="display:flex;flex-direction:column;align-items:center;gap:14px;">
    <style>
      .hq-spinner-svg { width: 56px; height: 56px; }
      .hq-part { animation: hq-lift 2s ease-in-out infinite; }
      /* Un color por cuadrante, tomados del logo de marca
         (apps/resources/DominaLogo.png). El rombo de domina_isp es monocromo
         azul; este usa la paleta completa. */
      .hq-p1 { fill: #E91A4B; --tx: -6px; --ty: -6px; animation-delay: 0.0s; } /* arriba-izquierda */
      .hq-p2 { fill: #FF5100; --tx:  6px; --ty: -6px; animation-delay: 0.5s; } /* arriba-derecha   */
      .hq-p3 { fill: #00B5E5; --tx:  6px; --ty:  6px; animation-delay: 1.0s; } /* abajo-derecha    */
      .hq-p4 { fill: #009B52; --tx: -6px; --ty:  6px; animation-delay: 1.5s; } /* abajo-izquierda  */
      @keyframes hq-lift {
        0%, 40%, 100% { transform: translate(0, 0); opacity: .85; }
        20% { transform: translate(var(--tx), var(--ty)); opacity: 1; }
      }
    </style>
    <svg viewBox="0 0 100 100" class="hq-spinner-svg">
      <g transform="translate(50,50)">
        <path class="hq-part hq-p1" d="M -44,-1 L -1,-44 L -1,-26 L -26,-1 Z" />
        <path class="hq-part hq-p2" d="M 1,-44 L 44,-1 L 26,-1 L 1,-26 Z" />
        <path class="hq-part hq-p3" d="M 44,1 L 1,44 L 1,26 L 26,1 Z" />
        <path class="hq-part hq-p4" d="M -1,44 L -44,1 L -26,1 L -1,26 Z" />
      </g>
    </svg>
    <div>${__("Generando el Excel...")}</div>
    <div class="text-muted small">${__("Puede tardar según el rango de fechas")}</div>
  </div>
`;

frappe.query_reports["VE Sales Invoices HQ"] = {
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
  ],

  onload: function (report) {
    report.page.add_inner_button(__("Exportar Excel"), () =>
      _hq_export_excel(report),
    );
  },
};

// El Excel se arma en memoria en el servidor y viaja en base64: no queda
// ningún archivo en el disco del servidor que haya que limpiar después.
function _hq_export_excel(report) {
  const filters = report.get_filter_values();

  if (!filters.company) {
    frappe.throw(__("Seleccione una Compañía para exportar el reporte."));
    return;
  }

  frappe.dom.freeze(HQ_EXPORT_SPINNER);

  frappe.call({
    method:
      "l10n_ve.l10n_ve.report.ve_sales_invoices_hq.excel_export.download_hq_excel",
    args: { filters: JSON.stringify(filters) },
    callback: function (r) {
      frappe.dom.unfreeze();

      if (!r.message || r.message.type !== "download") {
        frappe.msgprint({
          title: __("Error"),
          message: __("No se pudo generar el archivo de Excel."),
          indicator: "red",
        });
        return;
      }

      _hq_download_blob(r.message.filecontent, r.message.filename);
      frappe.show_alert({
        message: __("Excel descargado."),
        indicator: "green",
      });
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
function _hq_download_blob(base64_content, filename) {
  const bytes = Uint8Array.from(atob(base64_content), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}
