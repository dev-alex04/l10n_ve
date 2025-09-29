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

    if (
      !frm.doc.__islocal &&
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
                            "El Número de Comprobante debe tener exactamente 14" +
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
                            frm.reload_doc(); // Recargar el formulario
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
        // CAMBIO: Usamos frappe.db.get_doc para obtener el documento completo.
        // Esto asegura que campos calculados como address_html estén presentes.
        let address_doc = await frappe.db.get_doc("Address", address_name);

        // Retornamos directamente el address_html del documento.
        return address_doc.address_line1 || "Dirección no disponible";
    } catch (e) {
        console.error("Error al obtener el texto de la dirección:", e);
        return "Error al cargar la dirección";
    }
}
function generate_custom_invoice_preview(frm) {
  frappe.call({
    method: "frappe.client.get",
    args: {
      doctype: "Customer",
      name: frm.doc.customer,
    },
    callback: function (r) {
      if (!r.message) {
        frappe.msgprint("No se pudo encontrar al cliente.");
        return;
      }
      const customer_data = r.message;
      const customer_address =
        customer_data.primary_address||
        frm.doc.address_display ||
        "Dirección no disponible";

      frappe.db
        .get_value("Company", frm.doc.company, [
          "company_logo",
          "tax_id",
          "custom_company_primary_address",
        ])
        .then(async (company_r) => {
          const company_logo_url = company_r.message.company_logo
            ? frappe.urllib.get_full_url(company_r.message.company_logo)
            : null;
          const company_tax_id =
            company_r.message.tax_id || "RIF no disponible";
          const address_name = company_r.message.custom_company_primary_address;

          const company_primary_address = await get_address_text(address_name);


          let items_html = "";
          frm.doc.items.forEach((item, index) => {
            items_html += `<tr><td>${
              index + 1
            }</td><td class="item-description">${
              item.item_name
            }</td><td class="text-right">${
              item.qty
            }</td><td class="text-right">${format_currency(
              item.amount,
              frm.doc.currency
            )}</td></tr>`;
          });


let taxes_html = "";
if (frm.doc.taxes && frm.doc.taxes.length) {
    frm.doc.taxes.forEach((tax) => {

        // 1. Condición de exclusión
        // Usamos tax.charge_type y comprobamos si incluye "Retención"
        // Asegúrate de que el valor exacto para Retención sea correcto en tu sistema (ej: "Withholding Tax" si está en inglés).
        const is_retention = tax.charge_type && tax.charge_type.toLowerCase().includes('withholding');

        // 2. Comprobamos si tiene monto Y NO es retención
        if (tax.tax_amount && !is_retention) {

            // Genera el HTML para el impuesto
            taxes_html += `<tr><td class="label">${
                // Usa tax.charge_type para la etiqueta, con la traducción __()
                __(tax.charge_type) || tax.account_head
            }:</td><td class="value">${format_currency(
                tax.tax_amount,
                frm.doc.currency
            )}</td></tr>`;
        }
    });
}
          const preview_html = `
        <div class="invoice-box">
            <table class="main-header-with-logo-table">
                <tr>
                  <td class="header-main-title">
                      <strong>FACTURA DE VENTA</strong>
                      <div class="company-address">  <p><span class="label-bold">Dirección:</span> ${
                              company_primary_address || "Dirección no disponible"
                          }</p>
                      </div>
                  </td>
                    <td class="header-logo-container">
                        ${
                          company_logo_url
                            ? `<img src="${company_logo_url}" alt="Logo" class="company-logo">`
                            : ""
                        }
                         <p><span class="label-bold">RIF:</span> ${
                               company_tax_id|| "Dirección no disponible"
                          }</p>
                    </td>
                </tr>
            </table>

            <table class="main-header-table">
                <tr>
                    <td class="invoice-details-col">
                     <strong>Datos de la factura:</strong>

                        <p><span class="label-bold">Nro.Control: </span>  ${
                          frm.doc.bill_no || "No.Control no disponible"
                        }</p>
                        <p><span class="label-bold">Nro.Factura: </span> ${
                          frm.doc.bill_control || "No.Factura no disponible"
                        }</p>
                        <p><span class="label-bold">Fecha emisión: </span> ${frappe.datetime.str_to_user(
                          frm.doc.posting_date
                        )}</p>

                    </td>

                    <td class="customer-details-col">
                        <strong>Datos del Cliente:</strong>
                        <p><span class="label-bold">Nombre:</span> ${
                          frm.doc.customer_name || frm.doc.customer
                        }</p>
                        <p><span class="label-bold">RIF: </span>${
                          customer_data.tax_id || "RIF no disponible"
                        }</p>
                        <p><span class="label-bold">Dirección: </span>${customer_address}</p>
                    </td>
                </tr>
            </table>

            <div class="items-full-width">
                <table class="items-table">
                    <thead>
                        <tr><th>N°</th><th class="item-description">Producto</th><th class="text-right">Cantidad</th><th class="text-right">Total</th></tr>
                    </thead>
                    <tbody>${items_html}</tbody>
                </table>
            </div>

            <div class="totals-row">
                <table class="totals-section">

                     <tr><td class="label">Base imponible:</td><td class="value">${format_currency(
                      frm.doc.total,
                      frm.doc.currency
                    )}</td></tr>
                    <tr><td class="label">Total exento:</td><td class="value">${format_currency(
                      frm.doc.total_exempt,
                      frm.doc.currency
                    )}</td></tr>

                     ${taxes_html}

                     <tr class="grand-total"><td class="label">Total a Pagar:</td><td class="value">${format_currency(
                      frm.doc.grand_total,
                      frm.doc.currency
                    )}</td></tr>
                </table>
            </div>

            <div class="additional-info-section">
                <p><strong>Valor en Letras:</strong> ${
                  frm.doc.in_words || "Cálculo pendiente"
                }</p>
                <p style="margin-top: 10px;"><strong>Observaciones:</strong> ${
                  frm.doc.remarks || "Ninguna"
                }</p>
                <p style="margin-top: 20px; font-style: italic;">Sujeto a Retención de IVA e ISLR según corresponda a Contribuyentes Especiales.</p>
            </div>
        </div>`;

          // 2. Configuración del Diálogo y Generación del PDF
          const dialog = new frappe.ui.Dialog({
            title: __("Imprimir Factura de Venta"),
            size: "large",
            primary_action_label: __("Descargar PDF"),
            primary_action: () => {
              const iframe = dialog
                .get_field("preview_area")
                .$wrapper.find("iframe")[0];
              if (iframe && iframe.contentWindow) {
                frappe.show_alert({
                  message: "Generando PDF...",
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

                    pdf.save(`Factura - ${frm.doc.name}.pdf`);
                    dialog.hide();
                  });
// ...
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
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

        /* === Colores DESIGNET === */
        :root {
            --color-primary: #1D87E6; /* Azul Cian/Brillante para acentos y líneas */
            --color-secondary: #1E3B7D; /* Azul Oscuro/Marino para texto importante y fondos de bloques */
            --color-text: #333;
            --color-light-background: #E8F4FF; /* Fondo sutil para filas alternas */
            --color-accent-text: #ffffff; /* Texto blanco para fondos oscuros */
        }

        /* === Estilos Base === */
        body {
            font-family: 'Inter', sans-serif;
            font-size: 9pt;
            color: var(--color-text);
        }
        .invoice-box {
            max-width: 800px;
            margin: auto;
            padding: 25px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }

        /* === 1. Encabezado Principal (Título, Logo y Datos de la Empresa) === */
        .main-header-with-logo-table {
            margin-bottom: 5px;
            /* Borde inferior profesional en Azul Marino */
            border-bottom: 4px solid var(--color-secondary);
            padding-bottom: 5px;
        }
        .main-header-with-logo-table td {
   vertical-align: top;
    vertical-align: bottom;
    padding: 0;
}
        .header-main-title {
    width: 50%;
    text-align: left;
    /* vertical-align: middle; <--- ANTES */
    vertical-align: bottom; /* **AHORA:** Lo pegamos a la parte inferior de la fila */
    padding-left: 0;
}
        .header-main-title strong {
            font-size: 1.8em;
            font-weight: 800;
            /* Título en el color de acento (Azul Cian) */
            color: var(--color-text);
            display: block;
            padding: 0;
            margin: 0;
        }
        /* --- EN LA CELDA DEL LOGO/EMPRESA --- */
.header-logo-container {
    width: 50%;
    text-align: right;
    padding-right: 0;
}
.company-logo {
    /* **AJUSTE CLAVE:** Más ancho que alto para logos horizontales */
    max-width: 150px; /* Aumentamos el ancho, es el límite principal */
    max-height: 200px; /* Reducimos la altura, para que no empuje el contenido verticalmente */
    display: inline-block;
    margin-bottom: 5px;
    margin-right: 30px; /* Margen para separarlo del borde derecho */
}
.company-address {
    margin-top: 5px;
    line-height: 1.2;
    /* clear: both; <--- LO ELIMINAMOS para que el texto se alinee al bottom del TD */
    padding-right: 15px;
}
        .company-address p {
            font-size: 0.8em;
            margin: 0 !important;
            line-height: 1.3;
            text-align: right;
        }
        .label-bold {
            font-weight: 700;
            /* Etiquetas importantes en Azul Oscuro/Marino */
            color: var(--color-secondary);
        }


        /* === 2. Bloque de Información (Factura y Cliente) === */
        .main-header-table {
            margin-top: 20px;
            margin-bottom: 25px;
        }
        .main-header-table td {
            width: 50%;
            padding: 0;
            vertical-align: top;
            line-height: 1.5;
            border: none;
            background-color: transparent;
        }
        .main-header-table strong {
            display: block;
            font-size: 10pt;
            font-weight: 700;
            padding: 5px 15px;
            margin-bottom: 8px;

            /* Bloque sólido de color de marca */
            background-color: var(--color-secondary);
            color: var(--color-accent-text);
        }
        .main-header-table p {
            margin: 0 !important;
            line-height: 1.4;
            margin-bottom: 3px !important;
            padding: 0 15px;
        }
        .customer-details-col {
            padding-left: 10px;
        }
        .invoice-details-col {
            padding-right: 10px;
        }


        /* === 3. TABLA DE ITEMS === */
        .items-full-width {
            margin-top: 20px;
            margin-bottom: 30px;
            /* Borde exterior para contener la tabla */
            border: 1px solid #ddd;
        }
        .items-table {
            font-size: 9pt;
        }
        .items-table th {
            /* Fondo sutil de la marca */
            background-color: var(--color-light-background);
            color: var(--color-secondary);
            /* Borde de separación fuerte en Azul Cian */
            border-bottom: 2px solid var(--color-primary);
            font-weight: 700;
            padding: 8px 10px;
            text-transform: uppercase;
            text-align: left;
        }
        .items-table td {
            /* Borde de fila muy sutil */
            border-bottom: 1px solid #eee;
            padding: 7px 10px;
        }
        .items-table .text-right { text-align: right; }
        .items-table .item-description { width: 45%; }


        /* === 4. Totales === */
        .totals-row {
            width: 45%;
            float: right;
            clear: both;
            /* Enmarcamos la columna de totales */
            border-left: 1px solid #ddd;
            padding-left: 10px;
        }
        .totals-section td {
            width: 50%;
            padding: 4px 0;
            border-bottom: 1px solid #eee;
        }
        .totals-section .label {
            font-weight: 600;
            color: var(--color-text);
            padding-right: 10px;
        }
        .totals-section .value {
            text-align: right;
            font-weight: 700;
            color: var(--color-secondary);
        }
        .totals-section .grand-total {

            background-color: #f9f9f9;

            border-top: nose;
            border-bottom: nose;
        }
        .totals-section .grand-total .label, .totals-section .grand-total .value {
            font-size: 1.1em;
            font-weight: 800;
            /* Texto blanco para contraste fuerte */
              color: var(--color-secondary);

        }

        /* === 5. Información Adicional / Pie de Página === */
        .additional-info-section {
            clear: both;
            margin-top: 35px;
            /* Borde de cierre de marca en Azul Cian */
            border-top: 4px solid var(--color-primary);
            padding-top: 15px;
            font-size: 0.9em;
        }
    </style>
                      </head>
                      <body>${preview_html}</body>
                  </html>`);
              iframe_doc.close();
            };
          }
        });
    },
  });
}
