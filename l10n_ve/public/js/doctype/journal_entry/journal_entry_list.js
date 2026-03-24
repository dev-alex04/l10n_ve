// Filtros personalizados para la vista de lista de Journal Entry
// Permite filtrar por campos de la tabla hija Journal Entry Account

frappe.listview_settings["Journal Entry"] = $.extend(frappe.listview_settings["Journal Entry"] || {}, {
	onload: function (listview) {
		if (listview._jea_filters_added) return;
		listview._jea_filters_added = true;

		const child_dt = "Journal Entry Account";
		const $wrapper = listview.page.page_form.find(".standard-filter-section");

		const jea_filters = [
			{
				fieldtype: "Select",
				label: __("Tipo de Entidad"),
				fieldname: "party_type",
				options: ["", "Customer", "Supplier", "Employee"],
				condition: "=",
				doctype: child_dt,
			},
			{
				fieldtype: "Data",
				label: __("Tercero"),
				fieldname: "party",
				condition: "like",
				doctype: child_dt,
			},
		];

		jea_filters.forEach((df) => {
			df.onchange = () => listview.filter_area.debounced_refresh_list_view();
			listview.page.add_field(df, $wrapper);
		});
	},
});
