frappe.listview_settings['VE Conatel Tax Declaration'] = {
    get_indicator: function(doc) {
        if (doc.status === 'Declarado') {
            return [__("Declarado"), "green", "status,=,Declarado"];
        } else if (doc.status === 'Por Declarar') {
            return [__("Por Declarar"), "orange", "status,=,Por Declarar"];
        } else {
            return [__("Por Procesar"), "red", "status,=,Por Procesar"];
        }
    }
};
