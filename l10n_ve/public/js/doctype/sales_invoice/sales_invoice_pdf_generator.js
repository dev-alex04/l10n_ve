// Funciones de ayuda
function format_currency(value, currency) {
  return frappe.format(value, { fieldtype: "Currency", currency: currency });
}

function formatDate(dateStr) {
  return frappe.datetime.str_to_user(dateStr);
}

async function get_address_text(address_name) {
  if (!address_name) {
    return "Dirección principal no configurada";
  }

  try {
    let address_doc = await frappe.db.get_doc("Address", address_name);
    return address_doc.address_line1 || "Dirección no disponible";
  } catch (e) {
    console.error("Error al obtener el texto de la dirección:", e);
    return "Error al cargar la dirección";
  }
}

const template_html = `
<div class="invoice-box">
    <div class="title-bar">
        <strong>{{document_title}}</strong>
        <span class="rif-info"><span class="label-bold" style="color: white;">RIF:</span> {{company_tax_id}}</span>
    </div>
    <table class="main-header-with-logo-table">
        <tr>
            <td class="company-details-container">
                <p class="company-name">{{company_name}}</p>
                <p class="company-address"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-map-pin"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg> {{company_primary_address}}</p>
            </td>
            <td class="header-logo-container">
                {{company_logo_html}}
            </td>
        </tr>
    </table>

    <table class="main-header-table">
        <tr>
            <td class="invoice-details-col">
                <strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-file-text"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg> Datos del Documento:</strong>
                <p><span class="label-bold">Fecha emisión: </span> {{posting_date}}</p>
                <p><span class="label-bold">{{control_label}} </span> {{control_number}}</p>
                <p><span class="label-bold">{{document_label}} </span> {{document_number}}</p>
            </td>

            <td class="customer-details-col">
                <strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-user"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg> Datos del Cliente:</strong>
                <p><span class="label-bold">Nombre:</span> {{customer_name}}</p>
                <p><span class="label-bold">Identificación: </span>{{customer_tax_id}}</p>
                <p><span class="label-bold">Dirección: </span>{{customer_address}}</p>
            </td>
        </tr>
    </table>

    {{affected_invoice_section_html}}

    <div class="items-box">
        <div class="items-full-width">
            <table class="items-table">
                <thead>
                    <tr><th>N°</th><th class="item-description"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-box"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg> Producto</th><th class="text-right item-qty">Cantidad</th><th class="text-right item-price">Precio Unit.</th><th class="text-right item-discount">Descuento</th><th class="text-right item-total">Total</th></tr>
                </thead>
                <tbody>{{items_html}}</tbody>
            </table>
        </div>
    </div>

    <div class="totals-row">
        <table class="totals-section">
            <tr><td class="label">Base Imponible:</td><td class="value">{{total}}</td></tr>
            {{igtf_html}}
            <tr><td class="label">Total Exento:</td><td class="value">{{total_exempt}}</td></tr>
            <tr><td class="label">Total Descuento:</td><td class="value">{{total_discount}}</td></tr>
            {{taxes_html}}
            <tr class="grand-total">
                <td class="label">Total a Pagar:</td>
                <td class="value">{{grand_total}}</td>
            </tr>
        </table>
    </div>

    <div class="additional-info-section">
        <p><strong>Valor en Letras:</strong> {{in_words}}</p>
        <p style="margin-top: 10px;"><strong>Observaciones:</strong> {{remarks}}</p>
        <p style="margin-top: 20px; font-style: italic;">Sujeto a Retención de IVA e ISLR según corresponda a Contribuyentes Especiales.</p>
    </div>
</div>`;

