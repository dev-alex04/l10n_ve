frappe.listview_settings["ISLR Withholding Voucher"] = {
  hide_name_column: true,
  has_indicator_for_draft: true,
  has_indicator_for_cancelled: true,

  get_indicator: function (doc) {
    if (doc.docstatus === 0) {
      return [__("Borrador"), "grey", "docstatus,=,0"];
    } else if (doc.docstatus === 1) {
      if (doc.is_declared) {
        return [__("Declarado"), "green", "is_declared,=,1"];
      }
      return [__("Validado"), "blue", "docstatus,=,1"];
    } else if (doc.docstatus === 2) {
      return [__("Cancelado"), "red", "docstatus,=,2"];
    }
  },
};
