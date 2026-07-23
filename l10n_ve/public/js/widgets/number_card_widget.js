frappe.provide("frappe.widget.widget_factory");
frappe.provide("frappe.utils");

if (frappe.widget.widget_factory.number_card) {
    frappe.widget.widget_factory.number_card.prototype.set_formatted_number = function(df, doc) {
        let number = flt(this.number);
        let number_parts = [number.toString(), ""];

        if (this.card_doc.currency) {
            this.formatted_number = format_currency(number, this.card_doc.currency);
        } else {
            const symbol = number_parts[1] || "";
            if (window.convert_old_to_new_number_format) {
                 number_parts[0] = window.convert_old_to_new_number_format(number_parts[0]);
            }
            const formatted_number = frappe.format(number_parts[0], df, null, doc);
            this.formatted_number =
                ($(formatted_number).text() || formatted_number) + " " + __(symbol);
        }
    };

    // Extender render_number para mostrar referencia USD precalculada (tasa por transacción)
    const original_render_number = frappe.widget.widget_factory.number_card.prototype.render_number;
    frappe.widget.widget_factory.number_card.prototype.render_number = function() {
        original_render_number.call(this);

        // Leer el total USD precalculado desde bootinfo (inyectado en boot.py)
        let card_refs = frappe.boot.card_usd_refs || {};
        let card_name = this.card_doc.name;
        let ref_data = card_refs[card_name];

        if (ref_data && ref_data.usd_total > 0) {
            let formatted_usd = "REF " + flt(ref_data.usd_total)
                .toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            let formatted_rate = flt(ref_data.avg_rate)
                .toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

            $(this.body).find(".sub-value").remove();
            $(this.body).find(".widget-content").append(
                `<div class="sub-value text-muted" style="font-size: 13px; margin-top: 6px; color: var(--text-light) !important;">${formatted_usd} (Tasa prom: ${formatted_rate})</div>`
            );
        }
    };
}

// Interceptar y formatear los elementos de resumen de reportes y gráficos
if (frappe.utils.build_summary_item) {
    const original_build_summary_item = frappe.utils.build_summary_item;
    frappe.utils.build_summary_item = function(summary) {
        let $item = original_build_summary_item.call(this, summary);

        let rate = frappe.boot.today_exchange_rate || 0.0;
        if (summary && summary.datatype === "Currency" && (summary.currency === "VES" || summary.currency === "VEF") && rate > 0) {
            let usd_val = flt(summary.value) / rate;
            let formatted_usd = format_currency(usd_val, "USD");
            let $val_div = $item.find(".summary-value");
            if ($val_div.length) {
                let current_text = $val_div.text();
                $val_div.text(`${current_text} (${formatted_usd})`);
            }
        }
        return $item;
    };
}

// Interceptar la creación de gráficos para agregar la referencia en dólares a los tooltips
if (frappe.utils.make_chart) {
    const original_make_chart = frappe.utils.make_chart;
    frappe.utils.make_chart = function(wrapper, custom_options) {
        custom_options = custom_options || {};
        let tooltipOptions = custom_options.tooltipOptions || {};
        let original_formatTooltipY = tooltipOptions.formatTooltipY;

        tooltipOptions.formatTooltipY = (value) => {
            let formatted = original_formatTooltipY ? original_formatTooltipY(value) : value;
            let rate = frappe.boot.today_exchange_rate || 0.0;
            if (rate > 0 && typeof value === 'number') {
                let base_currency = frappe.defaults.get_default("currency");
                if (base_currency === "VES" || base_currency === "VEF") {
                    let usd_val = value / rate;
                    let formatted_usd = format_currency(usd_val, "USD");
                    formatted += ` (${formatted_usd})`;
                }
            }
            return formatted;
        };
        custom_options.tooltipOptions = tooltipOptions;
        return original_make_chart.call(this, wrapper, custom_options);
    };
}