async function generate_custom_invoice_preview(frm) {
  const doc = frm.doc;

  let document_title = __("FACTURA DE VENTA");
  let control_label = __("Nro. Control:");
  let control_number = doc.bill_control;
  let document_label = __("Nro. Factura:");
  let document_number = doc.bill_no || __("Nro. Factura no disponible");

  if (doc.is_return) {
    document_title = __("NOTA DE CRÉDITO");
    document_label = __("Nro. Nota Crédito:");
    document_number =
      doc.credit_note_no || doc.name || "No. Nota de Crédito no disponible";
  } else if (doc.is_debit_note) {
    document_title = __("NOTA DE DÉBITO");
    document_label = __("Nro. Nota Débito:");
    document_number =
      doc.debit_note_no || doc.name || "No. Nota de Débito no disponible";
  }

  control_number = control_number || "No. Control no disponible";
  document_number = document_number || "No. Documento no disponible";

  try {
    const [customer_data, company_r, styles_css] = await Promise.all([
      frappe.db.get_doc("Customer", frm.doc.customer),
      frappe.db.get_value("Company", frm.doc.company, [
        "company_logo",
        "tax_id",
        "custom_company_primary_address",
        "company_name",
        "default_currency",
      ]),
      fetch(
        `/assets/l10n_ve/js/doctype/sales_invoice/invoice_preview.css?v=${new Date().getTime()}`
      ).then((res) => res.text()),
    ]);

    let customer_address = await get_address_text(
      customer_data.customer_primary_address || doc.customer_address
    );

    const company_currency = company_r.message.default_currency;
    const is_foreign_currency = doc.currency !== company_currency;
    const display_currency = company_currency;
    const in_words_field = is_foreign_currency ? "base_in_words" : "in_words";

    const company_logo_url = company_r.message.company_logo
      ? frappe.urllib.get_full_url(company_r.message.company_logo)
      : null;
    const company_tax_id = company_r.message.tax_id || "RIF no disponible";
    const company_primary_address = await get_address_text(
      company_r.message.custom_company_primary_address
    );
    const company_name =
      company_r.message.company_name || "Nombre no disponible";

    // 2. Construir fragmentos de HTML
    let items_html = frm.doc.items
      .map((item, index) => {
        const amount = is_foreign_currency ? item.base_amount : item.amount;
        const unit_price = item.base_rate;
        const total_line_discount =
          (is_foreign_currency
            ? item.discount_amount * doc.conversion_rate
            : item.discount_amount) * item.qty;
        return `<tr>
                <td>${index + 1}</td>
                <td class="item-description">${item.item_name}</td>
                <td class="text-right item-qty">${item.qty}</td>
                <td class="text-right item-price">${format_currency(
                  unit_price,
                  display_currency
                )}</td>
                <td class="text-right item-discount">${format_currency(
                  total_line_discount,
                  display_currency
                )}</td>
                <td class="text-right item-total">${format_currency(
                  amount,
                  display_currency
                )}</td>
            </tr>`;
      })
      .join("");

    let taxes_html = (frm.doc.taxes || [])
      .filter(
        (tax) =>
          tax.tax_amount &&
          !tax.charge_type.toLowerCase().includes("withholding")
      )
      .map((tax) => {
        const tax_amount = is_foreign_currency
          ? tax.base_tax_amount
          : tax.tax_amount;
        return `<tr>
                    <td class="label">${
                      __(tax.charge_type) || tax.account_head
                    } ${parseInt(tax.rate)}%:</td>
                    <td class="value">${format_currency(
                      tax_amount,
                      display_currency
                    )}</td>
                </tr>`;
      })
      .join("");

    // 2.0.1. Construir HTML para Factura Afectada si aplica
    let affected_invoice_section_html = "";
    if ((doc.is_return || doc.is_debit_note) && doc.return_against) {
      const affected_invoice_data = await frappe.db.get_value(
        "Sales Invoice",
        doc.return_against,
        ["base_grand_total", "posting_date"]
      );
      if (affected_invoice_data && affected_invoice_data.message) {
        const {
          grand_total: affected_grand_total,
          base_grand_total: affected_base_grand_total,
          posting_date: affected_posting_date,
        } = affected_invoice_data.message;
        const affected_invoice_number =
          doc.affected_invoice_number || doc.return_against;

        let affected_cells = `<td><span class="label">${__("Factura Afectada:")}</span><span class="value">${affected_invoice_number}</span></td>` +
                           `<td><span class="label">${__("Fecha de Factura Afectada:")}</span><span class="value">${formatDate(affected_posting_date)}</span></td>` +
                           `<td><span class="label" style="text-align: right;">${__("Monto Afectado:")}</span><span class="value">${format_currency(affected_base_grand_total, display_currency)}</span></td>`;

        affected_invoice_section_html = `<div class="affected-invoice-wrapper">
                                            <table class="affected-invoice-section">
                                                <thead><tr><th colspan="3">Datos del Documento Afectado</th></tr></thead>
                                                <tbody><tr>${affected_cells}</tr></tbody>
                                            </table>
                                         </div>`;
      }
    }

    // 2.1. Construir HTML para IGTF si aplica
    let igtf_html = "";
    const base_igtf = doc.base_amount_igtf ?? 0;
    const total_igtf = doc.total_igtf ?? 0;

    if (base_igtf > 0 && total_igtf > 0) {
      igtf_html = `
        <tr>
            <td class="label">${__("Base IGTF")}:</td>
            <td class="value">${format_currency(
              base_igtf,
              display_currency
            )}</td>
        </tr>
        <tr>
            <td class="label">${__("IGTF")}:</td>
            <td class="value">${format_currency(
              total_igtf,
              display_currency
            )}</td>
        </tr>
      `;
    }

    const total_exempt_amount = frm.doc.items.reduce((sum, item) => {
      if (item.vat_exempt) {
        return sum + (is_foreign_currency ? item.base_amount : item.amount);
      }
      return sum;
    }, 0);

    // Calcular el total de descuentos
    const total_discount_amount = frm.doc.items.reduce((sum, item) => {
      const discount =
        (is_foreign_currency
          ? item.discount_amount * doc.conversion_rate
          : item.discount_amount) * item.qty;
      return sum + (discount || 0);
    }, 0);

    // 3. Rellenar la plantilla
    const context = {
      document_title,
      company_name,
      company_primary_address,
      company_logo_html: company_logo_url
        ? `<img src="${company_logo_url}" alt="Logo" class="company-logo">`
        : "",
      company_tax_id,
      control_label,
      control_number,
      document_label,
      document_number,
      posting_date: formatDate(frm.doc.posting_date),
      customer_name: frm.doc.customer_name || frm.doc.customer,
      customer_tax_id: customer_data.tax_id || "RIF no disponible",
      customer_address,
      items_html,
      total: format_currency(
        is_foreign_currency ? frm.doc.base_total : frm.doc.total,
        display_currency
      ),
      total_discount: format_currency(total_discount_amount, display_currency),
      total_exempt: format_currency(total_exempt_amount, display_currency),
      taxes_html,
      affected_invoice_section_html,
      igtf_html,
      grand_total: format_currency(
        is_foreign_currency ? frm.doc.base_grand_total : frm.doc.grand_total,
        display_currency
      ),
      in_words: frm.doc[in_words_field] || "Cálculo pendiente",
      remarks: frm.doc.remarks || "Ninguna",
    };

    let preview_html = template_html.replace(
      /\{\{([^}]+)\}\}/g,
      (match, key) => {
        return context[key.trim()] || "";
      }
    );

    // 4. Mostrar el diálogo
    const dialog = new frappe.ui.Dialog({
      title: __("Imprimir") + " " + document_title,
      size: "large",
      primary_action_label: __("Descargar PDF"),
      primary_action: () => {
        const iframe = dialog
          .get_field("preview_area")
          .$wrapper.find("iframe")[0];
        if (iframe && iframe.contentWindow) {
          frappe.show_alert({
            message: __("Generando PDF..."),
            indicator: "green",
          });
          const elementToCapture =
            iframe.contentWindow.document.querySelector(".invoice-box");

          iframe.contentWindow
            .html2canvas(elementToCapture, {
              scale: 2,
              useCORS: true,
            })
            .then((canvas) => {
              const imgData = canvas.toDataURL("image/png");

              const pdf = new iframe.contentWindow.jspdf.jsPDF({
                orientation: "portrait",
                unit: "pt",
                format: "a4",
              });

              const pdfWidth = pdf.internal.pageSize.getWidth();
              const pdfHeight = pdf.internal.pageSize.getHeight();
              const imgWidth = canvas.width;
              const imgHeight = canvas.height;
              const ratio = pdfWidth / imgWidth;
              const totalPdfHeight = imgHeight * ratio;
              let position = 0;

              pdf.addImage(
                imgData,
                "PNG",
                0,
                position,
                pdfWidth,
                totalPdfHeight
              );

              let heightLeft = totalPdfHeight - pdfHeight;

              while (heightLeft >= 0) {
                position = heightLeft - totalPdfHeight;
                pdf.addPage();
                pdf.addImage(
                  imgData,
                  "PNG",
                  0,
                  position,
                  pdfWidth,
                  totalPdfHeight
                );
                heightLeft -= pdfHeight;
              }

              pdf.save(`${document_title} - ${frm.doc.name}.pdf`);
              dialog.hide();
            });
        } else {
          console.error("Iframe o su contenido no está listo.");
        }
      },
      fields: [{ fieldname: "preview_area", fieldtype: "HTML" }],
    });

    dialog.show();
    const preview_area = dialog.get_field("preview_area").$wrapper;
    preview_area.html(
      '<iframe style="width: 100%; height: 600px; border: 0;"></iframe>'
    );
    const iframe = preview_area.find("iframe")[0];

    if (iframe) {
      iframe.onload = function () {
        const iframe_doc = iframe.contentWindow.document;
        iframe_doc.open();
        iframe_doc.write(`
                <html>
                  <head>
                    <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
                    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
                    <style>
                        ${styles_css}
                    </style>
                  </head>
                  <body>${preview_html}</body>
                </html>`);
        iframe_doc.close();
      };
    }
  } catch (e) {
    console.error("Error al generar la vista previa de la factura:", e);
    frappe.msgprint(
      __(
        "No se pudo generar la vista previa. Revise la consola para más detalles."
      )
    );
  }
}

function cleanCountryName(addressText) {
  return addressText.replace(
    /Venezuela, Bolivarian Republic of/gi,
    "Venezuela"
  );
}