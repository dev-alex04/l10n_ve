console.log("aquii.");
frappe.provide("erpnext.setup");

frappe.setup.on("before_load", function() {
    if (erpnext.setup.slides_settings) {
        let organization_slide = erpnext.setup.slides_settings.find(slide => slide.name === 'organization');

        if (organization_slide) {
            const field_exists = organization_slide.fields.some(field => field.fieldname === 'tax_id');
            if (field_exists) {
                return;
            }

            const tax_id_field = {
                fieldname: "tax_id",
                label: __("Tax ID"), 
                fieldtype: "Data",
                reqd: 1,
                validate: function(value) {
                    if (!value) return; 

                    const rif_regex = /^[JVEGjveg]\d{8,9}$/;

                    if (!rif_regex.test(value)) {
                       
                        frappe.msgprint(__("El formato del Tax ID (RIF) no es válido. Debe empezar con J, V, E, o G seguido de 8 o 9 dígitos."));
                        return __("Formato de RIF inválido");  
                    }
                }
            };

            const company_abbr_index = organization_slide.fields.findIndex(field => field.fieldname === 'company_abbr');

            if (company_abbr_index !== -1) {
                organization_slide.fields.splice(company_abbr_index + 1, 0, tax_id_field);
            }
        }
    }
});
