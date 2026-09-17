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

  formatter(value, row, column, data, default_formatter) {
    // La columna del cliente muestra el nombre, no el identificador de la base.
    if (column.fieldname === "party" && data && data.party_name) {
      return `<a href="/app/customer/${encodeURIComponent(data.party)}">${frappe.utils.escape_html(
        data.party_name
      )}</a>`;
    }
    if (column.fieldname === "action" && data && data.party) {
      if (data.can_fix && data.may_fix) {
        // Los cuatro datos van como argumentos entrecomillados, uno por uno. La versión
        // anterior serializaba la fila entera y la insertaba SIN comillas, así que el
        // `onclick` quedaba `fix(%7B%22party%22...)` y el navegador ni siquiera lo parseaba:
        // SyntaxError, el botón no hacía nada y no se veía ningún error en pantalla.
        // `encodeURIComponent` NO codifica la comilla simple, y el atributo la usa para
        // delimitar: sin este reemplazo, un cliente como O'BRIEN C.A. vuelve a romper el
        // botón exactamente igual que antes.
        const arg = (v) =>
          encodeURIComponent(v == null ? "" : String(v)).replace(/'/g, "%27");
        return `<button class="btn btn-xs btn-primary" onclick="l10n_ve.unlinked_refunds.fix(
          '${arg(data.company)}', '${arg(data.party)}', '${arg(data.advance_account)}',
          '${arg(data.party_name)}')">${__("Corregir")}</button>`;
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
 * Recibe los datos sueltos y ya codificados por el formatter, no la fila serializada: así el
 * `onclick` es JavaScript válido aunque el nombre del cliente traiga comillas o acentos.
 *
 * @param {string} company - Empresa, codificada con encodeURIComponent
 * @param {string} party - Identificador del cliente, codificado
 * @param {string} advanceAccount - Cuenta de anticipos, codificada
 * @param {string} partyName - Nombre visible del cliente, codificado
 */
l10n_ve.unlinked_refunds.fix = function (company, party, advanceAccount, partyName) {
  const row = {
    company: decodeURIComponent(company),
    party: decodeURIComponent(party),
    advance_account: decodeURIComponent(advanceAccount),
    party_name: decodeURIComponent(partyName || ""),
  };
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
