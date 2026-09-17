// Copyright (c) 2026, DominaERP and Contributors
// For license information, please see license.txt

frappe.provide("l10n_ve.unlinked_refunds");

frappe.query_reports["Unlinked Refunds"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Empresa"),
      fieldtype: "Link",
      options: "Company",
      default: frappe.defaults.get_user_default("Company"),
      reqd: 1,
    },
    {
      fieldname: "customer",
      label: __("Cliente"),
      fieldtype: "Link",
      options: "Customer",
    },
  ],

  /**
   * Ensancha la columna del número de fila sin ensanchar la tabla.
   *
   * Esa columna la crea el escritorio: sin ancho declarado y sin poder arrastrarla mientras
   * haya menos de 1.000 filas. Con los anchos de este reporte le quedan 34 px, y desde el
   * décimo caso el número sale cortado («1…»).
   *
   * Los 26 px que le faltan se le quitan a «Acción», que solo lleva un botón y va sobrada.
   * Sumarlos sin más pasa la tabla de 1.383 a 1.399 px sobre 1.383 visibles: aparece una
   * barra de desplazamiento horizontal que además tapa la última fila, o sea que se arregla
   * el número y se rompe algo peor.
   *
   * Va por el gestor de columnas y no por CSS: una regla sobre la celda ensancha el cuerpo
   * pero no el encabezado y los desalinea --medido, 8 px--. Y va en `after_datatable_render`
   * porque cada dibujado rehace la tabla y los anchos vuelven a los suyos.
   *
   * @param {object} datatable - La tabla ya dibujada
   */
  after_datatable_render(datatable) {
    const columns = datatable.columnmanager || datatable.columnManager;
    if (!columns) {
      return;
    }
    const all = datatable.getColumns() || [];
    const index_column = all[0];
    const action_column = all[all.length - 1];
    if (!index_column || !action_column) {
      return;
    }

    const missing = 60 - (index_column.width || 0);
    if (missing <= 0) {
      return;
    }

    index_column.width = 60;
    // El botón mide unos 90 px: 140 es el piso por debajo del cual sí lo apretaría.
    action_column.width = Math.max((action_column.width || 0) - missing, 140);
    columns.setColumnWidth(0);
    columns.setColumnHeaderWidth(0);
    columns.setColumnWidth(all.length - 1);
    columns.setColumnHeaderWidth(all.length - 1);
  },

  formatter(value, row, column, data, default_formatter) {
    // La columna del cliente muestra el nombre, no el identificador de la base.
    if (column.fieldname === "party" && data && data.party_name) {
      return `<a href="/app/customer/${encodeURIComponent(data.party)}">${frappe.utils.escape_html(
        data.party_name
      )}</a>`;
    }
    if (column.fieldname === "action" && data && data.party) {
      if (data.can_fix && data.may_fix) {
        return `<button class="btn btn-xs btn-primary"
          onclick="l10n_ve.unlinked_refunds.fix(${escape(JSON.stringify(data))})">${__("Corregir")}</button>`;
      }
      if (!data.can_fix) {
        return `<span class="text-muted" title="${frappe.utils.escape_html(data.problem || "")}">${__(
          "Necesita revisión"
        )}</span>`;
      }
      return `<span class="text-muted">${__("Lo corrige contabilidad")}</span>`;
    }
    if (column.fieldname === "situation" && data) {
      const color = data.can_fix ? (data.situation === __("Deuda escondida") ? "orange" : "blue") : "gray";
      return `<span class="indicator-pill ${color}">${value}</span>`;
    }
    return default_formatter(value, row, column, data);
  },
};

/**
 * Muestra lo que la corrección va a hacer y, si lo aprueban, la ejecuta.
 *
 * @param {string} datos - La fila del reporte, serializada por el formatter
 */
l10n_ve.unlinked_refunds.fix = function (data) {
  const row = JSON.parse(unescape(data));
  frappe
    .call({
      method: "l10n_ve.overrides.advance_refund_audit.describe",
      args: { company: row.company, party: row.party, advance_account: row.advance_account },
    })
    .then((r) => {
      const plan = r.message || {};
      if (!plan.can_fix) {
        frappe.msgprint({
          title: __("Este caso necesita revisión"),
          message: plan.problem,
          indicator: "orange",
        });
        return;
      }
      frappe.confirm(
        `<p>${__("Sobre la cuenta de {0}:", [frappe.utils.escape_html(row.party_name || row.party)])}</p>
         <ul><li>${plan.lines.map(frappe.utils.escape_html).join("</li><li>")}</li></ul>`,
        () => {
          frappe.call({
            method: "l10n_ve.overrides.advance_refund_audit.fix",
            args: { company: row.company, party: row.party, advance_account: row.advance_account },
            freeze: true,
            freeze_message: __("Corrigiendo..."),
            callback(res) {
              if (!res.message) return;
              frappe.show_alert({
                message: __("Listo. Documentos creados: {0}", [res.message.documents.join(", ")]),
                indicator: "green",
              });
              frappe.query_report.refresh();
            },
          });
        }
      );
    });
};
