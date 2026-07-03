// -*- coding: utf-8 -*-
// Form script for Reporte Gerencial Single DocType

frappe.ui.form.on('Reporte Gerencial', {
    onload: function(frm) {
        // Override dirty function to prevent document from ever being marked as modified
        frm.dirty = function(is_dirty) {
            this.doc.__unsaved = 0;
            if (this.page && typeof this.page.clear_indicator === 'function') {
                this.page.clear_indicator();
            }
        };

        // Redirect to standard Single DocType route if opened as a generic new document
        if (frm.is_new() && frm.doc.name !== 'Reporte Gerencial') {
            frappe.set_route('Form', 'Reporte Gerencial', 'Reporte Gerencial');
            return;
        }

        // Set default dates if empty without dirtying the document
        let changed = false;
        if (!frm.doc.from_date) {
            frm.doc.from_date = frappe.datetime.month_start();
            changed = true;
        }
        if (!frm.doc.to_date) {
            frm.doc.to_date = frappe.datetime.get_today();
            changed = true;
        }
        // Set default company
        if (!frm.doc.company) {
            frm.doc.company = frappe.defaults.get_user_default('company');
            changed = true;
        }
        // Always clear branch, cost center and customer filters on initial page load to show consolidated data
        if (frm.doc.branch) {
            frm.doc.branch = '';
            changed = true;
        }
        if (frm.doc.cost_center) {
            frm.doc.cost_center = '';
            changed = true;
        }
        if (frm.doc.customer) {
            frm.doc.customer = '';
            changed = true;
        }
        if (changed) {
            frm.refresh_fields();
            frm.dirty(false);
        }

        frm.set_query("customer", function() {
            return {
                query: "l10n_ve.l10n_ve.doctype.reporte_gerencial.reporte_gerencial.get_customer_list",
                params: {
                    filters: {
                        company: frm.doc.company
                    }
                }
            };
        });
    },

    refresh: function(frm) {
        // Prevent editing and clear standard save button completely
        frm.disable_save();
        frm.page.clear_primary_action();
        frm.page.clear_menu();
        
        // Hide primary button if present
        if (frm.page.btn_primary) {
            frm.page.btn_primary.hide();
        }
        
        // Ensure form is not marked as modified
        frm.dirty(false);
        
        // Add reload button in toolbar
        frm.page.set_primary_action('Actualizar', () => {
            frm.trigger('render_dashboard');
        }, 'fa fa-refresh');

        // Add download buttons in inner toolbar
        frm.page.add_inner_button('Descargar PDF', () => {
            if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
                frappe.msgprint('Por favor seleccione Empresa, Fecha Inicio y Fecha Fin.');
                return;
            }
            const url = frappe.urllib.get_full_url(
                `/api/method/l10n_ve.l10n_ve.doctype.reporte_gerencial.reporte_gerencial.download_pdf?company=${encodeURIComponent(frm.doc.company)}&from_date=${encodeURIComponent(frm.doc.from_date)}&to_date=${encodeURIComponent(frm.doc.to_date)}&branch=${encodeURIComponent(frm.doc.branch || '')}&cost_center=${encodeURIComponent(frm.doc.cost_center || '')}&customer=${encodeURIComponent(frm.doc.customer || '')}`
            );
            window.open(url);
        });

        frm.page.add_inner_button('Descargar Excel', () => {
            if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
                frappe.msgprint('Por favor seleccione Empresa, Fecha Inicio y Fecha Fin.');
                return;
            }
            const url = frappe.urllib.get_full_url(
                `/api/method/l10n_ve.l10n_ve.doctype.reporte_gerencial.reporte_gerencial.download_excel?company=${encodeURIComponent(frm.doc.company)}&from_date=${encodeURIComponent(frm.doc.from_date)}&to_date=${encodeURIComponent(frm.doc.to_date)}&branch=${encodeURIComponent(frm.doc.branch || '')}&cost_center=${encodeURIComponent(frm.doc.cost_center || '')}&customer=${encodeURIComponent(frm.doc.customer || '')}`
            );
            window.open(url);
        });

        // Render initial view
        frm.trigger('render_dashboard');
    },

    company: function(frm) {
        if (frm.fields_dict.dashboard_html && frm.fields_dict.dashboard_html.$wrapper) {
            frm.trigger('render_dashboard');
        }
    },

    from_date: function(frm) {
        if (frm.fields_dict.dashboard_html && frm.fields_dict.dashboard_html.$wrapper) {
            frm.trigger('render_dashboard');
        }
    },

    to_date: function(frm) {
        if (frm.fields_dict.dashboard_html && frm.fields_dict.dashboard_html.$wrapper) {
            frm.trigger('render_dashboard');
        }
    },

    branch: function(frm) {
        if (frm.fields_dict.dashboard_html && frm.fields_dict.dashboard_html.$wrapper) {
            frm.trigger('render_dashboard');
        }
    },

    cost_center: function(frm) {
        if (frm.fields_dict.dashboard_html && frm.fields_dict.dashboard_html.$wrapper) {
            frm.trigger('render_dashboard');
        }
    },

    customer: function(frm) {
        if (frm.fields_dict.dashboard_html && frm.fields_dict.dashboard_html.$wrapper) {
            frm.trigger('render_dashboard');
        }
    },

    render_dashboard: function(frm) {
        if (!frm.fields_dict.dashboard_html) {
            return;
        }

        if (!frm.fields_dict.dashboard_html.$wrapper) {
            if (!frm.render_retry_count) {
                frm.render_retry_count = 0;
            }
            if (frm.render_retry_count < 10) {
                frm.render_retry_count++;
                setTimeout(() => {
                    frm.trigger('render_dashboard');
                }, 100);
            }
            return;
        }
        frm.render_retry_count = 0; // Reset count on success

        if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
            frm.fields_dict.dashboard_html.$wrapper.html(`
                <div style="padding: 40px; text-align: center; color: var(--text-muted); font-size: 14px;">
                    <i class="fa fa-info-circle fa-2x" style="margin-bottom: 10px;"></i>
                    <p>Por favor seleccione los filtros obligatorios (Empresa, Fecha Inicio y Fecha Fin) para mostrar el panel.</p>
                </div>
            `);
            return;
        }

        // Validación: fecha inicio no puede ser posterior a fecha fin
        if (frm.doc.from_date > frm.doc.to_date) {
            frm.fields_dict.dashboard_html.$wrapper.html(`
                <div style="padding: 40px; text-align: center; color: var(--red-500); font-size: 14px;">
                    <i class="fa fa-exclamation-triangle fa-2x" style="margin-bottom: 10px;"></i>
                    <p>Error: La Fecha de Inicio no puede ser posterior a la Fecha Fin.</p>
                </div>
            `);
            frappe.msgprint({
                title: 'Rango de Fechas Inválido',
                indicator: 'red',
                message: 'La Fecha de Inicio no puede ser posterior a la Fecha Fin.'
            });
            return;
        }

        // Show spinner
        frm.fields_dict.dashboard_html.$wrapper.html(`
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 250px; padding: 40px;">
                <div class="frappe-spinner" style="width: 40px; height: 40px; border: 3px solid var(--border-color); border-top-color: var(--primary-color); border-radius: 50%; animation: spin 1s linear infinite;"></div>
                <p style="margin-top: 15px; color: var(--text-muted); font-size: 13px;">Cargando estadísticas gerenciales...</p>
                <style>
                    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                </style>
            </div>
        `);

        // Fetch data
        frappe.call({
            method: 'l10n_ve.l10n_ve.doctype.reporte_gerencial.reporte_gerencial.get_dashboard_data',
            args: {
                company: frm.doc.company,
                from_date: frm.doc.from_date,
                to_date: frm.doc.to_date,
                branch: frm.doc.branch || null,
                cost_center: frm.doc.cost_center || null,
                customer: frm.doc.customer || null
            },
            callback: function(r) {
                if (r.message) {
                    render_premium_dashboard(frm, r.message);
                    setTimeout(() => {
                        frm.dirty(false);
                    }, 100);
                } else {
                    frm.fields_dict.dashboard_html.$wrapper.html(`
                        <div style="padding: 40px; text-align: center; color: var(--red-500); font-size: 14px;">
                            <i class="fa fa-exclamation-triangle fa-2x" style="margin-bottom: 10px;"></i>
                            <p>Ocurrió un error al procesar la información contable.</p>
                        </div>
                    `);
                }
            }
        });
    }
});

