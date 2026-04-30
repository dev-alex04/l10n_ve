/**
 * Helper compartido para renderizar la vista previa fiscal de documentos HKA.
 * Utilizable por VAT Withholding Voucher, ISLR Withholding Voucher y cualquier
 * DocType que tenga un campo `hka_preview` (HTML) y `hka_response` (Long Text).
 *
 * @param {Object} frm - Instancia del formulario Frappe.
 * @param {Object} options - Opciones de configuración.
 * @param {string} options.doctype - DocType del comprobante (ej: "VAT Withholding Voucher").
 * @param {string} [options.title="Comprobante Fiscal Digital"] - Título del panel.
 * @param {string} [options.preview_field="hka_preview"] - Nombre del campo HTML wrapper.
 * @param {string} [options.response_field="hka_response"] - Nombre del campo con la respuesta HKA.
 */
function render_fiscal_preview(frm, options = {}) {
  const {
    doctype,
    title = "Comprobante Fiscal Digital",
    preview_field = "hka_preview",
    response_field = "hka_response",
  } = options;

  const wrapper = frm.fields_dict[preview_field];
  if (!wrapper || frm.is_new()) return;

  const raw = frm.doc[response_field] || "";
  if (!raw || !raw.includes('"urlConsulta"')) {
    wrapper.$wrapper.html("");
    return;
  }

  let hka;
  try {
    const data = JSON.parse(raw);
    const resultado = (data && data.resultado) || {};
    hka = {
      url_consulta: resultado.urlConsulta || "",
      numero_control: resultado.numeroControl || "",
      numero_documento: resultado.numeroDocumento || "",
    };
  } catch (e) {
    wrapper.$wrapper.html("");
    return;
  }

  if (!hka.numero_documento) {
    wrapper.$wrapper.html("");
    return;
  }

  const esc = frappe.utils.escape_html;
  wrapper.$wrapper.html(`
    <div class="fiscal-preview">
      <div class="fiscal-preview__header"
        onclick="this.parentElement.querySelector('.fiscal-preview__body').classList.toggle('fiscal-preview--collapsed')">
        <div class="fiscal-preview__header-left">
          <svg class="fiscal-preview__icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="1" width="14" height="14" rx="2" stroke-width="1.5" fill="none"/>
            <path d="M4 5h8M4 8h6M4 11h4" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
          <span class="fiscal-preview__title">${esc(title)}</span>
        </div>
        <div class="fiscal-preview__header-right">
          ${hka.numero_documento ? `<span class="fiscal-preview__meta">Doc: <strong>${esc(hka.numero_documento)}</strong></span>` : ""}
          ${hka.numero_control ? `<span class="fiscal-preview__meta">Control: <strong>${esc(hka.numero_control)}</strong></span>` : ""}
          ${
            hka.url_consulta
              ? `<a href="${esc(hka.url_consulta)}"
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
          <span>Descargando comprobante fiscal desde TFHKA...</span>
        </div>
      </div>
    </div>
  `);

  frappe.call({
    method: "l10n_ve.digital_invoice.tfhka_client.get_fiscal_invoice_pdf",
    args: { invoice_name: frm.doc.name, doctype: doctype },
    callback: function (r) {
      const body = wrapper.$wrapper.find(".fiscal-preview__body");
      if (!r.message || !r.message.base64) {
        body.html(`
          <div class="fiscal-preview__fallback">
            <p>${r.message ? r.message.error : "No se pudo cargar la vista previa."}</p>
            ${
              hka.url_consulta
                ? `<a href="${esc(hka.url_consulta)}" target="_blank" rel="noopener noreferrer">
                Ver comprobante en el portal de TFHKA →
              </a>`
                : ""
            }
          </div>
        `);
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
      body.html(`
        <div class="fiscal-preview__fallback">
          <p>Error al conectar con TFHKA.</p>
          ${
            hka.url_consulta
              ? `<a href="${esc(hka.url_consulta)}" target="_blank" rel="noopener noreferrer">
              Ver comprobante en el portal de TFHKA →
            </a>`
              : ""
          }
        </div>
      `);
    },
  });
}
