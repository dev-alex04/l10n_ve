// -*- coding: utf-8 -*-
// Form script for Dashboard Gerencial Single DocType

frappe.ui.form.on('Dashboard Gerencial', {
    onload: function(frm) {
        // Redirect to standard Single DocType route if opened as a generic new document
        if (frm.is_new() && frm.doc.name !== 'Dashboard Gerencial') {
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
        // Always clear branch and cost center filters on initial page load to show consolidated data
        if (frm.doc.branch) {
            frm.doc.branch = '';
            changed = true;
        }
        if (frm.doc.cost_center) {
            frm.doc.cost_center = '';
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

        // Add download buttons in inner toolbar
        frm.page.add_inner_button(__('Descargar PDF'), () => {
            if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
                frappe.msgprint(__('Por favor seleccione Empresa, Fecha Inicio y Fecha Fin.'));
                return;
            }
            const url = frappe.urllib.get_full_url(
                `/api/method/l10n_ve.l10n_ve.doctype.dashboard_gerencial.dashboard_gerencial.download_pdf?company=${encodeURIComponent(frm.doc.company)}&from_date=${encodeURIComponent(frm.doc.from_date)}&to_date=${encodeURIComponent(frm.doc.to_date)}&branch=${encodeURIComponent(frm.doc.branch || '')}&cost_center=${encodeURIComponent(frm.doc.cost_center || '')}`
            );
            window.open(url);
        });

        frm.page.add_inner_button(__('Descargar Excel'), () => {
            if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
                frappe.msgprint(__('Por favor seleccione Empresa, Fecha Inicio y Fecha Fin.'));
                return;
            }
            const url = frappe.urllib.get_full_url(
                `/api/method/l10n_ve.l10n_ve.doctype.dashboard_gerencial.dashboard_gerencial.download_excel?company=${encodeURIComponent(frm.doc.company)}&from_date=${encodeURIComponent(frm.doc.from_date)}&to_date=${encodeURIComponent(frm.doc.to_date)}&branch=${encodeURIComponent(frm.doc.branch || '')}&cost_center=${encodeURIComponent(frm.doc.cost_center || '')}`
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
                title: __('Rango de Fechas Inválido'),
                indicator: 'red',
                message: __('La Fecha de Inicio no puede ser posterior a la Fecha Fin.')
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
    if (!frm.fields_dict.dashboard_html || !frm.fields_dict.dashboard_html.$wrapper) {
        return;
    }

    const rate = data.exchange_rate || 1.0;

    // Calculate sums from table rows to drive both the table totals and the summary cards
    let t_cobrar = 0, t_op = 0, t_iva_op = 0, t_fact = 0, t_iva = 0, t_neto = 0, t_ret_iva = 0, t_ret_islr = 0, t_igtf = 0, t_disp = 0, t_spent = 0, t_util = 0;
    // Bs nativo para las tarjetas (mismos campos *_vef que la tabla)
    let v_cobrar = 0, v_fact = 0, v_iva = 0, v_igtf = 0, v_disp = 0, v_spent = 0, v_util = 0;
    (data.branch_financial_summary || []).forEach(r => {
        // Solo raíces (indent 0): la tabla es un árbol y los padres ya consolidan a sus hijos.
        if ((r.indent || 0) !== 0) return;
        t_cobrar += r.pending_to_collect || 0;   v_cobrar += r.pending_to_collect_vef || 0;
        t_op += r.payment_order || 0;
        t_iva_op += r.payment_order_vat || 0;
        t_fact += r.billed || 0;                  v_fact += r.billed_vef || 0;
        t_iva += r.vat || 0;                       v_iva += r.vat_vef || 0;
        t_neto += r.vat_after_withholding || 0;
        t_ret_iva += r.vat_withholding || 0;
        t_ret_islr += r.islr_withholding || 0;
        t_igtf += r.igtf || 0;                     v_igtf += r.igtf_vef || 0;
        t_disp += r.availability || 0;             v_disp += r.availability_vef || 0;
        t_spent += r.spent || 0;                   v_spent += r.spent_vef || 0;
        t_util += r.profit || 0;                   v_util += r.profit_vef || 0;
    });

    const get_card_vals = (usd_val, vef_val) => {
        return {
            usd: format_currency_ve(usd_val, "USD"),
            vef: format_currency_ve(vef_val, "VEF")
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
                .dg-card-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                    gap: 16px;
                    margin-bottom: 35px;
                }
                .dg-card {
                    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
                    border: 1px solid #334155 !important;
                    border-radius: 12px;
                    padding: 18px;
                    position: relative;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    justify-content: space-between;
                    min-height: 130px;
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
                    margin-bottom: 4px;
                }
                .dg-card-title {
                    font-size: 10.5px;
                    text-transform: uppercase;
                    letter-spacing: 0.8px;
                    font-weight: 700;
                    color: #94a3b8 !important;
                }
                .dg-card-icon {
                    font-size: 28px !important;
                    opacity: 0.12;
                    position: absolute;
                    right: 15px;
                    top: 15px;
                    color: #ffffff !important;
                }
                .dg-card-value {
                    font-size: 22px !important;
                    font-weight: 800 !important;
                    margin: 4px 0 0 0;
                    letter-spacing: -0.5px;
                    color: #ffffff !important;
                }
                .dg-card-equivalent {
                    font-size: 13.5px !important;
                    font-weight: 600 !important;
                    margin-top: 2px;
                    margin-bottom: 4px;
                }
                .dg-card-subtext {
                    font-size: 11px;
                    color: #94a3b8 !important;
                    border-top: 1px solid rgba(255, 255, 255, 0.08);
                    padding-top: 6px;
                    margin-top: 4px;
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
                
                .dg-card-green .dg-card-equivalent, .dg-card-deepgreen .dg-card-equivalent { color: #10b981 !important; }
                .dg-card-red .dg-card-equivalent, .dg-card-pink .dg-card-equivalent { color: #ef4444 !important; }
                .dg-card-blue .dg-card-equivalent, .dg-card-teal .dg-card-equivalent { color: #3b82f6 !important; }
                .dg-card-orange .dg-card-equivalent { color: #f97316 !important; }
                .dg-card-purple .dg-card-equivalent, .dg-card-indigo .dg-card-equivalent { color: #8b5cf6 !important; }
                .dg-card-grey .dg-card-equivalent { color: #94a3b8 !important; }
                
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
                <i class="fa fa-th-large" style="color: #3b82f6;"></i> Resumen
            </h6>
            
            <div class="dg-card-grid">
                <!-- Cantidad de Ventas -->
                <div id="dg-sales-count-card" class="dg-card dg-card-purple" style="cursor: pointer;">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Cantidad de ventas</span>
                        <i class="fa fa-shopping-bag dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${data.sales_count}</div>
                    <div class="dg-card-subtext">
                        <span>Facturas emitidas en el periodo seleccionado</span>
                    </div>
                </div>

                <!-- Por cobrar -->
                <div class="dg-card dg-card-grey">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Por cobrar</span>
                        <i class="fa fa-clock-o dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${get_card_vals(t_cobrar, v_cobrar).usd}</div>
                    <div class="dg-card-equivalent">${get_card_vals(t_cobrar, v_cobrar).vef}</div>
                </div>

                <!-- Facturado -->
                <div class="dg-card dg-card-teal">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Facturado</span>
                        <i class="fa fa-dollar dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${get_card_vals(t_fact, v_fact).usd}</div>
                    <div class="dg-card-equivalent">${get_card_vals(t_fact, v_fact).vef}</div>
                </div>

                <!-- IVA -->
                <div class="dg-card dg-card-orange">
                    <div class="dg-card-header">
                        <span class="dg-card-title">IVA</span>
                        <i class="fa fa-percent dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${get_card_vals(t_iva, v_iva).usd}</div>
                    <div class="dg-card-equivalent">${get_card_vals(t_iva, v_iva).vef}</div>
                </div>

                <!-- IGTF -->
                <div class="dg-card dg-card-red">
                    <div class="dg-card-header">
                        <span class="dg-card-title">IGTF</span>
                        <i class="fa fa-university dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${get_card_vals(t_igtf, v_igtf).usd}</div>
                    <div class="dg-card-equivalent">${get_card_vals(t_igtf, v_igtf).vef}</div>
                </div>

                <!-- Disponibilidad -->
                <div class="dg-card dg-card-green">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Disponibilidad</span>
                        <i class="fa fa-check-circle dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${get_card_vals(t_disp, v_disp).usd}</div>
                    <div class="dg-card-equivalent">${get_card_vals(t_disp, v_disp).vef}</div>
                </div>

                <!-- Gastos -->
                <div class="dg-card dg-card-pink">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Gastos</span>
                        <i class="fa fa-arrow-down dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${get_card_vals(t_spent, v_spent).usd}</div>
                    <div class="dg-card-equivalent">${get_card_vals(t_spent, v_spent).vef}</div>
                </div>

                <!-- Utilidad -->
                <div class="dg-card dg-card-deepgreen">
                    <div class="dg-card-header">
                        <span class="dg-card-title">Utilidad</span>
                        <i class="fa fa-line-chart dg-card-icon"></i>
                    </div>
                    <div class="dg-card-value">${get_card_vals(t_util, v_util).usd}</div>
                    <div class="dg-card-equivalent">${get_card_vals(t_util, v_util).vef}</div>
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
        </div>
    `;

    frm.fields_dict.dashboard_html.$wrapper.html(html);

    // Bind clean jQuery click event to navigate to Sales Invoices list view
    frm.fields_dict.dashboard_html.$wrapper.find('#dg-sales-count-card').on('click', function() {
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

    // Bs NATIVO: el backend ya entrega cada columna en su bolívar real (campos *_vef);
    // no se reconvierte por la tasa de hoy (por eso cuadra con el panel ISP).
    const format_table_cell = (usd_val, vef_val) => {
        const usd_str = format_currency_ve(usd_val, "USD");
        const bs_str = format_currency_ve(vef_val, "VEF");
        return `<div>${usd_str}</div><div style="font-size: 10.5px; color: #a0aec0; font-weight: normal; margin-top: 2px;">${bs_str}</div>`;
    };

    let t_cobrar = 0, t_op = 0, t_iva_op = 0, t_fact = 0, t_iva = 0, t_neto = 0, t_ret_iva = 0, t_ret_islr = 0, t_igtf = 0, t_ganancia = 0, t_perdida = 0, t_disp = 0, t_spent = 0, t_util = 0;
    let v_cobrar = 0, v_op = 0, v_iva_op = 0, v_fact = 0, v_iva = 0, v_neto = 0, v_ret_iva = 0, v_ret_islr = 0, v_igtf = 0, v_ganancia = 0, v_perdida = 0, v_disp = 0, v_spent = 0, v_util = 0;

    let rows_html = rows.map(r => {
        // El TOTAL suma SOLO las raíces (indent 0) para no duplicar padres con hijos.
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

        const indent = (r.indent || 0) * 24;
        const name_html = frappe.utils.escape_html(r.branch);
        // Sangría con un span interno (margin): el CSS .dg-table td usa padding !important
        // y pisaría un padding-left en la celda.
        const branch_label = r.is_group
            ? `<span style="margin-left: ${indent}px;"><strong>${name_html}</strong></span>`
            : `<span style="margin-left: ${indent}px; opacity: 0.85;">${name_html}</span>`;
        return `
            <tr>
                <td>${branch_label}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.pending_to_collect, r.pending_to_collect_vef)}</td>
                <td style="text-align: right; font-weight: 600; color: #3b82f6;">${format_table_cell(r.payment_order, r.payment_order_vef)}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.payment_order_vat, r.payment_order_vat_vef)}</td>
                <td style="text-align: right; font-weight: 600; color: #3b82f6;">${format_table_cell(r.billed, r.billed_vef)}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.vat, r.vat_vef)}</td>
                <td style="text-align: right; font-weight: 600;">${format_table_cell(r.vat_after_withholding, r.vat_after_withholding_vef)}</td>
                <td style="text-align: right; font-weight: 600; color: #8b5cf6;">${format_table_cell(r.vat_withholding, r.vat_withholding_vef)}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.islr_withholding, r.islr_withholding_vef)}</td>
                <td style="text-align: right; color: var(--text-muted);">${format_table_cell(r.igtf, r.igtf_vef)}</td>
                <td style="text-align: right; color: ${(r.ganancia || 0) > 0 ? '#10b981' : 'var(--text-muted)'};">${format_table_cell(r.ganancia, r.ganancia_vef)}</td>
                <td style="text-align: right; color: ${(r.perdida || 0) > 0 ? '#ef4444' : 'var(--text-muted)'};">${format_table_cell(r.perdida, r.perdida_vef)}</td>
                <td style="text-align: right; font-weight: 700; color: ${r.availability >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(r.availability, r.availability_vef)}</td>
                <td style="text-align: right; font-weight: 600; color: #ef4444;">${format_table_cell(r.spent, r.spent_vef)}</td>
                <td style="text-align: right; font-weight: 700; color: ${r.profit >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(r.profit, r.profit_vef)}</td>
            </tr>
        `;
    }).join("");

    // Agregar fila de totales
    const total_row = `
        <tr style="background: #1f2733 !important; border-top: 2px solid #2d3748 !important; font-weight: 700; color: #ffffff !important;">
            <td><strong>TOTAL</strong></td>
            <td style="text-align: right;">${format_table_cell(t_cobrar, v_cobrar)}</td>
            <td style="text-align: right; color: #3b82f6;">${format_table_cell(t_op, v_op)}</td>
            <td style="text-align: right;">${format_table_cell(t_iva_op, v_iva_op)}</td>
            <td style="text-align: right; color: #3b82f6;">${format_table_cell(t_fact, v_fact)}</td>
            <td style="text-align: right;">${format_table_cell(t_iva, v_iva)}</td>
            <td style="text-align: right;">${format_table_cell(t_neto, v_neto)}</td>
            <td style="text-align: right; color: #8b5cf6;">${format_table_cell(t_ret_iva, v_ret_iva)}</td>
            <td style="text-align: right;">${format_table_cell(t_ret_islr, v_ret_islr)}</td>
            <td style="text-align: right; color: #ef4444;">${format_table_cell(t_igtf, v_igtf)}</td>
            <td style="text-align: right; color: #10b981;">${format_table_cell(t_ganancia, v_ganancia)}</td>
            <td style="text-align: right; color: #ef4444;">${format_table_cell(t_perdida, v_perdida)}</td>
            <td style="text-align: right; color: ${t_disp >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(t_disp, v_disp)}</td>
            <td style="text-align: right; color: #ef4444;">${format_table_cell(t_spent, v_spent)}</td>
            <td style="text-align: right; color: ${t_util >= 0 ? '#10b981' : '#ef4444'};">${format_table_cell(t_util, v_util)}</td>
        </tr>
    `;

    return rows_html + total_row;
}