function format_currency_ve(val, currency = "USD") {
    const symbol = currency === "USD" ? "REF " : "Bs. ";
    return symbol + parseFloat(val).toLocaleString('es-VE', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function render_premium_dashboard(frm, data) {
    if (!frm.fields_dict.dashboard_html || !frm.fields_dict.dashboard_html.$wrapper) {
        return;
    }

    const rate = data.exchange_rate || 1.0;

    // Read calculations directly from the real_kpis dictionary computed in the python backend
    const kpis = data.real_kpis || {};
    
    const t_cobrar = kpis.total_pendiente_usd || 0;
    const v_cobrar = kpis.total_pendiente_vef || 0;
    
    const t_fact = kpis.collected_usd_total || 0;
    const v_fact = kpis.collected_ves_total || 0;
    
    const t_iva = kpis.collected_usd_tax || 0;
    const v_iva = kpis.collected_ves_tax || 0;
    
    const t_spent = kpis.total_expenses_usd || 0;
    const v_spent = kpis.total_expenses_vef || 0;
    
    const t_disp = kpis.available_usd || 0;
    const v_disp = kpis.available_vef || 0;
    
    const t_ret_iva = kpis.ret_iva_usd || 0;
    const v_ret_iva = kpis.ret_iva_vef || 0;
    
    const t_ret_islr = kpis.ret_islr_usd || 0;
    const v_ret_islr = kpis.ret_islr_vef || 0;
    
    const t_igtf = kpis.igtf_total || 0;
    const v_igtf = kpis.igtf_vef || 0;

    const get_card_vals = (usd_val, vef_val) => {
        const equiv_vef = usd_val * rate;
        return {
            usd: format_currency_ve(usd_val, "USD"),
            vef: `Equiv. ${format_currency_ve(equiv_vef, "VEF")} (Tasa BCV: ${rate.toFixed(2)})`
        };
    };

    const html = `
        <div class="dashboard-gerencial-container">
            <style>
                .dashboard-gerencial-container {
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    padding: 10px 0 30px 0;
                    color: var(--text-color);
                }
                .dg-exchange-rate-banner {
                    background: #1e293b !important;
                    border: 1px solid #334155 !important;
                    border-radius: 8px;
                    padding: 12px 20px;
                    margin-bottom: 24px;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    font-size: 13px;
                    color: #cbd5e0 !important;
                }
                .dg-exchange-rate-banner i {
                    color: #3b82f6 !important;
                    font-size: 16px;
                }
                .kpi-cards-grid-custom {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                    gap: 16px;
                    margin-bottom: 25px;
                }
                .kpi-card-custom {
                    border-radius: 12px;
                    padding: 18px;
                    color: white;
                    min-height: 140px;
                    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
                    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.3s ease;
                    display: flex;
                    flex-direction: column;
                    justify-content: space-between;
                    position: relative;
                    overflow: hidden;
                }
                .kpi-card-custom:hover {
                    transform: translateY(-4px);
                    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.25);
                }
                .kpi-card-custom.cobrado-usd {
                    background: linear-gradient(135deg, #2b5c8f 0%, #1a365d 100%) !important;
                    box-shadow: 0 4px 15px rgba(43, 92, 143, 0.25);
                }
                .kpi-card-custom.cobrado-vef {
                    background: linear-gradient(135deg, #2e7d32 0%, #1b5e20 100%) !important;
                    box-shadow: 0 4px 15px rgba(46, 125, 50, 0.25);
                }
                .kpi-card-custom.disponible-vef,
                .kpi-card-custom.disponible-usd {
                    background: linear-gradient(135deg, #0f766e 0%, #115e59 100%) !important;
                    box-shadow: 0 4px 15px rgba(15, 118, 110, 0.25);
                }
                .kpi-card-custom.gastos-custom {
                    background: linear-gradient(135deg, #c2410c 0%, #9a3412 100%) !important;
                    box-shadow: 0 4px 15px rgba(194, 65, 12, 0.25);
                }
                .kpi-card-custom.utilidad-custom {
                    background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%) !important;
                    box-shadow: 0 4px 15px rgba(79, 70, 229, 0.25);
                }
                .kpi-card-custom.utilidad-custom.negative {
                    background: linear-gradient(135deg, #991b1b 0%, #7f1d1d 100%) !important;
                    box-shadow: 0 4px 15px rgba(153, 27, 27, 0.25) !important;
                }
                .kpi-card-custom.retencion-iva,
                .kpi-card-custom.retencion-islr,
                .kpi-card-custom.igtf-custom {
                    background: linear-gradient(135deg, #581c87 0%, #4c1d95 100%) !important;
                    box-shadow: 0 4px 15px rgba(88, 28, 135, 0.25);
                }
                .kpi-card-custom.por-cobrar-custom {
                    background: linear-gradient(135deg, #475569 0%, #1e293b 100%) !important;
                    box-shadow: 0 4px 15px rgba(71, 85, 105, 0.25);
                }
                .kpi-card-custom-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 8px;
                }
                .kpi-card-custom-title {
                    font-size: 11px;
                    font-weight: 600;
                    opacity: 0.9;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: #f1f5f9 !important;
                }
                .kpi-card-custom-icon {
                    font-size: 28px !important;
                    opacity: 0.15;
                    position: absolute;
                    right: 15px;
                    top: 15px;
                    color: white !important;
                }
                .kpi-card-custom-value {
                    font-size: 24px !important;
                    font-weight: 800 !important;
                    line-height: 1.1;
                    color: white !important;
                }
                .kpi-card-custom-ref {
                    font-size: 13px !important;
                    opacity: 0.9;
                    margin-top: 4px;
                    color: #e2e8f0 !important;
                }
                .kpi-card-custom-details {
                    margin-top: 8px;
                    border-top: 1px solid rgba(255, 255, 255, 0.15);
                    padding-top: 6px;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                    font-size: 11px !important;
                    color: #cbd5e0 !important;
                }
                
                .dg-section-title {
                    font-size: 16px;
                    font-weight: 700;
                    margin-top: 15px;
                    margin-bottom: 20px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    color: var(--text-color);
                    border-bottom: 1px solid var(--border-color);
                    padding-bottom: 10px;
                }
                .dg-table-card {
                    background: linear-gradient(145deg, #1e293b, #0f172a) !important;
                    border: 1px solid rgba(255, 255, 255, 0.08) !important;
                    border-radius: 16px;
                    padding: 24px;
                    box-shadow: 0 15px 30px rgba(0, 0, 0, 0.35);
                    margin-bottom: 30px;
                    overflow: hidden;
                }
                .dg-table {
                    width: 100%;
                    margin-bottom: 0;
                    border-collapse: collapse;
                    border-spacing: 0;
                }
                .dg-table th {
                    background: rgba(15, 23, 42, 0.4) !important;
                    font-size: 11px;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    font-weight: 700;
                    padding: 16px 14px !important;
                    border-top: none !important;
                    border-left: none !important;
                    border-right: none !important;
                    border-bottom: 2px solid rgba(255, 255, 255, 0.12) !important;
                    color: #e2e8f0 !important;
                    vertical-align: middle;
                    text-align: center !important;
                }
                .dg-table th:first-child {
                    text-align: left !important;
                }
                .dg-table td {
                    padding: 14px 14px !important;
                    font-size: 13px;
                    border-top: 1px solid rgba(255, 255, 255, 0.06) !important;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
                    border-left: none !important;
                    border-right: none !important;
                    color: #f8fafc !important;
                    vertical-align: middle;
                    text-align: center !important;
                }
                .dg-table td:first-child {
                    text-align: left !important;
                }
                .dg-table tbody tr {
                    transition: background-color 0.15s ease;
                }
                .dg-table tbody tr:hover {
                    background-color: rgba(255, 255, 255, 0.03) !important;
                }
                .dg-badge {
                    display: inline-block;
                    padding: 3px 8px;
                    border-radius: 9999px;
                    font-size: 11px;
                    font-weight: 600;
                }
                .dg-help-tip {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 14px;
                    height: 14px;
                    border-radius: 50%;
                    background-color: rgba(255, 255, 255, 0.15);
                    color: #cbd5e0;
                    font-size: 9.5px;
                    font-weight: bold;
                    cursor: help;
                    margin-left: 5px;
                    vertical-align: middle;
                    transition: all 0.2s ease;
                }
                .dg-help-tip:hover {
                    background-color: #3b82f6;
                    color: #ffffff;
                }
            </style>
            

            <!-- SECCIÓN 2: TARJETAS DE RESUMEN (Consolidadas a partir de los totales de la tabla) -->
            <h6 class="dg-section-title" style="margin-top: 0;">
                <i class="fa fa-th-large" style="color: #3b82f6;"></i> Resumen de Flujo de Caja
            </h6>
            
            <div class="kpi-cards-grid-custom">
                <!-- Por cobrar -->
                <div class="kpi-card-custom por-cobrar-custom">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Por cobrar</span>
                        <i class="fa fa-clock-o kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(t_cobrar, "USD")}</div>
                    <div class="kpi-card-custom-ref">Equiv. ${format_currency_ve(v_cobrar, "VEF")}</div>
                    <div class="kpi-card-custom-details">
                        <span>Facturas pendientes de número de control</span>
                    </div>
                </div>

                <!-- Cobrado USD -->
                <div class="kpi-card-custom cobrado-usd">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Cobrado REF ($)</span>
                        <i class="fa fa-dollar kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(t_fact, "USD")}</div>
                    <div class="kpi-card-custom-ref">Equiv. ${format_currency_ve(t_fact * rate, "VEF")}</div>
                    <div class="kpi-card-custom-details">
                        <span>Base: ${format_currency_ve(t_fact - t_iva - t_igtf, "USD")}</span>
                        <span>IVA: ${format_currency_ve(t_iva, "USD")}</span>
                        <span>IGTF: ${format_currency_ve(t_igtf, "USD")}</span>
                    </div>
                </div>

                <!-- Cobrado Bs. -->
                <div class="kpi-card-custom cobrado-vef">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Cobrado Bs.</span>
                        <i class="fa fa-university kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(v_fact, "VEF")}</div>
                    <div class="kpi-card-custom-ref">Equiv. ${format_currency_ve(v_fact / rate, "USD")}</div>
                    <div class="kpi-card-custom-details">
                        <span>Base: ${format_currency_ve(v_fact - v_iva - v_igtf, "VEF")}</span>
                        <span>IVA: ${format_currency_ve(v_iva, "VEF")}</span>
                        <span>IGTF: ${format_currency_ve(v_igtf, "VEF")}</span>
                    </div>
                </div>

                <!-- Gastos -->
                <div class="kpi-card-custom gastos-custom">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Gastos</span>
                        <i class="fa fa-arrow-down kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(t_spent, "USD")}</div>
                    <div class="kpi-card-custom-ref">Equiv. ${format_currency_ve(t_spent * rate, "VEF")}</div>
                    <div class="kpi-card-custom-details">
                        <span>Caja Bs: ${format_currency_ve(v_spent, "VEF")}</span>
                        <span>Equiv. Ref: ${format_currency_ve(v_spent / rate, "USD")}</span>
                    </div>
                </div>

                <!-- Disponible USD -->
                <div class="kpi-card-custom disponible-usd">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Disponible REF ($)</span>
                        <i class="fa fa-check-circle kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(t_disp, "USD")}</div>
                    <div class="kpi-card-custom-ref">Equiv. ${format_currency_ve(t_disp * rate, "VEF")}</div>
                    <div class="kpi-card-custom-details">
                        <span>Saldo disponible en dólares</span>
                    </div>
                </div>

                <!-- Disponible VES -->
                <div class="kpi-card-custom disponible-vef">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Disponible Bs.</span>
                        <i class="fa fa-check-circle kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(v_disp, "VEF")}</div>
                    <div class="kpi-card-custom-ref">Equiv. ${format_currency_ve(v_disp / rate, "USD")}</div>
                    <div class="kpi-card-custom-details">
                        <span>Saldo disponible en bolívares</span>
                    </div>
                </div>
            </div>

            <h6 class="dg-section-title">
                <i class="fa fa-shield" style="color: #8b5cf6;"></i> Retenciones e Impuestos
            </h6>
            
            <div class="kpi-cards-grid-custom" style="margin-bottom: 35px;">
                <!-- Retención IVA -->
                <div class="kpi-card-custom retencion-iva">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Retención IVA</span>
                        <i class="fa fa-percent kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(v_ret_iva, "VEF")}</div>
                    <div class="kpi-card-custom-ref">REF: ${format_currency_ve(t_ret_iva, "USD")}</div>
                    <div class="kpi-card-custom-details">
                        <span>IVA retenido por clientes especiales</span>
                    </div>
                </div>

                <!-- Retención ISLR -->
                <div class="kpi-card-custom retencion-islr">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">Retención ISLR</span>
                        <i class="fa fa-percent kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(v_ret_islr, "VEF")}</div>
                    <div class="kpi-card-custom-ref">REF: ${format_currency_ve(t_ret_islr, "USD")}</div>
                    <div class="kpi-card-custom-details">
                        <span>ISLR retenido en la fuente</span>
                    </div>
                </div>

                <!-- IGTF -->
                <div class="kpi-card-custom igtf-custom">
                    <div class="kpi-card-custom-header">
                        <span class="kpi-card-custom-title">IGTF</span>
                        <i class="fa fa-university kpi-card-custom-icon"></i>
                    </div>
                    <div class="kpi-card-custom-value">${format_currency_ve(v_igtf, "VEF")}</div>
                    <div class="kpi-card-custom-ref">REF: ${format_currency_ve(t_igtf, "USD")}</div>
                    <div class="kpi-card-custom-details">
                        <span>Impuesto a las Grandes Transacciones Financieras</span>
                    </div>
                </div>
            </div>

            <!-- SECCIÓN 1: CUADRO RESUMEN FINANCIERO POR SUCURSAL -->
            <div class="dg-table-card">
                <h6 class="dg-section-title" style="border: none; padding-bottom: 0; margin-bottom: 20px; margin-top: 0;">
                    <i class="fa fa-table dg-primary-icon"></i> Resumen Financiero por Sucursal
                    <span class="dg-help-tip" data-tooltip="Consolidado financiero del periodo por sucursal (ingresos, egresos, impuestos y utilidad neta).">?</span>
                    <span style="font-size: 12px; color: var(--text-muted); font-weight: normal; margin-left: 6px;">(Valores expresados en USD y su equivalente en Bs. abajo)</span>
                </h6>
                <div style="overflow-x: auto;">
                    <table class="dg-table table table-bordered">
                        <thead>
                            <tr>
                                <th>Sucursal</th>
                                <th style="text-align: right;">Por cobrar <span class="dg-help-tip" data-tooltip="Monto total de facturas que aún no tienen un número de control fiscal asignado.">?</span></th>
                                <th style="text-align: right;">Orden de Pago <span class="dg-help-tip" data-tooltip="Sumatoria de todas las facturas de venta registradas (tanto controladas como pendientes de número de control).">?</span></th>
                                <th style="text-align: right;">IVA Orden de Pago <span class="dg-help-tip" data-tooltip="Sumatoria del IVA de todas las facturas de venta del periodo.">?</span></th>
                                <th style="text-align: right;">Facturado <span class="dg-help-tip" data-tooltip="Monto total de facturas que ya tienen un número de control fiscal asignado.">?</span></th>
                                <th style="text-align: right;">IVA</th>
                                <th style="text-align: right;">IVA desp. Retención</th>
                                <th style="text-align: right;">Ret. IVA</th>
                                <th style="text-align: right;">Ret. ISLR</th>
                                <th style="text-align: right;">IGTF <span class="dg-help-tip" data-tooltip="Impuesto a las grandes transacciones financieras acumulado en el periodo.">?</span></th>
                                <th style="text-align: right;">Ganancia Cambiaria <span class="dg-help-tip" data-tooltip="Ganancia por diferencial cambiario asociada a las facturas del período.">?</span></th>
                                <th style="text-align: right;">Pérdida Cambiaria <span class="dg-help-tip" data-tooltip="Pérdida por diferencial cambiario asociada a las facturas del período.">?</span></th>
                                <th style="text-align: right;">Disponibilidad <span class="dg-help-tip" data-tooltip="Monto disponible calculado: (Facturado - IVA) - Retención de ISLR - Pérdida Cambiaria + Ganancia Cambiaria.">?</span></th>
                                <th style="text-align: right;">Gastos</th>
                                <th style="text-align: right;">Utilidad <span class="dg-help-tip" data-tooltip="Utilidad neta calculada de la sucursal: Disponibilidad - Gastos.">?</span></th>
                            </tr>
                        </thead>
                        <tbody>
                            ${render_branch_table_rows(data.branch_financial_summary, data.exchange_rate)}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- SECCIÓN 3: CUADRO RESUMEN FINANCIERO POR CLIENTE -->
            <div class="dg-table-card" style="margin-top: 30px;">
                <h6 class="dg-section-title" style="border: none; padding-bottom: 0; margin-bottom: 20px; margin-top: 0;">
                    <i class="fa fa-users dg-primary-icon"></i> Resumen Financiero por Cliente (Últimos 10)
                    <span class="dg-help-tip" data-tooltip="Consolidado financiero del periodo por cliente (ingresos e impuestos asociados).">?</span>
                    <span style="font-size: 12px; color: var(--text-muted); font-weight: normal; margin-left: 6px;">(Valores expresados en USD y su equivalente en Bs. abajo)</span>
                </h6>
                <div style="overflow-x: auto;">
                    <table class="dg-table table table-bordered">
                        <thead>
                            <tr>
                                <th>Cliente</th>
                                <th style="text-align: right;">Por cobrar <span class="dg-help-tip" data-tooltip="Monto total de facturas que aún no tienen un número de control fiscal asignado.">?</span></th>
                                <th style="text-align: right;">Orden de Pago <span class="dg-help-tip" data-tooltip="Sumatoria de todas las facturas de venta registradas (tanto controladas como pendientes de número de control).">?</span></th>
                                <th style="text-align: right;">IVA Orden de Pago <span class="dg-help-tip" data-tooltip="Sumatoria del IVA de todas las facturas de venta del periodo.">?</span></th>
                                <th style="text-align: right;">Facturado <span class="dg-help-tip" data-tooltip="Monto total de facturas que ya tienen un número de control fiscal asignado.">?</span></th>
                                <th style="text-align: right;">IVA</th>
                                <th style="text-align: right;">IVA desp. Retención</th>
                                <th style="text-align: right;">Ret. IVA</th>
                                <th style="text-align: right;">Ret. ISLR</th>
                                <th style="text-align: right;">Disponibilidad <span class="dg-help-tip" data-tooltip="Monto disponible calculado: (Facturado - IVA) - Retención de ISLR.">?</span></th>
                            </tr>
                        </thead>
                        <tbody>
                            ${render_customer_table_rows(data.customer_financial_summary, data.exchange_rate)}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    frm.fields_dict.dashboard_html.$wrapper.html(html);

    // Bind clean jQuery click event to navigate to Sales Invoices list view
    frm.fields_dict.dashboard_html.$wrapper.find('.por-cobrar-custom').css('cursor', 'pointer').on('click', function() {
        const filters = {
            docstatus: 1,
            company: frm.doc.company,
            posting_date: ['between', [frm.doc.from_date, frm.doc.to_date]]
        };
        if (frm.doc.branch) {
            filters.branch = frm.doc.branch;
        }
        frappe.set_route('List', 'Sales Invoice', filters);
    });

    // Create or locate the global tooltip element at the body level (immune to overflow: auto clipping)
    if ($('#dg-tooltip-container').length === 0) {
        $('body').append(`
            <div id="dg-tooltip-container" style="
                position: absolute;
                display: none;
                background: #0f172a;
                color: #f1f5f9;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 11.5px;
                max-width: 250px;
                z-index: 999999;
                box-shadow: 0 10px 15px -3px rgba(0,0,0,0.5);
                pointer-events: none;
                line-height: 1.4;
                font-family: sans-serif;
            "></div>
        `);
    }

    // Bind clean tooltip events using event delegation/direct mapping on the dashboard wrapper
    const $tooltip = $('#dg-tooltip-container');
    frm.fields_dict.dashboard_html.$wrapper.find('.dg-help-tip').on('mouseenter', function(e) {
        const text = $(this).attr('data-tooltip');
        if (!text) return;

        $tooltip.text(text).show();

        const offset = $(this).offset();
        const width = $tooltip.outerWidth();
        const height = $tooltip.outerHeight();

        $tooltip.css({
            top: (offset.top - height - 8) + 'px',
            left: (offset.left - (width / 2) + ($(this).outerWidth() / 2)) + 'px'
        });
    }).on('mouseleave', function() {
        $tooltip.hide();
    });
}

function render_branch_table_rows(rows, exchange_rate) {
    if (!rows || rows.length === 0) {
        return `<tr><td colspan="15" class="text-center" style="padding: 20px; color: var(--text-muted);">No se encontraron registros financieros para las sucursales.</td></tr>`;
    }

    const format_table_cell = (usd_val, vef_val, usd_color = "#f8fafc") => {
        const usd_str = format_currency_ve(usd_val, "USD");
        const bs_str = format_currency_ve(vef_val, "VEF");
        return `<div style="font-weight: 600; color: ${usd_color};">${usd_str}</div><div style="font-size: 10px; color: #94a3b8; font-weight: normal; margin-top: 1px; opacity: 0.8;">${bs_str}</div>`;
    };

    let t_cobrar = 0, t_op = 0, t_iva_op = 0, t_fact = 0, t_iva = 0, t_neto = 0, t_ret_iva = 0, t_ret_islr = 0, t_igtf = 0, t_ganancia = 0, t_perdida = 0, t_disp = 0, t_spent = 0, t_util = 0;
    let v_cobrar = 0, v_op = 0, v_iva_op = 0, v_fact = 0, v_iva = 0, v_neto = 0, v_ret_iva = 0, v_ret_islr = 0, v_igtf = 0, v_ganancia = 0, v_perdida = 0, v_disp = 0, v_spent = 0, v_util = 0;

    let rows_html = rows.map(r => {
        if ((r.indent || 0) === 0) {
            t_cobrar += r.pending_to_collect || 0;      v_cobrar += r.pending_to_collect_vef || 0;
            t_op += r.payment_order || 0;               v_op += r.payment_order_vef || 0;
            t_iva_op += r.payment_order_vat || 0;       v_iva_op += r.payment_order_vat_vef || 0;
            t_fact += r.billed || 0;                    v_fact += r.billed_vef || 0;
            t_iva += r.vat || 0;                        v_iva += r.vat_vef || 0;
            t_neto += r.vat_after_withholding || 0;     v_neto += r.vat_after_withholding_vef || 0;
            t_ret_iva += r.vat_withholding || 0;        v_ret_iva += r.vat_withholding_vef || 0;
            t_ret_islr += r.islr_withholding || 0;      v_ret_islr += r.islr_withholding_vef || 0;
            t_igtf += r.igtf || 0;                      v_igtf += r.igtf_vef || 0;
            t_ganancia += r.ganancia || 0;              v_ganancia += r.ganancia_vef || 0;
            t_perdida += r.perdida || 0;                v_perdida += r.perdida_vef || 0;
            t_disp += r.availability || 0;              v_disp += r.availability_vef || 0;
            t_spent += r.spent || 0;                    v_spent += r.spent_vef || 0;
            t_util += r.profit || 0;                    v_util += r.profit_vef || 0;
        }

        const indent = (r.indent || 0) * 20;
        const name_html = frappe.utils.escape_html(r.branch);
        const branch_label = r.is_group
            ? `<span style="margin-left: ${indent}px; color: #ffffff;"><strong>${name_html}</strong></span>`
            : `<span style="margin-left: ${indent}px; color: #cbd5e0; opacity: 0.95;">${name_html}</span>`;
            
        return `
            <tr>
                <td>${branch_label}</td>
                <td style="text-align: right;">${format_table_cell(r.pending_to_collect, r.pending_to_collect_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.payment_order, r.payment_order_vef, "#60a5fa")}</td>
                <td style="text-align: right;">${format_table_cell(r.payment_order_vat, r.payment_order_vat_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.billed, r.billed_vef, "#60a5fa")}</td>
                <td style="text-align: right;">${format_table_cell(r.vat, r.vat_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.vat_after_withholding, r.vat_after_withholding_vef, "#f8fafc")}</td>
                <td style="text-align: right;">${format_table_cell(r.vat_withholding, r.vat_withholding_vef, "#c084fc")}</td>
                <td style="text-align: right;">${format_table_cell(r.islr_withholding, r.islr_withholding_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.igtf, r.igtf_vef, "#f87171")}</td>
                <td style="text-align: right;">${format_table_cell(r.ganancia, r.ganancia_vef, (r.ganancia || 0) > 0 ? "#34d399" : "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.perdida, r.perdida_vef, (r.perdida || 0) > 0 ? "#f87171" : "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.availability, r.availability_vef, r.availability >= 0 ? "#34d399" : "#f87171")}</td>
                <td style="text-align: right;">${format_table_cell(r.spent, r.spent_vef, "#f87171")}</td>
                <td style="text-align: right;">${format_table_cell(r.profit, r.profit_vef, r.profit >= 0 ? "#34d399" : "#f87171")}</td>
            </tr>
        `;
    }).join("");

    const total_row = `
        <tr style="background: rgba(15, 23, 42, 0.6) !important; border-top: 2px solid rgba(255, 255, 255, 0.15) !important; border-bottom: 2px solid rgba(255, 255, 255, 0.15) !important; font-weight: 700; color: #ffffff !important;">
            <td><strong>TOTAL</strong></td>
            <td style="text-align: right;">${format_table_cell(t_cobrar, v_cobrar, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_op, v_op, "#60a5fa")}</td>
            <td style="text-align: right;">${format_table_cell(t_iva_op, v_iva_op, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_fact, v_fact, "#60a5fa")}</td>
            <td style="text-align: right;">${format_table_cell(t_iva, v_iva, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_neto, v_neto, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_ret_iva, v_ret_iva, "#c084fc")}</td>
            <td style="text-align: right;">${format_table_cell(t_ret_islr, v_ret_islr, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_igtf, v_igtf, "#f87171")}</td>
            <td style="text-align: right;">${format_table_cell(t_ganancia, v_ganancia, "#34d399")}</td>
            <td style="text-align: right;">${format_table_cell(t_perdida, v_perdida, "#f87171")}</td>
            <td style="text-align: right;">${format_table_cell(t_disp, v_disp, t_disp >= 0 ? "#34d399" : "#f87171")}</td>
            <td style="text-align: right;">${format_table_cell(t_spent, v_spent, "#f87171")}</td>
            <td style="text-align: right;">${format_table_cell(t_util, v_util, t_util >= 0 ? "#34d399" : "#f87171")}</td>
        </tr>
    `;

    return rows_html + total_row;
}

function render_customer_table_rows(rows, exchange_rate) {
    if (!rows || rows.length === 0) {
        return `<tr><td colspan="10" class="text-center" style="padding: 20px; color: var(--text-muted);">No se encontraron registros financieros para los clientes.</td></tr>`;
    }

    const format_table_cell = (usd_val, vef_val, usd_color = "#f8fafc") => {
        const usd_str = format_currency_ve(usd_val, "USD");
        const bs_str = format_currency_ve(vef_val, "VEF");
        return `<div style="font-weight: 600; color: ${usd_color};">${usd_str}</div><div style="font-size: 10px; color: #94a3b8; font-weight: normal; margin-top: 1px; opacity: 0.8;">${bs_str}</div>`;
    };

    let t_cobrar = 0, t_op = 0, t_iva_op = 0, t_fact = 0, t_iva = 0, t_neto = 0, t_ret_iva = 0, t_ret_islr = 0, t_disp = 0;
    let v_cobrar = 0, v_op = 0, v_iva_op = 0, v_fact = 0, v_iva = 0, v_neto = 0, v_ret_iva = 0, v_ret_islr = 0, v_disp = 0;

    let rows_html = rows.slice(0, 10).map(r => {
        t_cobrar += r.pending_to_collect || 0;      v_cobrar += r.pending_to_collect_vef || 0;
        t_op += r.payment_order || 0;               v_op += r.payment_order_vef || 0;
        t_iva_op += r.payment_order_vat || 0;       v_iva_op += r.payment_order_vat_vef || 0;
        t_fact += r.billed || 0;                    v_fact += r.billed_vef || 0;
        t_iva += r.vat || 0;                        v_iva += r.vat_vef || 0;
        t_neto += r.vat_after_withholding || 0;     v_neto += r.vat_after_withholding_vef || 0;
        t_ret_iva += r.vat_withholding || 0;        v_ret_iva += r.vat_withholding_vef || 0;
        t_ret_islr += r.islr_withholding || 0;      v_ret_islr += r.islr_withholding_vef || 0;
        t_disp += r.availability || 0;              v_disp += r.availability_vef || 0;

        const name_html = frappe.utils.escape_html(r.customer_name);
        return `
            <tr>
                <td><span style="color: #cbd5e0; opacity: 0.95;">${name_html}</span></td>
                <td style="text-align: right;">${format_table_cell(r.pending_to_collect, r.pending_to_collect_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.payment_order, r.payment_order_vef, "#60a5fa")}</td>
                <td style="text-align: right;">${format_table_cell(r.payment_order_vat, r.payment_order_vat_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.billed, r.billed_vef, "#60a5fa")}</td>
                <td style="text-align: right;">${format_table_cell(r.vat, r.vat_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.vat_after_withholding, r.vat_after_withholding_vef, "#f8fafc")}</td>
                <td style="text-align: right;">${format_table_cell(r.vat_withholding, r.vat_withholding_vef, "#c084fc")}</td>
                <td style="text-align: right;">${format_table_cell(r.islr_withholding, r.islr_withholding_vef, "#e2e8f0")}</td>
                <td style="text-align: right;">${format_table_cell(r.availability, r.availability_vef, r.availability >= 0 ? "#34d399" : "#f87171")}</td>
            </tr>
        `;
    }).join("");

    const total_row = `
        <tr style="background: rgba(15, 23, 42, 0.6) !important; border-top: 2px solid rgba(255, 255, 255, 0.15) !important; border-bottom: 2px solid rgba(255, 255, 255, 0.15) !important; font-weight: 700; color: #ffffff !important;">
            <td><strong>TOTAL</strong></td>
            <td style="text-align: right;">${format_table_cell(t_cobrar, v_cobrar, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_op, v_op, "#60a5fa")}</td>
            <td style="text-align: right;">${format_table_cell(t_iva_op, v_iva_op, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_fact, v_fact, "#60a5fa")}</td>
            <td style="text-align: right;">${format_table_cell(t_iva, v_iva, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_neto, v_neto, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_ret_iva, v_ret_iva, "#c084fc")}</td>
            <td style="text-align: right;">${format_table_cell(t_ret_islr, v_ret_islr, "#ffffff")}</td>
            <td style="text-align: right;">${format_table_cell(t_disp, v_disp, t_disp >= 0 ? "#34d399" : "#f87171")}</td>
        </tr>
    `;

    return rows_html + total_row;
}