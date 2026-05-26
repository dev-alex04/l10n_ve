frappe.query_reports["trial balance VEF"] = {
    "filters": [
        {
            "fieldname": "company",
            "label": __("Empresa"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("company"),
            "reqd": 1
        },
        {
            "fieldname": "from_date",
            "label": __("Desde"),
            "fieldtype": "Date",
            "default": frappe.datetime.month_start(),
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": __("Hasta"),
            "fieldtype": "Date",
            "default": frappe.datetime.month_end(),
            "reqd": 1
        },
        {
            "fieldname": "show_zero_values",
            "label": __("Mostrar cuentas en cero"),
            "fieldtype": "Check",
            "default": 0
        }
    ],

    "formatter": function (value, row, column, data, default_formatter) {
        if (!data) return default_formatter(value, row, column, data);

        // Si es una fila de cabecera de grupo, ocultamos los valores numéricos
        if (data.is_header && column.fieldname !== "account") {
            return "";
        }

        value = default_formatter(value, row, column, data);

        let is_group = data.is_group;
        let is_negative = column.fieldtype === "Currency" && data[column.fieldname] < 0;

        // Estilos para la columna de cuenta
        if (column.fieldname === "account") {
            let text = "";

            if (data.is_header) {
                let num = data.account_number ? `<span style="display: inline-block; width: 80px; font-weight: bold;">${data.account_number}</span>` : "";
                text = `${num}<span style="font-weight: bold;">${data.account_name}</span>`;
                value = `<span>${text}</span>`;
            } else if (data.is_total) {
                text = `<span style="font-weight: bold; margin-left: 80px;">${data.account_name}</span>`;
                value = `<span>${text}</span>`;
            } else {
                let num = data.account_number ? `<span style="display: inline-block; width: 80px;">${data.account_number}</span>` : "";
                text = `${num}<span>${data.account_name}</span>`;
                value = `<span>${text}</span>`;
            }
        }

        // Si la fila actual es un grupo (cabecera o total)
        if (is_group) {
            value = `<span style="font-weight: bold;">${value}</span>`;
        }

        // Colorear saldos negativos en rojo
        if (is_negative) {
            value = `<span style="color: red;">${value}</span>`;
        }

        return value;
    },

    "onload": function (report) {
        // Acción adicional: Botón para colapsar/expandir grupos si el reporte es muy largo
        report.page.add_inner_button(__("Expandir Todo"), function () {
            report.tree_grid.expand_all();
        });
    }
};