frappe.ui.form.on("Sales Invoice", {
  onload: function (frm) {
    if (frm.is_new()) {
      frm.set_value("bill_no", null);
      frm.set_value("credit_note_no", null);
      frm.set_value("debit_note_no", null);
      frm.set_value("bill_control", null);
    }

    frm.set_df_property("vat_withholding_voucher_number", "read_only", 1);
    frm.set_df_property("withholding_date", "read_only", 1);
    frm.set_df_property("voucher_image", "read_only", 1);

    toggle_document_number_fields(frm);
    toggle_vat_withholding_fields(frm);
  },

  refresh: function (frm) {
    toggle_vat_withholding_fields(frm);
    reorganize_customer_fields(frm);
    print_button_pdf(frm);

    let has_vat_withholding = false;
    if (frm.doc.taxes && frm.doc.taxes.length) {
      has_vat_withholding = frm.doc.taxes.some(tax_row =>
        tax_row.charge_type && tax_row.charge_type.toLowerCase().includes('withholding')
      );
    }

    if (
      !frm.doc.__islocal &&
       has_vat_withholding &&
      !frm.custom_buttons["Cargar Comprobante de Retencion"]
    ) {
      if (frm.doc.customer) {
        frappe.db
          .get_value("Customer", frm.doc.customer, "is_special_taxpayer")
          .then((r) => {
            if (r.message && r.message.is_special_taxpayer) {
              frm.add_custom_button(
                __("Cargar Comprobante de Retencion"),
                () => {
                  const dialog = new frappe.ui.Dialog({
                    title: __("Cargar Comprobante de Pago y Número"),
                    fields: [
                      {
                        label: __("Número de Comprobante"),
                        fieldname: "vat_withholding_voucher_number",
                        fieldtype: "Data",
                        reqd: 0,
                      },
                      {
                        label: __("Fecha de Comprobante"),
                        fieldname: "withholding_date",
                        fieldtype: "Date",
                        reqd: 0,
                      },
                      {
                        label: __("Imagen/PDF del Comprobante"),
                        fieldname: "voucher_image",
                        fieldtype: "Attach",
                        reqd: 0,
                      },
                      {
                        fieldname: "invoice_id",
                        fieldtype: "Data",
                        hidden: 1,
                        default: frm.doc.name,
                      },
                    ],
                    primary_action_label: __("Subir y Guardar"),
                    primary_action: (values) => {
                      const voucher_number =
                        values.vat_withholding_voucher_number;

                      if (!voucher_number) {
                        frappe.msgprint({
                          title: __("Error de Validación"),
                          indicator: "red",
                          message: __(
                            "Debe ingresar el Número de Comprobante."
                          ),
                        });
                        return;
                      }
                      const regex = /^\d{14}$/;
                      if (!regex.test(voucher_number)) {
                        frappe.msgprint({
                          title: __("Error de Formato"),
                          indicator: "red",
                          message: __(
                            "El Número de Comprobante debe tener exactamente 14 " +
                              "caracteres y solo puede contener números."
                          ),
                        });
                        return;
                      }

                      if (!values.withholding_date) {
                        frappe.msgprint({
                          title: __("Error de Validación"),
                          indicator: "red",
                          message: __("Debe ingresar la Fecha de Comprobante."),
                        });
                        return;
                      }
                      frappe.call({
                        method:
                          "l10n_ve.overrides.sales_invoice.upload_voucher_data",
                        args: {
                          docname: frm.doc.name,
                          voucher_number: values.vat_withholding_voucher_number,
                          withholding_date: values.withholding_date,
                          file_url: values.voucher_image,
                        },
                        callback: function (r) {
                          if (r.message && r.message.status === "success") {
                            frappe.msgprint(
                              __(
                                "Comprobante cargado y datos guardados exitosamente."
                              )
                            );
                            frm.reload_doc();
                            dialog.hide();
                          } else if (
                            r.message &&
                            r.message.status === "error"
                          ) {
                            frappe.msgprint(
                              __("Error al guardar: " + r.message.msg),
                              "Error"
                            );
                          }
                        },
                      });
                    },
                  });
                  dialog.show();
                }
              );
            }
          });
      }
    }
  },
  before_save: function(frm) {
    // Itera sobre la tabla hija de ítems
    frm.doc.items.forEach(function(item) {

    });
  },
// ---

  customer: function (frm) {
    toggle_vat_withholding_fields(frm);
    frm.refresh();
  },

  is_return: function (frm) {
    toggle_document_number_fields(frm);
  },

  is_debit_note: function (frm) {
    toggle_document_number_fields(frm);
  },
});

function toggle_document_number_fields(frm) {
  const is_credit_note = frm.doc.is_return;
  const is_debit_note = frm.doc.is_debit_note;

  frm.toggle_display(["bill_no"], !is_credit_note && !is_debit_note);
  frm.toggle_display(["credit_note_no"], is_credit_note);
  frm.toggle_display(["debit_note_no"], is_debit_note);
  frm.toggle_display(
    ["affected_invoice_number"],
    is_debit_note || is_credit_note
  );
  frm.toggle_display(["bill_control"], true);
}

