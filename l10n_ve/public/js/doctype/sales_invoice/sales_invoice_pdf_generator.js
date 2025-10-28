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
    <table class="main-header-with-logo-table">
        <tr>
            <td class="header-main-title">
                <strong>{{document_title}}</strong>
                   <div class="company-address"><p><span class="label-bold">Dirección:</span> {{company_primary_address}}</p>
                </div>
            </td>
            <td class="header-logo-container">
                {{company_logo_html}}
                <p><span class="label-bold">RIF:</span> {{company_tax_id}}</p>
            </td>
        </tr>
    </table>

    <table class="main-header-table">
        <tr>
            <td class="invoice-details-col">
                <strong>Datos del documento:</strong>

                 <p><span class="label-bold">{{control_label}} </span> {{control_number}}</p>
                <p><span class="label-bold">{{document_label}} </span> {{document_number}}</p>
                <p><span class="label-bold">Fecha emisión: </span> {{posting_date}}</p>
            </td>

            <td class="customer-details-col">
                <strong>Datos del Cliente:</strong>
                <p><span class="label-bold">Nombre:</span> {{customer_name}}</p>
                <p><span class="label-bold">RIF: </span>{{customer_tax_id}}</p>
                <p><span class="label-bold">Dirección: </span>{{customer_address}}</p>
            </td>
        </tr>
    </table>

    <div class="items-full-width">
        <table class="items-table">
            <thead>
                <tr><th>N°</th><th class="item-description">Producto</th><th class="text-right">Cantidad</th><th class="text-right">Total</th></tr>
            </thead>
            <tbody>{{items_html}}</tbody>
        </table>
    </div>

    <div class="totals-row">
        <table class="totals-section">
            <tr><td class="label">Base imponible:</td><td class="value">{{total}}</td></tr>
            {{igtf_html}}
            <tr><td class="label">Total exento:</td><td class="value">{{total_exempt}}</td></tr>
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
    const [customer_data, company_r, styles_css] =
      await Promise.all([
        frappe.db.get_doc("Customer", frm.doc.customer),
        frappe.db.get_value("Company", frm.doc.company, [
          "company_logo",
          "tax_id",
          "custom_company_primary_address",
          "default_currency",
        ]),
        fetch(
          "/assets/l10n_ve/js/doctype/sales_invoice/invoice_preview.css"
        ).then((res) => res.text()),
      ]);

    let customer_address =
      customer_data.primary_address ||
      frm.doc.address_display ||
      "Dirección no disponible";

    customer_address = cleanCountryName(customer_address);

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

    // 2. Construir fragmentos de HTML
    let items_html = frm.doc.items.map((item, index) => {
        const amount = is_foreign_currency ? item.base_amount : item.amount;
        return `<tr>
                <td>${index + 1}</td>
                <td class="item-description">${item.item_name}</td>
                <td class="text-right">${item.qty}</td>
                <td class="text-right">${format_currency(
                  amount,
                  display_currency
                )}</td>
            </tr>`}
      )
      .join("");

    let taxes_html = (frm.doc.taxes || [])
      .filter(
        (tax) =>
          tax.tax_amount &&
          !tax.charge_type.toLowerCase().includes("withholding")
      )
      .map(
        (tax) => {
            const tax_amount = is_foreign_currency ? tax.base_tax_amount : tax.tax_amount;
            return `<tr>
                    <td class="label">${
                      __(tax.charge_type) || tax.account_head
                    }:</td>
                    <td class="value">${format_currency(
                      tax_amount,
                      display_currency
                    )}</td>
                </tr>`}
      )
      .join("");

    // 2.1. Construir HTML para IGTF si aplica
    let igtf_html = "";
    const base_igtf = doc.base_amount_igtf ?? 0;
    const total_igtf = doc.total_igtf ?? 0;

    if (base_igtf > 0 && total_igtf > 0) {
      igtf_html = `
        <tr>
            <td class="label">${__("Base IGTF")}:</td>
            <td class="value">${format_currency(base_igtf, display_currency)}</td>
        </tr>
        <tr>
            <td class="label">${__("IGTF")}:</td>
            <td class="value">${format_currency(total_igtf, display_currency)}</td>
        </tr>
      `;
    }

    const total_exempt_amount = frm.doc.items.reduce((sum, item) => {
      if (item.vat_exempt) {
        return sum + (is_foreign_currency ? item.base_amount : item.amount);
      }
      return sum;
    }, 0);

    // 3. Rellenar la plantilla
    const context = {
      document_title,
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
      total: format_currency(is_foreign_currency ? frm.doc.base_total : frm.doc.total, display_currency),
      total_exempt: format_currency(total_exempt_amount, display_currency),
      taxes_html,
      igtf_html,
      grand_total: format_currency(is_foreign_currency ? frm.doc.base_grand_total : frm.doc.grand_total, display_currency),
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
                    <style>${styles_css}</style>
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
  return addressText.replace(/Venezuela, Bolivarian Republic of/gi, "Venezuela");
}
