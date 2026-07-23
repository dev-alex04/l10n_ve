/**
 * Módulo centralizado de indicadores fiscales para documentos de venta VE.
 *
 * Consumido por: Sales Invoice, VE Sales Credit Note, VE Sales Debit Note
 * (form views y list views).
 *
 * Registrado en app_include_js para disponibilidad global.
 */

/**
 * Calcula el indicador fiscal para un documento de ventas VE.
 *
 * @param {object} doc - frm.doc (form) o doc (list view)
 * @param {object} [opts] - Configuración por DocType
 * @param {string} [opts.doc_type="sales_invoice"] - "sales_invoice" | "credit_note" | "debit_note"
 * @returns {{ label: string, color: string, withholding_warning: boolean } | null}
 *   null cuando no aplica indicador VE (usar indicador nativo de Frappe).
 */
function compute_ve_billing_indicator(doc, opts) {
  opts = Object.assign({ doc_type: "sales_invoice" }, opts || {});

  // ── Override absoluto: documento anulado ──
  if (doc.is_void) {
    return { label: __("Anulado"), color: "red", withholding_warning: false };
  }

  // No-submitted: delegar a indicador nativo de Frappe
  if (doc.docstatus !== 1) {
    return null;
  }

  // Sales Invoice legacy: NC/ND internas no usan indicador compuesto
  if (opts.doc_type === "sales_invoice") {
    if (doc.is_return || doc.is_debit_note) {
      return null;
    }
  }

  // ── docstatus === 1: calcular indicador por tipo ──
  switch (opts.doc_type) {
    case "credit_note":
      return _credit_note_indicator(doc);
    case "debit_note":
      return _debit_note_indicator(doc);
    default:
      return _sales_invoice_indicator(doc);
  }
}

/**
 * Indicador compuesto para Sales Invoice: {Fiscal} - {Pago}
 * Incluye detección de comprobante de retención faltante.
 */
function _sales_invoice_indicator(doc) {
  const fiscal = doc.bill_no ? __("Emitida") : __("Por Emitir");
  let payment, color;
  const status = doc.status || "";

  if (status === "Paid") {
    payment = __("Pagado");
    color = "green";
  } else if (status === "Credit Note Issued") {
    payment = __("NC Aplicada");
    color = "gray";
  } else if (status === "Debit Note Issued") {
    payment = __("ND Aplicada");
    color = "gray";
  } else if (status.includes("Partly Paid")) {
    payment = __("Parcial");
    color = "yellow";
  } else {
    payment = __("Por Cobrar");
    color = doc.bill_no ? "blue" : "orange";
  }

  // Por Emitir (sin bill_no) → siempre naranja, sin importar estado de pago
  if (!doc.bill_no) {
    color = "orange";
  }

  // Detectar comprobantes de retención faltantes
  let withholding_warning = false;

  if (doc.taxes && doc.taxes.length) {
    // Form view: revisar charge_type directamente en la tabla de impuestos
    const has_vat = doc.taxes.some(
      (t) => t.charge_type === "VAT Withholding" && flt(t.tax_amount) !== 0
    );
    const has_islr = doc.taxes.some(
      (t) => t.charge_type === "ISLR" && flt(t.tax_amount) !== 0
    );
    withholding_warning =
      (has_vat && !doc.vat_withholding_voucher_number) ||
      (has_islr && !doc.islr_receipt_number);
  } else if (flt(doc.total_withholding) !== 0) {
    // List view: sin acceso a taxes, usar heurística con campos del padre
    withholding_warning =
      !doc.vat_withholding_voucher_number && !doc.islr_receipt_number;
  }

  return {
    label: `${fiscal} - ${payment}`,
    color,
    withholding_warning,
  };
}

/**
 * Indicador simple para VE Sales Credit Note: Emitida | Aplicada | Pendiente
 */
function _credit_note_indicator(doc) {
  if (doc.bill_no) {
    return { label: __("Emitida"), color: "blue", withholding_warning: false };
  }
  if (flt(doc.outstanding_amount) === 0) {
    return {
      label: __("Aplicada"),
      color: "green",
      withholding_warning: false,
    };
  }
  return {
    label: __("Pendiente"),
    color: "orange",
    withholding_warning: false,
  };
}

/**
 * Indicador compuesto para VE Sales Debit Note: {Fiscal} - {Pago}
 */
function _debit_note_indicator(doc) {
  const fiscal = doc.bill_no ? __("Emitida") : __("Aplicada");
  let payment, color;

  if (flt(doc.outstanding_amount) === 0) {
    payment = __("Pagado");
    color = "green";
  } else {
    payment = __("Por Cobrar");
    color = doc.bill_no ? "blue" : "orange";
  }

  return {
    label: `${fiscal} - ${payment}`,
    color,
    withholding_warning: false,
  };
}

/**
 * Aplica el indicador VE en un formulario (form view).
 * Usa setTimeout(0) para sobreescribir el indicador nativo de Frappe.
 *
 * @param {object} frm - Instancia del formulario Frappe
 * @param {object} [opts] - Opciones para compute_ve_billing_indicator
 */
function set_ve_form_indicator(frm, opts) {
  const result = compute_ve_billing_indicator(frm.doc, opts);
  if (!result) return;

  let label = result.label;
  let color = result.color;

  // En el formulario, mostrar advertencia de retención como texto legible
  if (result.withholding_warning) {
    label += " · Falta comprobante de retención";
    color = "orange";
  }

  setTimeout(() => {
    frm.page.set_indicator(label, color);
  }, 0);
}
