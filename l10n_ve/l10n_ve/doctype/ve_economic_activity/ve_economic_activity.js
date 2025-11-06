frappe.ui.form.on('VE Economic Activity', {
    setup: function(frm) {
        frm.activity_map = {
            "PRIMARIO": {
                "PESCA, AGRIC., GANAD.": [
                    "PESCA, AGRIC., GANAD.",
                    "PESCA Y ACUICULTURA",
                    "AGRICULTURA",
                    "AVICULTURA",
                    "GANADERÍA",
                    "SELVICULTURA, EXTRACCIÓN DE MADERA Y RECOLECCIÓN DE PRODUCTOS"
                ]
            },
            "SECUNDARIO": {
                "MINERÍA": [
                    "EXPLOTACIÓN DE MINAS Y CANTERAS"
                ],
                "MANUFACTURA": [
                    "MANUFACTURA DE ALIMENTOS, BEBIDAS, MADERA, SUSTANCIAS QUÍMICA, FARMACEUTICA, HOGAR, CEMENTO",
                    "TABACO Y DESTILADOS DEL ALCOHOL",
                    "FABRICACIÓN Y REPARACIÓN DE MAQUINARIA Y EQUIPO ELÉCTRICOS"
                ],
                "CONSTRUCCIÓN": [
                    "CONSTRUCCIÓN DE OBRAS",
                    "CONSTRUCCIÓN, REPARACIÓN Y MANTENIMIENTO",
                    "CONSTRUCCIÓN, SERVICIOS Y SUMINISTRO PETROLEROS"
                ]
            },
            "TERCIARIO": {
                "COMERCIO AL POR MAYOR": [
                    "COMERCIO AL POR MAYOR"
                ],
                "COMERCIO AL POR MENOR": [
                    "COMERCIO AL POR MENOR"
                ],
                "SERVICIOS": [
                    "SERVICIOS DE COMIDAS, BEBIDAS Y ESPARCIMIENTO",
                    "HOTELES, HOSTALES, PENSIONES, POSADAS, CAMPAMENTOS Y HOSPEDAJES",
                    "TRANSPORTE DE PASAJEROS Y DE CARGA, TERRESTRE, MARÍTIMO Y AÉREO",
                    "SERVICIO DE ESTÉTICA",
                    "SERVICIOS DE SALUD",
                    "SERVICIOS DOMÉSTICOS Y EMPRESARIAL",
                    "SERVICIO INMOBILIARIO, ADMINISTRADORAS, CEMENTERIO",
                    "TELECOMUNICACIONES",
                    "RADIODIFUSIÓN",
                    "TECNOLOGÍA, FORMACIÓN Y MEDIO DE DIFUSIÓN",
                    "SERVICIO MECÁNICO, DOMÉSTICOS, GAS Y ELECTRICIDAD",
                    "AGENCIAS BANCARIAS, CASAS DE EMPEÑO, SEGUROS",
                    "APARATOS PARA JUEGOS, DISPENSADORAS, PESOS",
                    "ALQUILER Y ARRENDAMIENTO DE OTROS TIPOS DE MAQUINARIAS, EQUIPOS Y BIENES TANGIBLES.",
                    "A.N.C.P."
                ]
            }
        };
    },

    refresh: function(frm) {
        if (frm.is_new()) {
            frm.set_value('sector', '');
            frm.set_df_property('group', 'options', []);
            frm.set_df_property('branch', 'options', []);
            frm.refresh_field('group');
            frm.refresh_field('branch');
        }
    },

    sector: function(frm) {
        frm.set_value('group', '');
        frm.set_value('branch', '');

        if (frm.doc.sector) {
            const groups = Object.keys(frm.activity_map[frm.doc.sector] || {});
            frm.set_df_property('group', 'options', groups);
            frm.refresh_field('group');
        } else {

            frm.set_df_property('group', 'options', []);
            frm.refresh_field('group');
        }

        frm.set_df_property('branch', 'options', []);
        frm.refresh_field('branch');
    },

    group: function(frm) {
        frm.set_value('branch', '');

        if (frm.doc.sector && frm.doc.group) {

            const branches = (frm.activity_map[frm.doc.sector] || {})[frm.doc.group] || [];
            frm.set_df_property('branch', 'options', branches);
            frm.refresh_field('branch');
        } else {
            frm.set_df_property('branch', 'options', []);
            frm.refresh_field('branch');
        }
    }
});