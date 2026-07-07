// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Venezuela Account Settings", {
  refresh(frm) {
    render_tax_method_help(frm);
  },
  tax_calculation_method(frm) {
    render_tax_method_help(frm);
  },
});

/**
 * Muestra la fórmula y un ejemplo del método de cálculo de impuestos seleccionado.
 * Los precios siempre se cargan como base imponible: el método solo cambia
 * cómo se deriva el carril fiscal (Bs).
 * @param {object} frm
 */
function render_tax_method_help(frm) {
  const method = frm.doc.tax_calculation_method;

  const pill = (text, accent) => `
    <span style="display:inline-block; padding:3px 10px; border-radius:99px;
                 font-size:12px; white-space:nowrap;
                 background:${accent ? "var(--" + accent + ")" : "var(--control-bg)"};
                 color:${accent ? "#fff" : "var(--text-color)"};
                 font-weight:${accent ? "600" : "normal"};">${text}</span>`;

  const arrow = `<span style="color:var(--text-muted); font-size:13px;">→</span>`;

  const card = ({ accent, titulo, subtitulo, formula, pasos, nota }) => `
    <div style="border:1px solid var(--border-color); border-left:4px solid var(--${accent});
                border-radius:10px; padding:14px 16px; background:var(--card-bg, transparent);">
      <div style="display:flex; align-items:baseline; gap:8px; margin-bottom:10px;">
        <span style="font-weight:600; font-size:13px; color:var(--text-color);">${titulo}</span>
        <span style="font-size:11.5px; color:var(--text-muted);">${subtitulo}</span>
      </div>
      <div style="display:inline-block; font-family:var(--font-family-monospace, monospace);
                  background:var(--control-bg); border:1px solid var(--border-color);
                  border-radius:6px; padding:5px 10px; font-size:12px; margin-bottom:12px;
                  color:var(--text-color);">${formula}</div>
      <div style="display:flex; align-items:center; gap:7px; flex-wrap:wrap; margin-bottom:10px;">
        ${pasos}
      </div>
      <div style="font-size:12px; color:var(--text-muted); border-top:1px dashed var(--border-color);
                  padding-top:8px;">${nota}</div>
    </div>`;

  let html;
  if (method === "Desde la base imponible") {
    html = card({
      accent: "blue-500",
      titulo: "Desde la base imponible",
      subtitulo: "el carril Bs se construye desde la base convertida",
      formula: "Bs: Base × tasa &nbsp;→&nbsp; + IVA 16%",
      pasos: [
        pill("Base $25,86"),
        arrow,
        pill("Base Bs 16.378,80"),
        arrow,
        pill("IVA Bs 2.620,61"),
        arrow,
        pill("Total Bs 18.999,41", "blue-500"),
      ].join(""),
      nota: "USD: 25,86 + 4,14 = <b style='color:var(--text-color);'>30,00</b> (igual en ambos métodos). " +
            "El total Bs puede diferir en céntimos del total comercial × tasa.",
    });
  } else if (method === "Desde el total de la factura") {
    html = card({
      accent: "green-500",
      titulo: "Desde el total de la factura",
      subtitulo: "el carril Bs se ancla al total comercial × tasa",
      formula: "Bs: Total × tasa &nbsp;→&nbsp; − IVA (÷ 1,16)",
      pasos: [
        pill("Total $30,00"),
        arrow,
        pill("Total Bs 19.000,93", "green-500"),
        arrow,
        pill("Base Bs 16.380,11"),
        arrow,
        pill("IVA Bs 2.620,82"),
      ].join(""),
      nota: "USD: 25,86 + 4,14 = <b style='color:var(--text-color);'>30,00</b> (igual en ambos métodos). " +
            "Total Bs = total comercial × tasa <b>exacto</b>; IVA = 16,0000% de la base Bs. " +
            "Los precios y plantillas <b>no cambian</b>.",
    });
  } else {
    html = `
      <div style="border:1px dashed var(--border-color); border-radius:10px; padding:16px;
                  text-align:center; color:var(--text-muted); font-size:12.5px;">
        Seleccione un método para ver su fórmula y ejemplo.<br>
        <span style="font-size:11.5px;">Sin método definido, el cálculo de documentos
        con impuestos queda bloqueado.</span>
      </div>`;
  }

  frm.get_field("tax_calculation_method_help").$wrapper.html(html);
}
