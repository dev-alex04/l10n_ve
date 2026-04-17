frappe.provide("frappe.treeview_settings");


frappe.treeview_settings["VE Branch"] = {
	get_tree_nodes: "frappe.desk.treeview.get_children",
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("company")
		}
	],
	breadcrumb: "Setup",
	disable_add_node: false,

	onload: function (treeview) {
		treeview.new_node = function () {
			var node = treeview.tree.get_selected_node();

			var parent_val = (node && node.data && node.data.value) ? node.data.value : "";


			frappe.new_doc("VE Branch", {
				parent_ve_branch: parent_val,
				is_group: 0,
				company: (node && node.data && node.data.company) || frappe.defaults.get_user_default("company")
			});
		};
	}
};
