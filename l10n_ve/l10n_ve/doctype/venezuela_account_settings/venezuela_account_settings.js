// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Venezuela Account Settings", {
  refresh(frm) {
    render_vat_method_help(frm);
  },
  vat_calculation_method(frm) {
    render_vat_method_help(frm);
  },
});

/**
 * Muestra la fórmula y un ejemplo del método de cálculo del IVA seleccionado.
 * @param {object} frm
 */
function render_vat_method_help(frm) {
  const method = frm.doc.vat_calculation_method;
  const box = (formula, ejemplo) => `
    <div style="border: 1px solid var(--border-color); border-radius: var(--border-radius);
                padding: 10px 12px; font-size: 12.5px; line-height: 1.7;">
      <div><b>Fórmula:</b> <code>${formula}</code></div>
      <div><b>Ejemplo:</b> ${ejemplo}</div>
    </div>`;

  let html;
  if (method === "Desde la base imponible") {
    html = box(
      "IVA = Base × 16% &nbsp;·&nbsp; Total = Base + IVA",
      "Base $30,17 → IVA $4,8272 → Total $34,9972 &nbsp;·&nbsp; Bs 22.165,98",
    );
  } else if (method === "Desde el total de la factura") {
    html = box(
      "Base = Total ÷ 1,16 &nbsp;·&nbsp; IVA = Total − Base",
      "Total $35,00 → Base $30,1724 → IVA $4,8276 &nbsp;·&nbsp; Bs 22.167,75 (= 35 × tasa)",
    );
  } else {
    html = `<div class="text-muted" style="padding: 10px 0;">
      Seleccione un método para ver su fórmula y ejemplo.
      Sin método definido, el cálculo de documentos con IVA queda bloqueado.</div>`;
  }

  frm.get_field("vat_calculation_method_help").$wrapper.html(html);
}
