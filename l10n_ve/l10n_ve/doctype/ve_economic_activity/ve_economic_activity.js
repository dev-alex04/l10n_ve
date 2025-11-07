frappe.ui.form.on('VE Economic Activity', {
    setup: function(frm) {
        // El mapa de actividades hardcodeado se ha eliminado.
        // Los datos ahora se obtienen dinámicamente del servidor.
    },

    refresh: function(frm) {
        if (frm.is_new()) {

            frm.set_df_property('group', 'options', []);
            frm.set_df_property('branch', 'options', []);
            frm.refresh_field('group');
            frm.refresh_field('branch');
        } else {

            if (frm.doc.sector) {
                frm.events.sector(frm);
            }
        }
    },

    sector: function(frm) {
        frm.set_value('group', '');
        frm.set_value('branch', '');
        frm.set_df_property('branch', 'options', []);
        frm.refresh_field('branch');

        if (frm.doc.sector) {
            frappe.call({
                method: 'l10n_ve.l10n_ve.doctype.ve_economic_activity.ve_economic_activity.get_economic_activity_options',
                args: {
                    sector: frm.doc.sector
                },
                callback: function(r) {
                    frm.set_df_property('group', 'options', r.message || []);
                    frm.refresh_field('group');
                    // Si estamos cargando un documento existente, dispara el evento de grupo
                    if (!frm.is_new() && frm.doc.group) {
                        frm.events.group(frm);
                    }
                }
            });
        } else {
            frm.set_df_property('group', 'options', []);
            frm.refresh_field('group');
        }
    },

    group: function(frm) {
        frm.set_value('branch', '');

        if (frm.doc.sector && frm.doc.group) {
            frappe.call({
                method: 'l10n_ve.l10n_ve.doctype.ve_economic_activity.ve_economic_activity.get_economic_activity_options',
                args: {
                    sector: frm.doc.sector,
                    group: frm.doc.group
                },
                callback: function(r) {
                    frm.set_df_property('branch', 'options', r.message || []);
                    frm.refresh_field('branch');
                }
            });
        } else {
            frm.set_df_property('branch', 'options', []);
            frm.refresh_field('branch');
        }
    }
});