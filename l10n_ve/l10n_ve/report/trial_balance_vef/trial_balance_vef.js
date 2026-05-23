frappe.query_reports["trial_balance_vef"] = {
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
        value = default_formatter(value, row, column, data);

        // Si la fila actual es un grupo (Activo, Pasivo, etc.)
        if (data && data.is_group) {
            // Aplicar negrita a toda la fila
            value = $(`<span>${value}</span>`).css("font-weight", "bold");

            // Si es la columna de nombre de cuenta, le damos un poco de indentación manual si quieres
            if (column.fieldname === "account") {
                $(value).css("color", "var(--text-color)"); // Mantiene el contraste según el tema activo
            }
        }

        // Colorear saldos negativos en rojo (opcional, muy contable)
        if (column.fieldtype === "Currency" && data && data[column.fieldname] < 0) {
            value = $(`<span>${value}</span>`).css("color", "red");
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