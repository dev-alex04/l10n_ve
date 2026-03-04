
    // Archivo JS para personalizar la vista de lista de VE Municipality Tax Declaration
    // Más información: https://frappeframework.com/docs/v15/user/en/desk/views/list-view#listviewsettings
    frappe.listview_settings['VE Municipality Tax Declaration'] = {

    add_fields: ["docstatus", "declaration_document"],

    hide_name_column: true,
    has_indicator_for_draft: true,
    has_indicator_for_cancelled: true,
    onload(listview) {
    },
    before_render() {
    },
    get_indicator(doc) {
        const status_map = {
            0: { label: __("Borrador"), color: "gray" },
            1: { label: __("Declarado"), color: "green" },
            2: { label: __("Cancelado"), color: "red" },
        };

        let status = status_map[doc.docstatus].label;
        let indicator = status_map[doc.docstatus].color;

        if (doc.docstatus === 1 && !doc.declaration_document) {
            status = __("Sin adjuntar Declaración");
            indicator = "red";
        }

        const filter = `docstatus,=,${doc.docstatus}`;

        return [status, indicator, filter];
    },

};
