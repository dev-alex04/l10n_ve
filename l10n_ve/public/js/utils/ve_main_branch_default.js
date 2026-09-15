/**
 * Propone la sucursal principal en los documentos nuevos de quien no tiene sucursal asignada.
 *
 * En la práctica son Administrator y los System Manager: un usuario acotado sin sucursal no ve
 * estos documentos, y el que tiene una sola la recibe de `set_ve_branch` al emitir. El mapa
 * {compañía: sucursal principal} llega en el boot (`get_main_branches_for_user`) y está vacío
 * para todos los demás. Es solo el valor inicial del formulario: el usuario lo puede cambiar y
 * el servidor no lo impone, así que lo que crean las integraciones sigue naciendo sin sucursal.
 *
 * Quedan fuera el cobro y las notas: el cobro toma la sucursal de la factura que salda, pero
 * solo si llega vacío (`set_ve_branch`), y las notas copian la de su factura.
 */
(function () {
	var DOCTYPES = [
		"Sales Invoice",
		"Purchase Invoice",
		"Delivery Note",
		"Purchase Receipt",
		"Expense",
		"Expense Report",
	];

	function main_branches() {
		return (frappe.boot && frappe.boot.ve_main_branches) || {};
	}

	function has_branch_field(frm) {
		var field = frm.fields_dict.branch;
		return Boolean(field && field.df.options === "VE Branch");
	}

	function propose_main_branch(frm) {
		if (!frm.is_new() || frm.doc.branch || !has_branch_field(frm)) return;
		var branch = main_branches()[frm.doc.company];
		if (branch) frm.set_value("branch", branch);
	}

	var handlers = {
		onload: propose_main_branch,
		company: function (frm) {
			if (!frm.is_new() || !has_branch_field(frm)) return;
			var branches = main_branches();
			var proposed = Object.values(branches);
			// Sin sucursales principales, que es lo habitual, no se toca el campo.
			if (!proposed.length) return;
			// Solo se reemplaza una sucursal propuesta por este archivo: la elegida a mano se respeta.
			if (frm.doc.branch && proposed.indexOf(frm.doc.branch) === -1) return;
			var next = branches[frm.doc.company] || "";
			if ((frm.doc.branch || "") !== next) frm.set_value("branch", next);
		},
	};

	DOCTYPES.forEach(function (doctype) {
		frappe.ui.form.on(doctype, handlers);
	});
})();
