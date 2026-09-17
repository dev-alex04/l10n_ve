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
      // El color y la explicación salen de `situation_key`, que es estable, y NO del texto
      // traducido: compararlo contra `__("Deuda escondida")` ataba el color a que la
      // traducción coincidiera carácter por carácter.
      const estilo = {
        hidden_debt: {
          color: "orange",
          // En una sola línea a propósito: partir una cadena traducida con `+` rompe la
          // extracción y semgrep lo marca (frappe-translation-js-splitting).
          ayuda: __("Lo que se le devolvió ya había pagado facturas. El cliente se ve al día, pero debajo hay deuda real. Corregir suelta esa aplicación y la factura vuelve a quedar pendiente."),
        },
        phantom_credit: {
          color: "blue",
          ayuda: __("Tiene disponible un saldo a favor que ya se le devolvió. Todavía no lo gastó. Corregir lo enlaza con su reembolso y deja de estar disponible."),
        },
      }[data.situation_key] || {
        color: "gray",
        // En los de revisión manual la explicación genérica no sirve: cada uno tiene su
        // motivo, y es el que el servidor ya calculó.
        ayuda:
          data.problem ||
          __("El sistema no puede explicar esta diferencia y no ofrece corrección automática."),
      };

      return `<span class="indicator-pill ${estilo.color}" title="${frappe.utils.escape_html(
        estilo.ayuda
      )}" style="cursor: help;">${value}</span>`;
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
