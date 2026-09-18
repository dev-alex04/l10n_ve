// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.listview_settings["Sales Invoice"] = {
  has_indicator_for_cancelled: true,
  hide_name_column: true,
  add_fields: [
    "customer",
    "customer_name",
    "base_grand_total",
    "outstanding_amount",
    "due_date",
    "company",
    "currency",
    "is_return",
    "is_debit_note",
    "is_void",
    "bill_no",
    "posting_date",
    "total_withholding",
    "vat_withholding_voucher_number",
    "islr_receipt_number",
    // Lo calcula el servidor mirando la tabla de impuestos, que acá no está.
    "missing_withholding_voucher",
  ],

  get_indicator: function (doc) {
    const result = compute_ve_billing_indicator(doc, {
      doc_type: "sales_invoice",
    });

    if (result) {
      let label = result.label;
      if (result.withholding_warning) label += " ⚠️";
      const filter = doc.is_void ? "is_void,=,1" : "docstatus,=,1";
      return [label, result.color, filter];
    }

    // Estados no-VE (compute retornó null)
    if (doc.docstatus === 2) {
      return [__("Cancelado"), "red", "docstatus,=,2"];
    }
    if (doc.docstatus === 0) {
      return [__("Borrador"), "red", "docstatus,=,0"];
    }
    if (doc.is_return) {
      return [__("Nota de Crédito"), "gray", "is_return,=,1"];
    }
    if (doc.is_debit_note) {
      return [__("Nota de Débito"), "gray", "is_debit_note,=,1"];
    }
  },

  right_column: "grand_total",

  onload: function (listview) {
    if (!listview._branch_filter_patched) {
      listview._branch_filter_patched = true;

      const original_get_filters_for_args = listview.get_filters_for_args;
      listview.get_filters_for_args = function () {
        const filters = original_get_filters_for_args.call(this);

        if (filters && filters.length) {
          filters.forEach((f) => {
            if (Array.isArray(f)) {
              let fieldname, operator_idx, value_idx;

              if (f.length >= 4) {
                fieldname = f[1];
                operator_idx = 2;
                value_idx = 3;
              } else if (f.length >= 3) {
                fieldname = f[0];
                operator_idx = 1;
                value_idx = 2;
              }

              const val = f[value_idx];
              const op = f[operator_idx];

              if (
                (fieldname === "branch" || fieldname === "ve_branch") &&
                typeof val === "string" &&
                val.trim() &&
                ["=", "equals"].includes(op)
              ) {
                f[operator_idx] = "descendants of (inclusive)";
              }
            }
          });
        }

        return filters;
      };
    }

    if (frappe.model.can_create("Delivery Note")) {
      listview.page.add_action_item(__("Delivery Note"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Sales Invoice",
          "Delivery Note",
        );
      });
    }

    if (frappe.model.can_create("Payment Entry")) {
      listview.page.add_action_item(__("Payment"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Sales Invoice",
          "Payment Entry",
        );
      });
    }

    listview.page.add_inner_button(__("Descargar Facturas HKA"), function () {
      let dialog = new frappe.ui.Dialog({
        title: __("Descarga Masiva de Facturas HKA"),
        fields: [
          {
            label: __("Fecha Desde"),
            fieldname: "from_date",
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.add_months(frappe.datetime.get_today(), -1)
          },
          {
            label: __("Fecha Hasta"),
            fieldname: "to_date",
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.get_today()
          },
          {
            label: __("Cliente (Opcional)"),
            fieldname: "customer",
            fieldtype: "Link",
            options: "Customer"
          },
          {
            label: __("Sucursal (Opcional)"),
            fieldname: "branch",
            fieldtype: "Link",
            options: "VE Branch"
          }
        ],
        primary_action_label: __("Iniciar Descarga"),
        primary_action(values) {
          frappe.call({
            method: "l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download.get_invoice_count",
            args: {
              from_date: values.from_date,
              to_date: values.to_date,
              customer: values.customer,
              branch: values.branch
            },
            freeze: true,
            freeze_message: __("Verificando cantidad de facturas..."),
            callback: function (r) {
              const count = r.message || 0;
              if (count === 0) {
                frappe.msgprint({
                  title: __("Sin Facturas"),
                  indicator: "orange",
                  message: __("No se encontraron facturas aprobadas por HKA en el rango seleccionado.")
                });
                return;
              }
              dialog.hide();
              frappe.call({
                method: "frappe.client.insert",
                args: {
                  doc: {
                    doctype: "VE Fiscal Document Download",
                    from_date: values.from_date,
                    to_date: values.to_date,
                    customer: values.customer,
                    branch: values.branch
                  }
                },
                freeze: true,
                freeze_message: __("Creando solicitud de descarga..."),
                callback: function (res_insert) {
                  if (res_insert.message) {
                    const docname = res_insert.message.name;
                    frappe.call({
                      method: "l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download.start_bulk_download",
                      args: {
                        docname: docname
                      },
                      freeze: true,
                      freeze_message: __("Iniciando descarga de PDFs en segundo plano..."),
                      callback: function (res_dl) {
                        frappe.set_route("Form", "VE Fiscal Document Download", docname);
                        frappe.show_alert({
                          message: __("Descarga iniciada en segundo plano."),
                          indicator: "green"
                        });
                      }
                    });
                  }
                }
              });
            }
          });
        }
      });
      dialog.show();
    });



    // Dynamic update of Subject column to use bill_no, while keeping other columns configurable by the user
    const get_df = frappe.meta.get_docfield.bind(null, "Sales Invoice");
    if (listview.columns && listview.columns.length > 0) {
      const subject_col = listview.columns.find(col => col.type === "Subject");
      if (subject_col) {
        subject_col.df = get_df("bill_no") || { label: __("Número de Factura"), fieldname: "bill_no", fieldtype: "Data" };
      }
    }
    listview.render_header(true);

    const original_render = listview.render_list;
    listview.render_list = function () {
      original_render.call(this);

      const invoices_with_withholding = [];
      (this.data || []).forEach((doc) => {
        if (doc.docstatus === 1 && flt(doc.total_withholding) !== 0) {
          invoices_with_withholding.push(doc.name);
        }
      });

      if (!invoices_with_withholding.length) return;

      frappe.xcall(
        "l10n_ve.overrides.sales_invoice.get_withholding_types",
        { invoice_names: JSON.stringify(invoices_with_withholding) }
      ).then((result) => {
        if (!result) return;

        listview.$result.find(".list-row").each(function () {
          const $row = $(this);
          const name = $row.find(".list-row-checkbox").attr("data-name");
          if (!name) return;

          const doc = listview.data.find((d) => d.name === name);
          if (!doc || doc.docstatus !== 1) return;

          const info = result[name];
          const $pills = $row.find(".indicator-pill");

          let should_warn = false;
          if (info) {
            should_warn =
              (info.has_vat && !doc.vat_withholding_voucher_number) ||
              (info.has_islr && !doc.islr_receipt_number);
          }

          $pills.each(function () {
            const $pill = $(this);
            const $target = $pill.find(".ellipsis").length ? $pill.find(".ellipsis") : $pill;
            const text = $target.text();

            if (should_warn) {
              if (!text.includes("⚠️")) {
                $target.text(text.trimEnd() + " ⚠️");
              }
              $pill.attr("title", __("Falta comprobante de retención"));
            } else {
              if (text.includes("⚠️")) {
                $target.text(text.replace(" ⚠️", ""));
              }
              $pill.removeAttr("title");
            }
          });
        });
      });
    };
  },
};
