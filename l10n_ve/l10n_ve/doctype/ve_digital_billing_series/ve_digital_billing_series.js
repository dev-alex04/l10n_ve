// Copyright (c) 2026, Galanet Solution and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Digital Billing Series", {
    refresh(frm) {
        if (frm.doc.range_from && frm.doc.range_to && frm.doc.last_control_number) {
            const used = frm.doc.last_control_number - frm.doc.range_from + 1;
            const total = frm.doc.range_to - frm.doc.range_from + 1;
            const pct = ((used / total) * 100).toFixed(1);
            frm.set_intro(
                __("Uso del rango: {0} / {1} números utilizados ({2}%)", [used, total, pct]),
                frm.doc.status === "Exhausted" ? "red" : (pct > 80 ? "orange" : "blue")
            );
        }
    }
});