function toggle_vat_withholding_fields(frm) {
  const fields_to_toggle = [
    "vat_withholding_voucher_number",
    "withholding_date",
    "voucher_image",
  ];

  frm.toggle_display(fields_to_toggle, false);

  const has_voucher_data = frm.doc.vat_withholding_voucher_number;

  if (has_voucher_data) {
    frm.toggle_display(fields_to_toggle, true);
    return;
  }

  if (frm.doc.customer) {
    frappe.db
      .get_value("Customer", frm.doc.customer, "is_special_taxpayer")
      .then((r) => {
        if (r.message && r.message.is_special_taxpayer) {
          frm.toggle_display(fields_to_toggle, true);
        }
      });
  }
}
function reorganize_customer_fields(frm) {
  let grand_total_wrapper = frm.get_field("grand_total").$wrapper;

  let total_advance_wrapper = frm.get_field("total_advance").$wrapper;

  let outstanding_amount_wrapper = frm.get_field("outstanding_amount").$wrapper;

  let base_grand_total_wrapper = frm.get_field("base_grand_total").$wrapper;

  grand_total_wrapper.insertBefore(base_grand_total_wrapper);
  total_advance_wrapper.insertBefore(base_grand_total_wrapper);
  outstanding_amount_wrapper.insertBefore(base_grand_total_wrapper);
}

function print_button_pdf(frm) {
  const button_group_label =
    frm.doc.docstatus == 0 ? __("Preview") : __("View");

  // Condición para evitar duplicados si la función refresh se llama varias veces
  if (!frm.custom_buttons["Generar PDF de Factura"]) {
    frm.add_custom_button(
      __("Generar PDF de Factura"),
      () => {
        // Aquí llamamos a la función de generación del preview
        generate_custom_invoice_preview(frm);
      },
      button_group_label
    );
  }
}

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

async function generate_custom_invoice_preview(frm) {
    const doc = frm.doc;

    let document_title = __("FACTURA DE VENTA");
    let control_label = __("Nro. Control:");
    let control_number = doc.bill_control;
    let document_label = __("Nro. Factura:");
    let document_number = doc.bill_no || doc.name;

    if (doc.is_return) {

      document_title = __("NOTA DE CRÉDITO");
      document_label = __("Nro. Nota Crédito:");
      document_number = doc.credit_note_no || doc.name
      || "No. Nota de Crédito no disponible";

    } else if (doc.is_debit_note) {

      document_title = __("NOTA DE DÉBITO");
        document_label = __("Nro. Nota Débito:");
        document_number = doc.debit_note_no|| doc.name
        || "No. Nota de Débito no disponible";
    }

    control_number = control_number || "No. Control no disponible";
    document_number = document_number || "No. Documento no disponible";

    try {
        // 1. Obtener datos del cliente y la compañía en paralelo
        const [customer_data, company_r, template_html, styles_css] = await Promise.all([
            frappe.db.get_doc("Customer", frm.doc.customer),
            frappe.db.get_value("Company", frm.doc.company, ["company_logo", "tax_id", "custom_company_primary_address"]),
            fetch('/assets/l10n_ve/js/doctype/sales_invoice/invoice_preview_template.html').then(res => res.text()),
            fetch('/assets/l10n_ve/js/doctype/sales_invoice/invoice_preview.css').then(res => res.text())
        ]);

        const customer_address = customer_data.primary_address || frm.doc.address_display || "Dirección no disponible";
        const company_logo_url = company_r.message.company_logo ? frappe.urllib.get_full_url(company_r.message.company_logo) : null;
        const company_tax_id = company_r.message.tax_id || "RIF no disponible";
        const company_primary_address = await get_address_text(company_r.message.custom_company_primary_address);

        // 2. Construir fragmentos de HTML
        let items_html = frm.doc.items.map((item, index) =>
            `<tr>
                <td>${index + 1}</td>
                <td class="item-description">${item.item_name}</td>
                <td class="text-right">${item.qty}</td>
                <td class="text-right">${format_currency(item.amount, frm.doc.currency)}</td>
            </tr>`
        ).join('');

        let taxes_html = (frm.doc.taxes || [])
            .filter(tax => tax.tax_amount && !tax.charge_type.toLowerCase().includes('withholding'))
            .map(tax =>
                `<tr>
                    <td class="label">${__(tax.charge_type) || tax.account_head}:</td>
                    <td class="value">${format_currency(tax.tax_amount, frm.doc.currency)}</td>
                </tr>`
            ).join('');

        // 3. Rellenar la plantilla
        const context = {
            document_title,
            company_primary_address,
            company_logo_html: company_logo_url ? `<img src="${company_logo_url}" alt="Logo" class="company-logo">` : "",
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
            total: format_currency(frm.doc.total, frm.doc.currency),
            total_exempt: format_currency(frm.doc.total_exempt, frm.doc.currency),
            taxes_html,
            grand_total: format_currency(frm.doc.grand_total, frm.doc.currency),
            in_words: frm.doc.in_words || "Cálculo pendiente",
            remarks: frm.doc.remarks || "Ninguna"
        };

        let preview_html = template_html.replace(/\{\{([^}]+)\}\}/g, (match, key) => {
            return context[key.trim()] || '';
        });

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

                      pdf.addImage(imgData, "PNG", 0, position, pdfWidth, totalPdfHeight);

                      let heightLeft = totalPdfHeight - pdfHeight;

                      while (heightLeft >= 0) {
                        position = heightLeft - totalPdfHeight;
                        pdf.addPage();
                        pdf.addImage(imgData, "PNG", 0, position, pdfWidth, totalPdfHeight);
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
        frappe.msgprint(__("No se pudo generar la vista previa. Revise la consola para más detalles."));
    }
}

frappe.ui.form.on('Sales Invoice Item', {
    item_code: function(frm, cdt, cdn) {
        var row = frappe.get_doc(cdt, cdn);

        if (row.item_code && !row.vat_exempt) {

            frappe.db.get_value(
                "Item",
                row.item_code,
                "vat_exempt",
                function (value) {
                    if (value.vat_exempt) {
                        frappe.model.set_value(cdt, cdn, "vat_exempt", 1);
                    }
                }
            );
        }
    }
});
