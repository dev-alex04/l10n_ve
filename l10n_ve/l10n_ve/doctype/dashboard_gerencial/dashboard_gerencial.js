// -*- coding: utf-8 -*-
// Form script for Dashboard Gerencial Single DocType

frappe.ui.form.on('Dashboard Gerencial', {
    onload: function(frm) {
        // Redirect to standard Single DocType route if opened as a generic new document
        if (frm.is_new()) {
            frappe.set_route('Form', 'Dashboard Gerencial', 'Dashboard Gerencial');
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
        if (changed) {
            frm.refresh_fields();
            frm.dirty(false);
        }
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
        frm.page.set_primary_action(__('Actualizar'), () => {
            frm.trigger('render_dashboard');
        }, 'fa fa-refresh');

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

    render_dashboard: function(frm) {
        if (!frm.fields_dict.dashboard_html || !frm.fields_dict.dashboard_html.$wrapper) {
            return;
        }

        if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
            frm.fields_dict.dashboard_html.$wrapper.html(`
                <div style="padding: 40px; text-align: center; color: var(--text-muted); font-size: 14px;">
                    <i class="fa fa-info-circle fa-2x" style="margin-bottom: 10px;"></i>
                    <p>Por favor seleccione los filtros obligatorios (Empresa, Fecha Inicio y Fecha Fin) para mostrar el panel.</p>
                </div>
            `);
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
            method: 'l10n_ve.l10n_ve.doctype.dashboard_gerencial.dashboard_gerencial.get_dashboard_data',
            args: {
                company: frm.doc.company,
                from_date: frm.doc.from_date,
                to_date: frm.doc.to_date,
                branch: frm.doc.branch || null,
                cost_center: frm.doc.cost_center || null
            },
            callback: function(r) {
                if (r.message) {
                    render_premium_dashboard(frm, r.message);
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
                .dg-card-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
                    gap: 20px;
                    margin-bottom: 35px;
                }
                .dg-card {
                    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
                    border: 1px solid #334155 !important;
                    border-radius: 12px;
                    padding: 24px;
                    position: relative;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    justify-content: space-between;
                    min-height: 180px;
                    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2), 0 2px 4px -1px rgba(0,0,0,0.1);
                    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                }
                .dg-card:hover {
                    transform: translateY(-4px);
                    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3), 0 4px 6px -2px rgba(0,0,0,0.2);
                    border-color: #475569 !important;
                }
                .dg-card-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 8px;
                }
                .dg-card-title {
                    font-size: 11px;
                    text-transform: uppercase;
                    letter-spacing: 0.8px;
                    font-weight: 700;
                    color: #94a3b8 !important;
                }
                .dg-card-icon {
                    font-size: 36px !important;
                    opacity: 0.12;
                    position: absolute;
                    right: 20px;
                    top: 20px;
                    color: #ffffff !important;
                }
                .dg-card-value {
                    font-size: 30px !important;
                    font-weight: 800 !important;
                    margin: 8px 0 0 0;
                    letter-spacing: -0.5px;
                    color: #ffffff !important;
                }
                .dg-card-equivalent {
                    font-size: 15px !important;
                    font-weight: 600 !important;
                    color: #3b82f6 !important;
                    margin-top: 2px;
                    margin-bottom: 8px;
                }
                .dg-card-green .dg-card-equivalent, .dg-card-deepgreen .dg-card-equivalent {
                    color: #10b981 !important;
                }
                .dg-card-red .dg-card-equivalent, .dg-card-pink .dg-card-equivalent {
                    color: #ef4444 !important;
                }
                .dg-card-subtext {
                    font-size: 12px;
                    color: #94a3b8 !important;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                    border-top: 1px solid rgba(255, 255, 255, 0.08);
                    padding-top: 8px;
                    margin-top: 6px;
                }
                
                /* Premium Card Border Accents (Slate background for all) */
                .dg-card-grey { border-top: 4px solid #64748b !important; }
                .dg-card-red { border-top: 4px solid #ef4444 !important; }
                .dg-card-teal { border-top: 4px solid #06b6d4 !important; }
                .dg-card-green { border-top: 4px solid #10b981 !important; }
                .dg-card-blue { border-top: 4px solid #3b82f6 !important; }
                .dg-card-orange { border-top: 4px solid #f97316 !important; }
                .dg-card-purple { border-top: 4px solid #8b5cf6 !important; }
                .dg-card-pink { border-top: 4px solid #ec4899 !important; }
                .dg-card-indigo { border-top: 4px solid #6366f1 !important; }
                .dg-card-deepgreen { border-top: 4px solid #059669 !important; }
                
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
                    background: #1e293b !important;
                    border: 1px solid #334155 !important;
                    border-radius: 14px;
                    padding: 24px;
                    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
                    margin-bottom: 30px;
                }
                .dg-table {
                    width: 100%;
                    margin-bottom: 0;
                    border-collapse: collapse;
                }
                .dg-table th {
                    background: #0f172a !important;
                    font-size: 11px;
                    text-transform: uppercase;
                    letter-spacing: 0.8px;
                    font-weight: 700;
                    padding: 14px 16px !important;
                    border: 1px solid #334155 !important;
                    color: #94a3b8 !important;
                }
                .dg-table td {
                    padding: 14px 16px !important;
                    font-size: 13px;
                    border: 1px solid #334155 !important;
                    color: #cbd5e0 !important;
                }
                .dg-badge {
                    display: inline-block;
                    padding: 3px 8px;
                    border-radius: 9999px;
                    font-size: 11px;
                    font-weight: 600;
                }
            </style>

            <div class="dg-exchange-rate-banner">
                <i class="fa fa-info-circle"></i>
                <span>Tasa de cambio de referencia: <strong>1 USD = ${format_currency_ve(data.exchange_rate, "VEF")}</strong> (al ${frappe.datetime.str_to_user(frm.doc.to_date)})</span>
            </div>

            <!-- SECCIÓN 1: FACTURACIÓN Y VENTAS -->
            <h6 class="dg-section-title">
                <i class="fa fa-shopping-cart" style="color: #3b82f6;"></i> Facturación y Ventas
            </h6>
            <div class="dg-card-grid">
                <!-- Total Facturado USD -->
                <div class="dg-card dg-card-blue">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Total Facturado USD</span>
                        <i class="fa fa-dollar dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.total_billed_usd, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.total_billed_bs, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Monto Base: ${format_currency_ve(data.total_billed_usd - data.taxes_usd, "USD")} <span style="opacity: 0.8; font-size: 11px;">(${format_currency_ve(data.total_billed_bs - data.taxes_vef, "VEF")})</span></span>
                        <span>Impuesto: ${format_currency_ve(data.taxes_usd, "USD")} <span style="opacity: 0.8; font-size: 11px;">(${format_currency_ve(data.taxes_vef, "VEF")})</span></span>
                    </div>
                </div>

                <!-- Total Facturado BS -->
                <div class="dg-card dg-card-grey">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Total Facturado BS</span>
                        <i class="fa fa-bank dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.total_billed_bs, "VEF")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.total_billed_usd, "USD")}</div>
                    <div class="dg-card-subtext">
                        <span>Monto Base: ${format_currency_ve(data.total_billed_bs - data.taxes_vef, "VEF")} <span style="opacity: 0.8; font-size: 11px;">(${format_currency_ve(data.total_billed_usd - data.taxes_usd, "USD")})</span></span>
                        <span>Impuesto: ${format_currency_ve(data.taxes_vef, "VEF")} <span style="opacity: 0.8; font-size: 11px;">(${format_currency_ve(data.taxes_usd, "USD")})</span></span>
                    </div>
                </div>

                <!-- Cantidad de Ventas -->
                <div class="dg-card dg-card-purple">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Cantidad de ventas</span>
                        <i class="fa fa-shopping-bag dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${data.sales_count}</div>
                    <div class="dg-card-subtext">
                        <span>Facturas emitidas en el periodo</span>
                    </div>
                </div>

                <!-- USD Facturas de Venta -->
                <div class="dg-card dg-card-teal">
                    <div class="dg-card-header">
                        <span class="dg-card-title">USD Facturas de venta</span>
                        <i class="fa fa-file-text dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${data.usd_sales_invoices_count}</div>
                    <div class="dg-card-subtext">
                        <span>Facturas emitidas nativas en USD</span>
                    </div>
                </div>
            </div>

            <!-- SECCIÓN 2: COBROS, IMPUESTOS Y RETENCIONES -->
            <h6 class="dg-section-title">
                <i class="fa fa-shield" style="color: #38a169;"></i> Cobros, Impuestos y Retenciones
            </h6>
            <div class="dg-card-grid">
                <!-- Cobrado VEF -->
                <div class="dg-card dg-card-green">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Total Cobrado Bs</span>
                        <i class="fa fa-arrow-up dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.collected_amount, "VEF")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.collected_amount / data.exchange_rate, "USD")}</div>
                    <div class="dg-card-subtext">
                        <span>Recaudación real cobrada en bolívares</span>
                        <span>Equiv. USD: ${format_currency_ve(data.collected_amount / data.exchange_rate, "USD")}</span>
                    </div>
                </div>

                <!-- Pendiente por Cobrar USD -->
                <div class="dg-card dg-card-red">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Pendiente por Cobrar</span>
                        <i class="fa fa-exclamation-circle dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.pending_to_collect_usd, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.pending_to_collect_usd * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Cuentas por cobrar (A/R) en USD</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.pending_to_collect_usd * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>

                <!-- Impuestos USD -->
                <div class="dg-card dg-card-orange">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Impuestos USD</span>
                        <i class="fa fa-percent dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.taxes_usd, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.taxes_usd * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Débito fiscal (IVA) estimado en USD</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.taxes_usd * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>

                <!-- Retención IVA Clientes -->
                <div class="dg-card dg-card-teal">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Retención IVA Clientes</span>
                        <i class="fa fa-gavel dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.client_vat_withholding_usd, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.client_vat_withholding_usd * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Anticipos de IVA retenidos por clientes</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.client_vat_withholding_usd * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>

                <!-- Retención ISLR Clientes -->
                <div class="dg-card dg-card-orange">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Retención ISLR Clientes</span>
                        <i class="fa fa-balance-scale dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.client_islr_withholding_usd, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.client_islr_withholding_usd * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Anticipos de ISLR retenidos por clientes</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.client_islr_withholding_usd * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>

                <!-- IGTF por Pagar USD -->
                <div class="dg-card dg-card-red">
                    <div class="dg-card-header">
                        <span class="dg-card-title">IGTF por Pagar USD</span>
                        <i class="fa fa-university dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.igtf_payable_usd, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.igtf_payable_usd * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Impuesto a grandes transacciones financieras</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.igtf_payable_usd * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>
            </div>

            <!-- SECCIÓN 3: CAJA, EGRESOS Y DISPONIBILIDAD -->
            <h6 class="dg-section-title">
                <i class="fa fa-piggy-bank" style="color: #dd6b20;"></i> Caja, Egresos y Disponibilidad
            </h6>
            <div class="dg-card-grid">
                <!-- Gastos USD (Mes) -->
                <div class="dg-card dg-card-pink">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Gastos USD (Mes)</span>
                        <i class="fa fa-arrow-down dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.expenses_usd_month, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.expenses_usd_month * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Egresos acumulados en el periodo</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.expenses_usd_month * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>

                <!-- Gastos USD (Año) -->
                <div class="dg-card dg-card-indigo">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Gastos USD (Año)</span>
                        <i class="fa fa-calendar dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.expenses_usd_year, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.expenses_usd_year * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Egresos del año fiscal corriente</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.expenses_usd_year * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>

                <!-- Disponible USD -->
                <div class="dg-card dg-card-deepgreen">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Disponible USD</span>
                        <i class="fa fa-check-circle dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${format_currency_ve(data.available_usd, "USD")}</div>
                    <div class="dg-card-equivalent">${format_currency_ve(data.available_usd * data.exchange_rate, "VEF")}</div>
                    <div class="dg-card-subtext">
                        <span>Fondos consolidados en Cajas y Bancos USD</span>
                        <span>Equiv. Bs: ${format_currency_ve(data.available_usd * data.exchange_rate, "VEF")}</span>
                    </div>
                </div>
            </div>

            <!-- SECCIÓN 4: TABLA RESUMEN FINANCIERO POR SUCURSAL -->
            <div class="dg-table-card">
                <h6 class="dg-section-title" style="border: none; padding-bottom: 0; margin-bottom: 20px;">
                    <i class="fa fa-table dg-primary-icon"></i> Resumen Financiero por Sucursal
                    <span style="font-size: 12px; color: var(--text-muted); font-weight: normal; margin-left: 6px;">(Valores expresados en USD y su equivalente en Bs. abajo)</span>
                </h6>
                <div style="overflow-x: auto;">
                    <table class="dg-table table table-bordered">
                        <thead>
                            <tr>
                                <th>Sucursal</th>
                                <th style="text-align: right;">Por cobrar</th>
                                <th style="text-align: right;">Orden de Pago</th>
                                <th style="text-align: right;">IVA Orden de Pago</th>
                                <th style="text-align: right;">Facturado</th>
                                <th style="text-align: right;">IVA</th>
                                <th style="text-align: right;">IVA desp. Retención</th>
                                <th style="text-align: right;">Ret. IVA</th>
                                <th style="text-align: right;">Ret. ISLR</th>
                                <th style="text-align: right;">Disponibilidad</th>
                                <th style="text-align: right;">Gastos</th>
                                <th style="text-align: right;">Utilidad</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${render_branch_table_rows(data.branch_financial_summary, data.exchange_rate)}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    frm.fields_dict.dashboard_html.$wrapper.html(html);
}

function render_branch_table_rows(rows, exchange_rate) {
    if (!rows || rows.length === 0) {
        return `<tr><td colspan="12" class="text-center" style="padding: 20px; color: var(--text-muted);">No se encontraron registros financieros para las sucursales.</td></tr>`;
    }

    const rate = exchange_rate || 1.0;
    const format_table_cell = (usd_val, r) => {
        const usd_str = format_currency_ve(usd_val, "USD");
        const bs_str = format_currency_ve(usd_val * r, "VEF");
        return `<div>${usd_str}</div><div style="font-size: 10.5px; color: #a0aec0; font-weight: normal; margin-top: 2px;">${bs_str}</div>`;
    };

    let t_cobrar = 0, t_op = 0, t_iva_op = 0, t_fact = 0, t_iva = 0, t_neto = 0, t_ret_iva = 0, t_ret_islr = 0, t_disp = 0, t_spent = 0, t_util = 0;

    let rows_html = rows.map(r => {
        t_cobrar += r.pending_to_collect;
        t_op += r.payment_order;
        t_iva_op += r.payment_order_vat;
        t_fact += r.billed;
        t_iva += r.vat;
        t_neto += r.vat_after_withholding;
        t_ret_iva += r.vat_withholding;
        t_ret_islr += r.islr_withholding;
        t_disp += r.availability;
        t_spent += r.spent;
        t_util += r.profit;

        return `
            <tr>
                <td><strong>${frappe.utils.escape_html(r.branch)}</strong></td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.pending_to_collect, rate)}</td>
                <td style="text-align: right; font-weight: 600; color: #3b82f6;">${format_table_cell(r.payment_order, rate)}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.payment_order_vat, rate)}</td>
                <td style="text-align: right; font-weight: 600; color: #3b82f6;">${format_table_cell(r.billed, rate)}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.vat, rate)}</td>
                <td style="text-align: right; font-weight: 600;">${format_table_cell(r.vat_after_withholding, rate)}</td>
                <td style="text-align: right; font-weight: 600; color: #8b5cf6;">${format_table_cell(r.vat_withholding, rate)}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.islr_withholding, rate)}</td>
                <td style="text-align: right; font-weight: 700; color: ${r.availability >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(r.availability, rate)}</td>
                <td style="text-align: right; font-weight: 600; color: #ef4444;">${format_table_cell(r.spent, rate)}</td>
                <td style="text-align: right; font-weight: 700; color: ${r.profit >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(r.profit, rate)}</td>
            </tr>
        `;
    }).join("");

    // Agregar fila de totales
    const total_row = `
        <tr style="background: #1f2733 !important; border-top: 2px solid #2d3748 !important; font-weight: 700; color: #ffffff !important;">
            <td><strong>TOTAL</strong></td>
            <td style="text-align: right;">${format_table_cell(t_cobrar, rate)}</td>
            <td style="text-align: right; color: #3b82f6;">${format_table_cell(t_op, rate)}</td>
            <td style="text-align: right;">${format_table_cell(t_iva_op, rate)}</td>
            <td style="text-align: right; color: #3b82f6;">${format_table_cell(t_fact, rate)}</td>
            <td style="text-align: right;">${format_table_cell(t_iva, rate)}</td>
            <td style="text-align: right;">${format_table_cell(t_neto, rate)}</td>
            <td style="text-align: right; color: #8b5cf6;">${format_table_cell(t_ret_iva, rate)}</td>
            <td style="text-align: right;">${format_table_cell(t_ret_islr, rate)}</td>
            <td style="text-align: right; color: ${t_disp >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(t_disp, rate)}</td>
            <td style="text-align: right; color: #ef4444;">${format_table_cell(t_spent, rate)}</td>
            <td style="text-align: right; color: ${t_util >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(t_util, rate)}</td>
        </tr>
    `;

    return rows_html + total_row;
}
