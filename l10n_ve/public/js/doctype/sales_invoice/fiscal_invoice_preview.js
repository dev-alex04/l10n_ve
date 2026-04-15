/**
 * Componente de vista previa de factura fiscal HKA.
 * Renderiza el PDF descargado desde TFHKA dentro del campo HTML 'sales_invoice_preview'.
 */

/**
 * Extrae los datos HKA del campo remarks de la factura.
 * @param {string} remarks
 * @returns {{ url_consulta: string, numero_control: string, numero_documento: string } | null}
 */
function parse_hka_remarks(remarks) {
  try {
    const data = JSON.parse(remarks);
    const resultado = (data && data.resultado) || {};
    return {
      url_consulta: resultado.urlConsulta || "",
      numero_control: resultado.numeroControl || "",
      numero_documento: resultado.numeroDocumento || "",
    };
  } catch (e) {
    return null;
  }
}

/**
 * Genera el HTML del header con número de documento/control y link externo.
 */
function get_fiscal_preview_header_html(
  numero_documento,
  numero_control,
  url_consulta,
) {
  const esc = frappe.utils.escape_html;
  return `
    <div class="fiscal-preview">
      <div class="fiscal-preview__header"
        onclick="this.parentElement.querySelector('.fiscal-preview__body').classList.toggle('fiscal-preview--collapsed')">
        <div class="fiscal-preview__header-left">
          <svg class="fiscal-preview__icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="1" width="14" height="14" rx="2" stroke-width="1.5" fill="none"/>
            <path d="M4 5h8M4 8h6M4 11h4" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
          <span class="fiscal-preview__title">Factura Fiscal Digital</span>
        </div>
        <div class="fiscal-preview__header-right">
          ${numero_documento ? `<span class="fiscal-preview__meta">Doc: <strong>${esc(numero_documento)}</strong></span>` : ""}
          ${numero_control ? `<span class="fiscal-preview__meta">Control: <strong>${esc(numero_control)}</strong></span>` : ""}
          ${
            url_consulta
              ? `<a href="${esc(url_consulta)}"
              class="fiscal-preview__open-link"
              target="_blank" rel="noopener noreferrer"
              title="Abrir en nueva pestaña"
              onclick="event.stopPropagation();">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M9 6.5v3a1 1 0 01-1 1H2.5a1 1 0 01-1-1V4a1 1 0 011-1H5.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                <path d="M7 1.5h3.5V5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M5 7l5.5-5.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
              </svg>
              Abrir
            </a>`
              : ""
          }
        </div>
      </div>
      <div class="fiscal-preview__body">
        <div class="fiscal-preview__loading">
          <div class="spinner-border text-muted" role="status"></div>
          <span>Descargando factura fiscal desde TFHKA...</span>
        </div>
      </div>
    </div>
  `;
}

/**
 * Genera el HTML de fallback cuando no se puede cargar el PDF.
 */
function get_fiscal_preview_fallback_html(message, url_consulta) {
  return `
    <div class="fiscal-preview__fallback">
      <p>${message}</p>
      ${
        url_consulta
          ? `<a href="${frappe.utils.escape_html(url_consulta)}" target="_blank" rel="noopener noreferrer">
          Ver factura en el portal de TFHKA →
        </a>`
          : ""
      }
    </div>
  `;
}

/**
 * Renderiza la vista previa de la factura fiscal HKA
 * dentro del campo HTML 'sales_invoice_preview'.
 * @param {object} frm
 */
function render_fiscal_invoice_preview(frm) {
  const wrapper = frm.fields_dict.sales_invoice_preview;
  if (!wrapper) return;

  if (!frm.doc.remarks || !frm.doc.remarks.includes('"urlConsulta"')) {
    wrapper.$wrapper.html("");
    return;
  }

  const hka = parse_hka_remarks(frm.doc.remarks);
  if (!hka || !hka.numero_documento) {
    wrapper.$wrapper.html("");
    return;
  }

  wrapper.$wrapper.html(
    get_fiscal_preview_header_html(
      hka.numero_documento,
      hka.numero_control,
      hka.url_consulta,
    ),
  );

  frappe.call({
    method: "l10n_ve.digital_invoice.tfhka_client.get_fiscal_invoice_pdf",
    args: { invoice_name: frm.doc.name },
    callback: function (r) {
      const body = wrapper.$wrapper.find(".fiscal-preview__body");
      if (!r.message || !r.message.base64) {
        body.html(
          get_fiscal_preview_fallback_html(
            "No se pudo cargar la vista previa del PDF.",
            hka.url_consulta,
          ),
        );
        return;
      }

      body.html(`
        <iframe
          src="data:application/pdf;base64,${r.message.base64}"
          style="width: 100%; height: 600px; border: none; display: block;"
        ></iframe>
      `);
    },
    error: function () {
      const body = wrapper.$wrapper.find(".fiscal-preview__body");
      body.html(
        get_fiscal_preview_fallback_html(
          "Error al conectar con TFHKA.",
          hka.url_consulta,
        ),
      );
    },
  });
}
