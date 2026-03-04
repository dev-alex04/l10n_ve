
frappe.provide("frappe.widget.widget_factory");
if (frappe.widget.widget_factory.number_card) {
    frappe.widget.widget_factory.number_card.prototype.set_formatted_number = function(df, doc) {
        
        let number = flt(this.number);
        let number_parts = [number.toString(), ""]; 

        if (this.card_doc.currency) {
            this.formatted_number = format_currency(number_parts[0], this.card_doc.currency);
            return;
        } 
        const symbol = number_parts[1] || "";
        
        if (window.convert_old_to_new_number_format) {
             number_parts[0] = window.convert_old_to_new_number_format(number_parts[0]);
        }
        const formatted_number = frappe.format(number_parts[0], df, null, doc);
        
        this.formatted_number =
            ($(formatted_number).text() || formatted_number) + " " + __(symbol);
    };
}
