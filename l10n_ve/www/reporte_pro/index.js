// Copyright (c) 2026, Domina Software and contributors

let dailySalesChartInstance = null;
let balanceDonutChartInstance = null;
let subGrowthChartInstance = null;
let subPlansChartInstance = null;
let subLocationsChartInstance = null;
let currentCurrency = "USD";
let allMunicipalities = [];
let calendarRangeDays = 7;
let calendarStartDate = null;
let cachedInstallations = [];
let cachedTasks = [];
let ispMapInstance = null;
let mapMarkersGroup = null;
let mapTileLayer = null;

const fmtUSD = (n) => "REF " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtVES = (n) => "Bs. " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

document.addEventListener("DOMContentLoaded", () => {
    // Initialize Lucide Icons
    if (typeof lucide !== "undefined") {
        lucide.createIcons();
    }

    // Setup date defaults (start of month to today)
    const today = new Date();
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
    
    // Inicializar Flatpickr en español
    const flatpickrConfig = {
        locale: "es",
        dateFormat: "Y-m-d",
        altInput: true,
        altFormat: "d/m/Y",
        altInputClass: "flatpickr-input form-control",
        onChange: () => {
            calendarStartDate = null;
            reloadDashboard();
        }
    };

    flatpickr("#filter-date-from", {
        ...flatpickrConfig,
        defaultDate: firstDay
    });

    flatpickr("#filter-date-to", {
        ...flatpickrConfig,
        defaultDate: today
    });

    // Inicializar mapa interactivo
    initLeafletMap();

    // Load filter options from backend
    loadFilterOptions(() => {
        // Fetch dashboard data with default filters
        reloadDashboard();
    });

    // Attach change events to filters
    const filterIds = ["filter-company", "filter-branch", "filter-router", "filter-state", "filter-municipality"];
    filterIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener("change", () => {
                if (id === "filter-state") {
                    updateMunicipalityDropdown();
                }
                reloadDashboard();
            });
        }
    });

    // Ventas del Día Filter Logic
    const salesPeriodSelect = document.getElementById("sales-period-select");
    const salesCustomContainer = document.getElementById("sales-custom-date-container");
    const salesCustomFrom = document.getElementById("sales-custom-from");
    const salesCustomTo = document.getElementById("sales-custom-to");

    if (salesPeriodSelect) {
        const todayStr = new Date().toISOString().split("T")[0];
        const firstDayStr = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split("T")[0];
        if (salesCustomFrom) salesCustomFrom.value = firstDayStr;
        if (salesCustomTo) salesCustomTo.value = todayStr;

        salesPeriodSelect.addEventListener("change", () => {
            const val = salesPeriodSelect.value;
            if (val === "custom") {
                if (salesCustomContainer) salesCustomContainer.style.display = "flex";
            } else {
                if (salesCustomContainer) salesCustomContainer.style.display = "none";
            }
            reloadSalesTable();
        });
    }

    if (salesCustomFrom) {
        salesCustomFrom.addEventListener("change", () => {
            reloadSalesTable();
        });
    }
    if (salesCustomTo) {
        salesCustomTo.addEventListener("change", () => {
            reloadSalesTable();
        });
    }

    // Dark Mode Toggle Logic
    const themeToggleBtn = document.getElementById("theme-toggle");
    if (themeToggleBtn) {
        const currentTheme = localStorage.getItem("theme");
        if (currentTheme === "dark") {
            document.body.classList.add("dark-theme");
            updateThemeButton(true);
        } else {
            updateThemeButton(false);
        }

        themeToggleBtn.addEventListener("click", () => {
            const isDark = document.body.classList.toggle("dark-theme");
            localStorage.setItem("theme", isDark ? "dark" : "light");
            updateThemeButton(isDark);
            
            // Dynamically update Leaflet map tile layer
            if (mapTileLayer) {
                const tileUrl = isDark 
                    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png' 
                    : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
                mapTileLayer.setUrl(tileUrl);
            }

            // Dynamically update ApexCharts theme options
            updateChartsTheme(isDark);
        });
    }

    function updateThemeButton(isDark) {
        if (!themeToggleBtn) return;
        const iconName = isDark ? "sun" : "moon";
        const text = isDark ? "Modo Claro" : "Modo Oscuro";
        themeToggleBtn.innerHTML = `<i data-lucide="${iconName}" style="width: 16px; height: 16px;"></i> <span>${text}</span>`;
        if (window.lucide) lucide.createIcons();
    }

    function updateChartsTheme(isDark) {
        const themeMode = isDark ? 'dark' : 'light';
        const textColor = isDark ? '#94a3b8' : '#64748b';
        const gridColor = isDark ? '#334155' : '#e2e8f0';

        const chartConfigs = [
            { chart: dailySalesChartInstance, type: 'sparkbar' },
            { chart: balanceDonutChartInstance, type: 'donut' },
            { chart: subGrowthChartInstance, type: 'growth' },
            { chart: subPlansChartInstance, type: 'plans' },
            { chart: subLocationsChartInstance, type: 'locations' }
        ];

        chartConfigs.forEach(({ chart, type }) => {
            if (!chart) return;

            let options = {
                theme: { mode: themeMode }
            };

            if (type === 'growth' || type === 'plans') {
                options.xaxis = {
                    labels: { style: { colors: textColor } }
                };
                options.yaxis = {
                    labels: { style: { colors: textColor } }
                };
                options.grid = {
                    borderColor: gridColor
                };
            } else if (type === 'locations') {
                options.legend = {
                    labels: { colors: textColor }
                };
                options.stroke = {
                    colors: isDark ? ['#0f172a'] : ['#ffffff']
                };
                options.plotOptions = {
                    pie: {
                        donut: {
                            labels: {
                                name: { color: textColor },
                                value: { color: isDark ? '#f8fafc' : '#0f172a' },
                                total: { color: textColor }
                            }
                        }
                    }
                };
            }

            try {
                chart.updateOptions(options);
            } catch (e) {
                console.error(`Error dynamically updating theme for chart ${type}:`, e);
            }
        });
    }

    // Calendar controls listeners
    const calBtnToday = document.getElementById("cal-btn-today");
    if (calBtnToday) {
        calBtnToday.addEventListener("click", () => {
            const today = new Date();
            const dayOfWeek = today.getDay();
            calendarStartDate = new Date(today);
            calendarStartDate.setDate(today.getDate() - dayOfWeek);
            renderCalendar(cachedTasks);
        });
    }

    const calBtnPrev = document.getElementById("cal-btn-prev");
    if (calBtnPrev) {
        calBtnPrev.addEventListener("click", () => {
            if (!calendarStartDate) {
                calendarStartDate = new Date();
                calendarStartDate.setDate(calendarStartDate.getDate() - calendarStartDate.getDay());
            }
            calendarStartDate.setDate(calendarStartDate.getDate() - calendarRangeDays);
            renderCalendar(cachedTasks);
        });
    }

    const calBtnNext = document.getElementById("cal-btn-next");
    if (calBtnNext) {
        calBtnNext.addEventListener("click", () => {
            if (!calendarStartDate) {
                calendarStartDate = new Date();
                calendarStartDate.setDate(calendarStartDate.getDate() - calendarStartDate.getDay());
            }
            calendarStartDate.setDate(calendarStartDate.getDate() + calendarRangeDays);
            renderCalendar(cachedTasks);
        });
    }

    // Calendar range switchers
    [7, 15, 30].forEach(days => {
        const btn = document.getElementById(`cal-btn-range-${days}`);
        if (btn) {
            btn.addEventListener("click", () => {
                calendarRangeDays = days;
                [7, 15, 30].forEach(d => {
                    const b = document.getElementById(`cal-btn-range-${d}`);
                    if (b) {
                        if (d === days) {
                            b.classList.add("active");
                        } else {
                            b.classList.remove("active");
                        }
                    }
                });
                renderCalendar(cachedTasks);
            });
        }
    });

    // Close modal listeners
    const closeBtn = document.getElementById("modal-close-btn");
    if (closeBtn) closeBtn.addEventListener("click", () => window.closeInstallationModal());
    
    const closeActionBtn = document.getElementById("modal-close-action-btn");
    if (closeActionBtn) closeActionBtn.addEventListener("click", () => window.closeInstallationModal());
    
    const modalOverlay = document.getElementById("installation-modal");
    if (modalOverlay) {
        modalOverlay.addEventListener("click", (e) => {
            if (e.target === modalOverlay) {
                window.closeInstallationModal();
            }
        });
    }

    // Add task form submit listener
    const addTaskForm = document.getElementById("add-task-form");
    if (addTaskForm) {
        addTaskForm.addEventListener("submit", (e) => {
            e.preventDefault();
            const subject = document.getElementById("add-task-subject").value;
            const description = document.getElementById("add-task-desc").value;
            const date = document.getElementById("add-task-date").value;
            
            const url = "/api/method/l10n_ve.www.reporte_pro.index.create_task";
            fetch(url, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Frappe-CSRF-Token": window.csrf_token
                },
                body: JSON.stringify({ subject, description, date })
            })
            .then(res => res.json())
            .then(res => {
                if (res.message && res.message.status === "success") {
                    window.closeAddTaskModal();
                    reloadDashboard();
                } else {
                    alert("Error guardando la tarea: " + (res._server_messages || "Error desconocido"));
                }
            })
            .catch(err => {
                console.error("Error creating task:", err);
                alert("Error de conexión al guardar la tarea.");
            });
        });
    }

    // Add close buttons listeners for task modals
    const addTaskCloseBtn = document.getElementById("add-task-close-btn");
    if (addTaskCloseBtn) addTaskCloseBtn.addEventListener("click", () => window.closeAddTaskModal());
    const addTaskCancelBtn = document.getElementById("add-task-cancel-btn");
    if (addTaskCancelBtn) addTaskCancelBtn.addEventListener("click", () => window.closeAddTaskModal());
    
    const taskDetailCloseBtn = document.getElementById("task-detail-close-btn");
    if (taskDetailCloseBtn) taskDetailCloseBtn.addEventListener("click", () => window.closeTaskDetailModal());
    const taskDetailCloseActionBtn = document.getElementById("task-detail-close-action-btn");
    if (taskDetailCloseActionBtn) taskDetailCloseActionBtn.addEventListener("click", () => window.closeTaskDetailModal());

    const addTaskModalOverlay = document.getElementById("add-task-modal");
    if (addTaskModalOverlay) {
        addTaskModalOverlay.addEventListener("click", (e) => {
            if (e.target === addTaskModalOverlay) window.closeAddTaskModal();
        });
    }
    const taskDetailModalOverlay = document.getElementById("task-detail-modal");
    if (taskDetailModalOverlay) {
        taskDetailModalOverlay.addEventListener("click", (e) => {
            if (e.target === taskDetailModalOverlay) window.closeTaskDetailModal();
        });
    }
});

function loadFilterOptions(callback) {
    // Use GET — no CSRF token required for read-only endpoints
    const url = "/api/method/l10n_ve.www.reporte_pro.index.get_filter_options";
    fetch(url, { method: "GET", credentials: "same-origin" })
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(data => {
            const options = data.message;
            if (options) {
                populateSelect("filter-company", options.companies, false);
                populateSelect("filter-branch", options.branches, true);
                populateSelect("filter-router", options.routers, true);
                populateSelect("filter-state", options.states, true);
                
                allMunicipalities = options.municipalities || [];
                updateMunicipalityDropdown();
            }
            callback();
        })
        .catch(e => {
            console.error("Error cargando opciones de filtro:", e);
            callback();
        });
}

function updateMunicipalityDropdown() {
    const stateEl = document.getElementById("filter-state");
    const selectedState = stateEl ? stateEl.value : "";
    let filtered = allMunicipalities;
    if (selectedState) {
        filtered = allMunicipalities.filter(m => m.state === selectedState);
    }
    populateSelect("filter-municipality", filtered, true);
}

function populateSelect(id, list, addAllOption) {
    const select = document.getElementById(id);
    if (!select) return;
    
    let html = "";
    if (addAllOption) {
        html += `<option value="">${id.includes('branch') ? 'Todas' : 'Todos'}</option>`;
    }
    
    if (list && list.length > 0) {
        list.forEach(item => {
            html += `<option value="${item.value}">${item.label}</option>`;
        });
    } else if (!addAllOption) {
        html += `<option value="">Sin opciones</option>`;
    }
    select.innerHTML = html;
}

function reloadDashboard() {
    // Keep calendarStartDate to avoid jumping calendar views on save
    const filters = {
        company: document.getElementById("filter-company").value,
        branch: document.getElementById("filter-branch").value,
        router: document.getElementById("filter-router").value,
        state: document.getElementById("filter-state").value,
        municipality: document.getElementById("filter-municipality").value,
        currency: "USD",
        date_from: document.getElementById("filter-date-from").value,
        date_to: document.getElementById("filter-date-to").value
    };

    fetchDashboardData(filters, (data) => {
        let dashboardData = data;
        if (!dashboardData) {
            console.log("No data returned from backend, using high-fidelity mock data.");
            dashboardData = getMockData();
        }
        window.lastDashboardData = dashboardData;
        renderDashboard(dashboardData);
    });
}

// =========================================================================
// API & RENDER CONTROLLER
// =========================================================================

function fetchDashboardData(filters, callback) {
    // Use GET with query params — no CSRF token required for read-only endpoints
    const apiMethod = "l10n_ve.www.reporte_pro.index.get_dashboard_data";
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") params.append(k, v); });
    const url = `/api/method/${apiMethod}?${params.toString()}`;
    fetch(url, { method: "GET", credentials: "same-origin" })
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(data => {
            if (data.message) {
                callback(data.message);
            } else {
                callback(null);
            }
        })
        .catch(err => {
            console.error("Error cargando datos del dashboard:", err);
            callback(null);
        });
}

function renderDashboard(data) {
    if (data && data.exchange_rate) {
        window.exchange_rate = parseFloat(data.exchange_rate);
    }
    if (!window.exchange_rate || isNaN(window.exchange_rate)) {
        window.exchange_rate = 1.0;
    }
    const kpis = data.kpi_cards || {};

    // ── 1. KPI Cards ──────────────────────────────────────────────────────

    // Por Cobrar
    const pendienteUsd = parseFloat(kpis.total_pendiente_usd || kpis.grand_total || 0);
    const pendienteVef = parseFloat(kpis.total_pendiente_vef || 0);
    const count = kpis.unpaid_orders_count || 0;
    
    const displayPendiente = currentCurrency === "VEF" ? fmtVES(pendienteVef) : fmtUSD(pendienteUsd);
    const subtextPendiente = currentCurrency === "VEF" ? fmtUSD(pendienteUsd) : fmtVES(pendienteVef);
    
    setText("kpi-pendiente-val", displayPendiente);
    setText("kpi-pendiente-count", `Equiv. ${subtextPendiente} (Tasa BCV: ${window.exchange_rate.toFixed(2)})<br><span style="opacity: 0.8;">${count} factura${count !== 1 ? "s" : ""} pendiente${count !== 1 ? "s" : ""}</span>`);

    // Cobrado REF ($)
    const cobUsdTotal = parseFloat(kpis.collected_usd_total || 0);
    const cobUsdBase  = parseFloat(kpis.collected_usd_base  || 0);
    const cobUsdTax   = parseFloat(kpis.collected_usd_tax   || 0);
    const cobUsdIgtf  = parseFloat(kpis.collected_usd_igtf  || 0);
    const cobUsdTotalVes = cobUsdTotal * window.exchange_rate;
    
    setText("kpi-cobrado-usd-val", fmtUSD(cobUsdTotal));
    setText("kpi-cobrado-usd-sub", `Equiv. ${fmtVES(cobUsdTotalVes)} (Tasa BCV: ${window.exchange_rate.toFixed(2)})<br>
        <span style="opacity: 0.8; font-size: 10px; display: block; margin-top: 4px;">Base: ${fmtUSD(cobUsdBase)}</span>
        <span style="opacity: 0.8; font-size: 10px; display: block; margin-top: 2px;">IVA: ${fmtUSD(cobUsdTax)}</span>
        <span style="opacity: 0.8; font-size: 10px; display: block; margin-top: 2px;">IGTF: ${fmtUSD(cobUsdIgtf)}</span>`);

    // Cobrado Bs.
    const cobVesTotal = parseFloat(kpis.collected_ves_total || 0);
    const cobVesBase  = parseFloat(kpis.collected_ves_base  || 0);
    const cobVesTax   = parseFloat(kpis.collected_ves_tax   || 0);
    const cobVesIgtf  = parseFloat(kpis.collected_ves_igtf  || 0);
    const cobVesTotalUsd = parseFloat(kpis.collected_ves_equivalent_usd || 0);
    const implicitRate = cobVesTotalUsd > 0 ? cobVesTotal / cobVesTotalUsd : 0;
    const rateText = implicitRate > 0 ? ` (Tasa Promedio: ${implicitRate.toFixed(2)})` : '';
    
    setText("kpi-cobrado-ves-val", fmtVES(cobVesTotal));
    setText("kpi-cobrado-ves-sub", `Equiv. ${fmtUSD(cobVesTotalUsd)}${rateText}<br>
        <span style="opacity: 0.8; font-size: 10px; display: block; margin-top: 4px;">Base: ${fmtVES(cobVesBase)}</span>
        <span style="opacity: 0.8; font-size: 10px; display: block; margin-top: 2px;">IVA: ${fmtVES(cobVesTax)}</span>
        <span style="opacity: 0.8; font-size: 10px; display: block; margin-top: 2px;">IGTF: ${fmtVES(cobVesIgtf)}</span>`);

    // Gastos
    const gastosUsd = parseFloat(kpis.total_expenses_usd || 0);
    const gastosVef = parseFloat(kpis.total_expenses_vef || 0);
    const gastosUsdEquivVes = gastosUsd * window.exchange_rate;
    const gastosVefEquivUsd = gastosVef / (window.exchange_rate || 1);
    
    setText("kpi-gastos-usd-val", fmtUSD(gastosUsd));
    setText("kpi-gastos-ves-val", `Equiv. ${fmtVES(gastosUsdEquivVes)} (Tasa BCV: ${window.exchange_rate.toFixed(2)})<br><span style="display: block; margin-top: 4px; font-weight: 600; color: var(--text-primary); font-size: 13px;">${fmtVES(gastosVef)}</span>Equiv. ${fmtUSD(gastosVefEquivUsd)} (Tasa BCV: ${window.exchange_rate.toFixed(2)})`);

    // Disponible USD & Bs.
    const dispUsd = parseFloat(kpis.available_usd !== undefined ? kpis.available_usd : cobUsdTotal - gastosUsd);
    const dispVes = parseFloat(kpis.available_vef !== undefined ? kpis.available_vef : cobVesTotal - gastosVef);
    const dispUsdEquivVes = dispUsd * window.exchange_rate;
    const dispVesEquivUsd = dispVes / (window.exchange_rate || 1);
    
    setText("kpi-disp-usd-val", fmtUSD(dispUsd));
    setText("kpi-disp-usd-sub", `Equiv. ${fmtVES(dispUsdEquivVes)} (Tasa BCV: ${window.exchange_rate.toFixed(2)})<br><span style="opacity: 0.8;">Cobrado − Gastos</span>`);
    setText("kpi-disp-ves-val", fmtVES(dispVes));
    setText("kpi-disp-ves-sub", `Equiv. ${fmtUSD(dispVesEquivUsd)} (Tasa BCV: ${window.exchange_rate.toFixed(2)})<br><span style="opacity: 0.8;">Cobrado − Gastos</span>`);

    // ── 2. Bottom balance card (legacy) ───────────────────────────────────
    const mainBalance = currentCurrency === "VEF" ? fmtVES(dispVes) : fmtUSD(dispUsd);
    const subBalance = currentCurrency === "VEF" ? fmtUSD(dispVesEquivUsd) : fmtVES(dispUsdEquivVes);
    
    setText("balance-amount-val", mainBalance);
    setText("balance-amount-sub", `Equiv. ${subBalance}`);

    // Donut: cobrado vs gastos in selected currency
    const totalCollectedUsd = parseFloat(kpis.collected_total_usd || 0);
    const totalCollectedVef = parseFloat(kpis.collected_total_vef || 0);
    const ingresos = currentCurrency === "VEF" ? totalCollectedVef : totalCollectedUsd;
    const egresos  = currentCurrency === "VEF" ? gastosVef        : gastosUsd;
    initBalanceChart(ingresos, egresos);

    // ── 3. Monthly expenses breakdown ─────────────────────────────────────
    renderExpenses(data.expenses_by_category, egresos);

    // ── 4. Sales Summary & Trends ─────────────────────────────────────────
    renderSalesSummary(data.trend, ingresos, kpis);

    // ── 5. Ventas del día table + KPI tax cards ──────────────────────────
    const salesPeriodSelect = document.getElementById("sales-period-select");
    const currentSalesPeriod = salesPeriodSelect ? salesPeriodSelect.value : "today";
    if (currentSalesPeriod === "today") {
        renderSalesTodayTable(data.sales_today);
    } else {
        reloadSalesTable();
    }
    renderTaxKpiCards(data.tax_totals);

    // ── 6. Calendar (tasks) ──────────────────────────────────────────────
    cachedTasks = data.calendar_tasks || [];
    renderCalendar(cachedTasks);

    // ── 7. Subscriber & Business Analytics ─────────────────────────────────
    renderSubscriberAnalytics(data.customer_analytics);

    // Re-init icons for any newly inserted lucide elements
    if (window.lucide) lucide.createIcons();
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = value;
}


function formatMoney(amount) {
    const symbol = currentCurrency === "VEF" ? "Bs. " : "REF ";
    return symbol + parseFloat(amount).toLocaleString('es-ES', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

// =========================================================================
// SUBSCRIBER & BUSINESS ANALYTICS RENDERING
// =========================================================================

function renderSubscriberAnalytics(analytics) {
    if (!analytics) return;

    // 1. Process Service Status Chart & KPIs
    const statusChart = analytics.status_chart || { labels: [], values: [] };
    let totalServices = 0;
    let activeServices = 0;
    let suspendedServices = 0;

    for (let i = 0; i < statusChart.labels.length; i++) {
        const label = statusChart.labels[i] || "";
        const val = parseInt(statusChart.values[i] || 0);
        totalServices += val;

        const norm = label.toLowerCase();
        if (norm.includes("acti")) {
            activeServices += val;
        } else if (norm.includes("suspe") || norm.includes("moro")) {
            suspendedServices += val;
        }
    }

    const activePct = totalServices > 0 ? Math.round((activeServices / totalServices) * 100) : 0;
    const suspendedPct = totalServices > 0 ? Math.round((suspendedServices / totalServices) * 100) : 0;

    setText("sub-active-val", activeServices);
    setText("sub-active-pct", `${activePct}% del total (${totalServices} servicios)`);
    setText("sub-suspended-val", suspendedServices);
    setText("sub-suspended-pct", `${suspendedPct}% del total`);

    // 2. New Customer Growth
    const newCust = analytics.new_customers_data || { new_this_month: 0, average: 0, trend: "up" };
    setText("sub-news-val", newCust.new_this_month);
    setText("sub-news-avg", `Promedio: ${newCust.average || 0} / mes`);

    // 3. Churn Data
    const churn = analytics.churn_data || { current_rate: 0, average_rate: 0, churned_this_month: 0, trend: "down" };
    setText("sub-churn-val", `${churn.current_rate || 0}%`);
    setText("sub-churn-avg", `Bajas: ${churn.churned_this_month || 0} (Promedio: ${churn.average_rate || 0}%)`);

    // 4. Render Charts & Map
    initSubscriberGrowthChart(analytics.growth_chart);
    initSubscriberPlansChart(analytics.plan_distribution);
    initSubscriberLocationsChart(analytics.location_chart);
    updateMapData(analytics);
}

function initSubscriberGrowthChart(growthData) {
    if (subGrowthChartInstance) {
        subGrowthChartInstance.destroy();
        subGrowthChartInstance = null;
    }
    const container = document.querySelector("#panel-sub-growth");
    if (!container) return;
    container.innerHTML = "";

    const labels = growthData ? (growthData.labels || []) : [];
    const values = (growthData && growthData.datasets && growthData.datasets[0]) ? (growthData.datasets[0].values || []) : [];

    const isDark = document.body.classList.contains("dark-theme");

    const options = {
        series: [{
            name: 'Servicios Nuevos',
            data: values
        }],
        chart: {
            type: 'area',
            height: 250,
            toolbar: { show: false },
            animations: { enabled: true },
            background: 'transparent'
        },
        stroke: {
            curve: 'smooth',
            width: 2.5
        },
        fill: {
            type: 'gradient',
            gradient: {
                shadeIntensity: 1,
                opacityFrom: 0.45,
                opacityTo: 0.05,
                stops: [0, 100]
            }
        },
        colors: ['#2563eb'],
        xaxis: {
            categories: labels,
            labels: {
                style: {
                    colors: isDark ? '#94a3b8' : '#64748b',
                    fontSize: '11px'
                }
            },
            axisBorder: { show: false },
            axisTicks: { show: false }
        },
        yaxis: {
            labels: {
                style: {
                    colors: isDark ? '#94a3b8' : '#64748b',
                    fontSize: '11px'
                }
            }
        },
        grid: {
            borderColor: isDark ? '#334155' : '#e2e8f0',
            strokeDashArray: 4
        },
        theme: {
            mode: isDark ? 'dark' : 'light'
        },
        tooltip: {
            theme: isDark ? 'dark' : 'light'
        }
    };

    subGrowthChartInstance = new ApexCharts(container, options);
    subGrowthChartInstance.render();
}

function initSubscriberPlansChart(planDistribution) {
    if (subPlansChartInstance) {
        subPlansChartInstance.destroy();
        subPlansChartInstance = null;
    }
    const container = document.querySelector("#panel-sub-plans");
    if (!container) return;
    container.innerHTML = "";

    const labels = planDistribution ? (planDistribution.labels || []) : [];
    const values = planDistribution ? (planDistribution.values || []) : [];

    const isDark = document.body.classList.contains("dark-theme");

    const options = {
        series: [{
            name: 'Servicios',
            data: values
        }],
        chart: {
            type: 'bar',
            height: 250,
            toolbar: { show: false },
            background: 'transparent'
        },
        plotOptions: {
            bar: {
                borderRadius: 4,
                horizontal: true,
                barHeight: '70%'
            }
        },
        colors: ['#06b6d4'],
        xaxis: {
            categories: labels,
            labels: {
                style: {
                    colors: isDark ? '#94a3b8' : '#64748b',
                    fontSize: '11px'
                }
            },
            axisBorder: { show: false },
            axisTicks: { show: false }
        },
        yaxis: {
            labels: {
                style: {
                    colors: isDark ? '#94a3b8' : '#64748b',
                    fontSize: '11px'
                }
            }
        },
        grid: {
            borderColor: isDark ? '#334155' : '#e2e8f0',
            strokeDashArray: 4
        },
        theme: {
            mode: isDark ? 'dark' : 'light'
        },
        tooltip: {
            theme: isDark ? 'dark' : 'light'
        }
    };

    subPlansChartInstance = new ApexCharts(container, options);
    subPlansChartInstance.render();
}

function initSubscriberLocationsChart(locationChart) {
    if (subLocationsChartInstance) {
        subLocationsChartInstance.destroy();
        subLocationsChartInstance = null;
    }
    const container = document.querySelector("#panel-sub-locations");
    if (!container) return;
    container.innerHTML = "";

    const labels = locationChart ? (locationChart.labels || []) : [];
    const values = locationChart ? (locationChart.values || []) : [];

    const isDark = document.body.classList.contains("dark-theme");

    const options = {
        series: values,
        chart: {
            type: 'donut',
            height: 250,
            background: 'transparent'
        },
        labels: labels,
        colors: ['#2563eb', '#10b981', '#7c3aed', '#f59e0b', '#ec4899', '#06b6d4', '#64748b'],
        stroke: {
            show: true,
            colors: isDark ? ['#0f172a'] : ['#ffffff'],
            width: 2
        },
        plotOptions: {
            pie: {
                donut: {
                    size: '65%',
                    labels: {
                        show: true,
                        name: {
                            show: true,
                            fontSize: '13px',
                            color: isDark ? '#94a3b8' : '#64748b'
                        },
                        value: {
                            show: true,
                            fontSize: '18px',
                            fontWeight: 'bold',
                            color: isDark ? '#f8fafc' : '#0f172a'
                        },
                        total: {
                            show: true,
                            label: 'Total',
                            color: isDark ? '#94a3b8' : '#64748b'
                        }
                    }
                }
            }
        },
        dataLabels: { enabled: false },
        legend: {
            show: true,
            position: 'bottom',
            labels: {
                colors: isDark ? '#94a3b8' : '#64748b'
            }
        },
        theme: {
            mode: isDark ? 'dark' : 'light'
        },
        tooltip: {
            theme: isDark ? 'dark' : 'light'
        }
    };

    subLocationsChartInstance = new ApexCharts(container, options);
    subLocationsChartInstance.render();
}

// =========================================================================
// COMPONENTS RENDERING
// =========================================================================

// Sales Bar Chart
function initSalesChart(labels, values) {
    if (dailySalesChartInstance) {
        dailySalesChartInstance.destroy();
        dailySalesChartInstance = null;
    }
    const container = document.querySelector("#daily-sales-chart");
    if (container) container.innerHTML = "";

    const options = {
        series: [{
            name: 'Ventas',
            data: values
        }],
        chart: {
            type: 'bar',
            height: 75,
            sparkline: { enabled: true },
            animations: { enabled: true }
        },
        plotOptions: {
            bar: {
                borderRadius: 3,
                columnWidth: '55%',
                colors: {
                    ranges: [{
                        from: 0,
                        to: 9999999,
                        color: '#1e3a8a'
                    }]
                }
            }
        },
        xaxis: {
            categories: labels
        },
        tooltip: { enabled: false }
    };

    dailySalesChartInstance = new ApexCharts(document.querySelector("#daily-sales-chart"), options);
    dailySalesChartInstance.render();
}

// Balance Donut Chart
function initBalanceChart(income, expenses) {
    if (balanceDonutChartInstance) {
        balanceDonutChartInstance.destroy();
        balanceDonutChartInstance = null;
    }
    const container = document.querySelector("#balance-donut-chart");
    if (container) container.innerHTML = "";

    const options = {
        series: [income, expenses],
        chart: {
            type: 'donut',
            width: 120,
            height: 120,
            sparkline: { enabled: true }
        },
        labels: ['Ingresos', 'Gastos'],
        colors: ['#10b981', '#ef4444'],
        plotOptions: {
            pie: {
                donut: {
                    size: '72%',
                    labels: {
                        show: false
                    }
                }
            }
        },
        dataLabels: { enabled: false },
        legend: { show: false },
        tooltip: {
            enabled: true,
            y: {
                formatter: function(val) {
                    return formatMoney(val);
                }
            }
        }
    };

    balanceDonutChartInstance = new ApexCharts(document.querySelector("#balance-donut-chart"), options);
    balanceDonutChartInstance.render();
}

// Expenses List
function renderExpenses(categories, totalExpenses) {
    const wrapper = document.querySelector(".expenses-chart-wrapper");
    const totalVal = document.getElementById("expenses-total-val");
    if (!wrapper) return;

    const totalExpensesUsd = currentCurrency === "VEF" ? totalExpenses / window.exchange_rate : totalExpenses;
    const totalExpensesVes = currentCurrency === "VEF" ? totalExpenses : totalExpenses * window.exchange_rate;
    totalVal.innerText = fmtUSD(totalExpensesUsd) + " | " + fmtVES(totalExpensesVes);

    let html = "";
    if (categories && categories.length > 0) {
        categories.slice(0, 3).forEach(item => {
            const amountUsd = item.amount_usd;
            const amountVes = item.amount_ves;
            const refAmt = currentCurrency === "VEF" ? amountVes : amountUsd;
            const pct = totalExpenses > 0 ? Math.round((refAmt / totalExpenses) * 100) : 0;
            
            let categoryName = item.category || "";
            if (categoryName.toUpperCase() === "INTERCOMPANY") {
                categoryName = "INTERCOMPAÑÍA";
            }
            
            html += `
                <div class="expense-item">
                    <div class="expense-info">
                        <span>${categoryName}</span>
                        <span>${fmtUSD(amountUsd)} | ${fmtVES(amountVes)}</span>
                    </div>
                    <div class="progress-bar-wrapper">
                        <div class="progress-bar-fill blue" style="width: ${pct}%;"></div>
                    </div>
                </div>
            `;
        });
    } else {
        // Fallback mockup
        const mockList = [
            { category: "Combustible", amount: totalExpenses * 0.4 },
            { category: "Repuestos FTTH", amount: totalExpenses * 0.2 },
            { category: "Salarios", amount: totalExpenses * 0.4 }
        ];
        mockList.forEach(item => {
            const amountUsd = currentCurrency === "VEF" ? item.amount / window.exchange_rate : item.amount;
            const amountVes = currentCurrency === "VEF" ? item.amount : item.amount * window.exchange_rate;
            html += `
                <div class="expense-item">
                    <div class="expense-info">
                        <span>${item.category}</span>
                        <span>${fmtUSD(amountUsd)} | ${fmtVES(amountVes)}</span>
                    </div>
                    <div class="progress-bar-wrapper">
                        <div class="progress-bar-fill blue" style="width: 40%;"></div>
                    </div>
                </div>
            `;
        });
    }
    wrapper.innerHTML = html;
}

// Sales Summary & Trends
function renderSalesSummary(trend, totalMonthly, kpis) {
    let labels = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
    let values = [3500, 4100, 4800, 4200, 5200, 4600, 4500];
    
    let weeklyTotal = 18750.00;
    
    if (trend && trend.datasets && trend.datasets.length > 0) {
        // Find dataset for 'Cobrado' (payments received)
        const cobradoDs = trend.datasets.find(ds => ds.name === 'Cobrado');
        if (cobradoDs && cobradoDs.values && cobradoDs.values.length > 0) {
            const rawVals = cobradoDs.values;
            const rawLabels = trend.labels || [];
            
            // Take the last 7 items
            const count = Math.min(7, rawVals.length);
            values = rawVals.slice(-count);
            labels = rawLabels.slice(-count).map(l => {
                const d = new Date(l + "T00:00:00");
                return d.toLocaleDateString('es-ES', { weekday: 'short' });
            });

            // Calculate weekly total based on these 7 days
            weeklyTotal = values.reduce((a, b) => a + b, 0);
        }
    }

    // Set text values
    const dailyTotal = values[values.length - 1] || 0;
    const dailyTotalUsd = currentCurrency === "VEF" ? dailyTotal / window.exchange_rate : dailyTotal;
    const dailyTotalVes = currentCurrency === "VEF" ? dailyTotal : dailyTotal * window.exchange_rate;
    const dailyEl = document.getElementById("daily-sales-val");
    if (dailyEl) {
        dailyEl.innerText = "Hoy: " + fmtUSD(dailyTotalUsd) + " | " + fmtVES(dailyTotalVes);
    }

    const weeklyTotalUsd = currentCurrency === "VEF" ? weeklyTotal / window.exchange_rate : weeklyTotal;
    const weeklyTotalVes = currentCurrency === "VEF" ? weeklyTotal : weeklyTotal * window.exchange_rate;
    document.getElementById("weekly-sales-val").innerText = fmtUSD(weeklyTotalUsd) + " | " + fmtVES(weeklyTotalVes);
    
    const monthlyTotalUsd = currentCurrency === "VEF" ? totalMonthly / window.exchange_rate : totalMonthly;
    const monthlyTotalVes = currentCurrency === "VEF" ? totalMonthly : totalMonthly * window.exchange_rate;
    document.getElementById("monthly-sales-val").innerText = fmtUSD(monthlyTotalUsd) + " | " + fmtVES(monthlyTotalVes);
    
    // Update metadata (Base + IVA)
    const weeklyBaseUsd = weeklyTotalUsd / 1.16;
    const weeklyTaxUsd = weeklyTotalUsd - weeklyBaseUsd;
    const weeklyBaseVes = weeklyTotalVes / 1.16;
    const weeklyTaxVes = weeklyTotalVes - weeklyBaseVes;
    const weeklyMetaEl = document.getElementById("weekly-sales-meta");
    if (weeklyMetaEl) {
        weeklyMetaEl.innerText = `Base: ${fmtUSD(weeklyBaseUsd)} (${fmtVES(weeklyBaseVes)}) | IVA: ${fmtUSD(weeklyTaxUsd)} (${fmtVES(weeklyTaxVes)})`;
    }

    const mBaseUsd = parseFloat(kpis.collected_usd_base || 0);
    const mTaxUsd = parseFloat(kpis.collected_usd_tax || 0);
    const mBaseVes = parseFloat(kpis.collected_ves_base || 0);
    const mTaxVes = parseFloat(kpis.collected_ves_tax || 0);
    const monthlyMetaEl = document.getElementById("monthly-sales-meta");
    if (monthlyMetaEl) {
        monthlyMetaEl.innerText = `Base: ${fmtUSD(mBaseUsd)} (${fmtVES(mBaseVes)}) | IVA: ${fmtUSD(mTaxUsd)} (${fmtVES(mTaxVes)})`;
    }
    
    // Render the bar chart
    initSalesChart(labels, values);
}

function reloadSalesTable() {
    const company = document.getElementById("filter-company").value;
    const period = document.getElementById("sales-period-select").value;
    const dateFrom = document.getElementById("sales-custom-from").value;
    const dateTo = document.getElementById("sales-custom-to").value;

    const titleEl = document.getElementById("sales-card-title");
    if (titleEl) {
        if (period === "today") titleEl.innerText = "Ventas del Día";
        else if (period === "week") titleEl.innerText = "Ventas de la Semana";
        else if (period === "month") titleEl.innerText = "Ventas del Mes";
        else if (period === "custom") titleEl.innerText = "Ventas del Período";
    }

    if (period === "today" && window.lastDashboardData && window.lastDashboardData.sales_today) {
        renderSalesTodayTable(window.lastDashboardData.sales_today);
        return;
    }

    const params = new URLSearchParams({ company, period });
    if (period === "custom") {
        if (dateFrom) params.append("date_from", dateFrom);
        if (dateTo) params.append("date_to", dateTo);
    }

    const tbody = document.getElementById("sales-today-tbody");
    if (tbody) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center" style="padding: 20px; text-align: center; color: var(--text-secondary);">Cargando ventas...</td></tr>`;
    }

    fetch(`/api/method/l10n_ve.www.reporte_pro.index.get_sales_data?${params.toString()}`, {
        method: "GET",
        credentials: "same-origin"
    })
    .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    })
    .then(data => {
        const sales = data.message || [];
        renderSalesTodayTable(sales);
    })
    .catch(err => {
        console.error("Error cargando ventas:", err);
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center" style="padding: 20px; text-align: center; color: var(--danger);">Error al cargar las ventas.</td></tr>`;
        }
    });
}

// Ventas del Día Table
function renderSalesTodayTable(sales) {
    const tbody = document.getElementById("sales-today-tbody");
    if (!tbody) return;

    let list = sales || [];
    if (list.length === 0) {
        const periodSelect = document.getElementById("sales-period-select");
        const periodText = periodSelect && periodSelect.value !== "today" ? "en este período" : "el día de hoy";
        tbody.innerHTML = `<tr><td colspan="5" class="text-center" style="padding: 20px; text-align: center; color: var(--text-secondary);">No hay ventas registradas ${periodText}.</td></tr>`;
        return;
    }

    const fmtUSD = (n) => "REF " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const fmtVES = (n) => "Bs. " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    let html = "";
    list.forEach(row => {
        // Status styles
        const statusBadge = row.status === "Paid" ? "success" : 
                            row.status === "Unpaid" ? "warning" : 
                            row.status === "Overdue" ? "danger" : "info";
                            
        const statusLabel = row.status === "Paid" ? "Pagado" : 
                            row.status === "Unpaid" ? "Por Cobrar" : 
                            row.status === "Overdue" ? "Vencido" : row.status;
                            
        // Format emission date cleanly
        let dateStr = row.posting_date || "—";
        
        html += `
            <tr>
                <td><a href="/app/sales-invoice/${row.invoice_id}" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">${row.invoice_id}</a></td>
                <td>${row.client}</td>
                <td>${dateStr}</td>
                <td>
                    <div style="font-weight: 600; color: var(--text-primary);">${fmtUSD(row.amount_usd)}</div>
                    <div style="font-size: 11px; color: var(--text-secondary);">${fmtVES(row.amount_ves)}</div>
                </td>
                <td><span class="badge ${statusBadge}">${statusLabel}</span></td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

// IVA del Día & IGTF del Día KPI cards
// Populates the split IVA and IGTF KPI cards
function renderTaxKpiCards(taxTotals) {
    const t = taxTotals || {};
    const fmtUSD = (n) => "REF " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const fmtVES = (n) => "Bs. " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    setText("kpi-iva-val",  fmtUSD(t.iva_usd));
    setText("kpi-iva-sub",  `Equiv. ${fmtVES(t.iva_ves)} (Tasa BCV: ${window.exchange_rate.toFixed(2)})`);
    setText("kpi-igtf-val", fmtUSD(t.igtf_usd));
    setText("kpi-igtf-sub", `Equiv. ${fmtVES(t.igtf_ves)} (Tasa BCV: ${window.exchange_rate.toFixed(2)})`);
}

// =========================================================================
// MOCK DATA (FALLBACK)
// =========================================================================

const WORK_ORDERS_MOCK = [];

function getMockData() {
    return {
        kpi_cards: {
            available_usd: 18220.00,
            collected_total_usd: 25000.00,
            total_expenses_usd: 6780.00
        },
        expenses_by_category: [
            { category: "Combustible", amount_usd: 2712.00 },
            { category: "Repuestos FTTH", amount_usd: 1356.00 },
            { category: "Salarios", amount_usd: 2712.00 }
        ],
        trend: {
            labels: ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'],
            datasets: [{
                name: 'Cobrado',
                values: [3500, 4100, 4800, 4200, 5200, 4600, 4500]
            }]
        },
        payments: {
            recent_payments: []
        }
    };
}

// =========================================================================
// STATIC COMPONENTS (CALENDAR & CHAT)
// =========================================================================

function getCalendarPeriodText(startDate, rangeDays) {
    if (!startDate) return "";
    
    const endDate = new Date(startDate);
    endDate.setDate(startDate.getDate() + rangeDays - 1);
    
    const startMonth = startDate.toLocaleDateString("es-ES", { month: "long" });
    const endMonth = endDate.toLocaleDateString("es-ES", { month: "long" });
    const startYear = startDate.getFullYear();
    const endYear = endDate.getFullYear();
    
    const capStartMonth = startMonth.charAt(0).toUpperCase() + startMonth.slice(1);
    const capEndMonth = endMonth.charAt(0).toUpperCase() + endMonth.slice(1);
    
    if (startYear === endYear) {
        if (startMonth === endMonth) {
            return `${capStartMonth} ${startYear}`;
        } else {
            return `${capStartMonth} - ${capEndMonth} ${startYear}`;
        }
    } else {
        return `${capStartMonth} ${startYear} - ${capEndMonth} ${endYear}`;
    }
}

function renderCalendar(tasks) {
    const calendarEl = document.getElementById("weekly-calendar");
    if (!calendarEl) return;

    // Initialize calendarStartDate if not set
    if (!calendarStartDate) {
        const dateFromVal = document.getElementById("filter-date-from").value;
        let baseDate = dateFromVal ? new Date(dateFromVal + "T00:00:00") : new Date();
        const dayOfWeek = baseDate.getDay();
        calendarStartDate = new Date(baseDate);
        calendarStartDate.setDate(baseDate.getDate() - dayOfWeek);
    }

    // Set dynamic columns and minimum width based on range
    calendarEl.style.gridTemplateColumns = `80px repeat(${calendarRangeDays}, 1fr)`;
    if (calendarRangeDays === 7) {
        calendarEl.style.minWidth = "800px";
    } else if (calendarRangeDays === 15) {
        calendarEl.style.minWidth = "1400px";
    } else if (calendarRangeDays === 30) {
        calendarEl.style.minWidth = "2400px";
    }

    // Dynamically update card title
    const titleEl = document.querySelector(".calendar-card .card-title");
    if (titleEl) {
        const periodText = getCalendarPeriodText(calendarStartDate, calendarRangeDays);
        if (calendarRangeDays === 7) {
            titleEl.innerText = `Calendario para tareas (Semanal - ${periodText})`;
        } else if (calendarRangeDays === 15) {
            titleEl.innerText = `Calendario para tareas (15 Días - ${periodText})`;
        } else if (calendarRangeDays === 30) {
            titleEl.innerText = `Calendario para tareas (Mensual - ${periodText})`;
        }
    }

    const daysFull = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
    const daysShort = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
    const daysMin = ["D", "L", "M", "X", "J", "V", "S"];

    let dayNames = daysFull;
    if (calendarRangeDays === 15) {
        dayNames = daysShort;
    } else if (calendarRangeDays === 30) {
        dayNames = daysMin;
    }

    // Render calendar header with date numbers and "+" button
    let html = `<div class="cal-header-cell cal-time-header-cell"></div>`;
    for (let d = 0; d < calendarRangeDays; d++) {
        const currentDate = new Date(calendarStartDate);
        currentDate.setDate(calendarStartDate.getDate() + d);
        
        const dayLabel = dayNames[currentDate.getDay()];
        const dateStr = currentDate.getDate() + "/" + (currentDate.getMonth() + 1);
        
        const isoDate = currentDate.getFullYear() + "-" + 
                        String(currentDate.getMonth() + 1).padStart(2, '0') + "-" + 
                        String(currentDate.getDate()).padStart(2, '0');
                        
        html += `
            <div class="cal-header-cell" style="position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; padding-bottom: 8px;">
                <span>${dayLabel}</span>
                <span style="font-size: 11px; font-weight: normal; opacity: 0.7;">${dateStr}</span>
                <button class="btn btn-outline" onclick="window.showAddTaskModal('${isoDate}')" title="Agregar Tarea" style="padding: 2px 6px; font-size: 10px; height: 18px; margin-top: 4px; display: inline-flex; align-items: center; justify-content: center; font-weight: bold; width: 18px; border-radius: 50%;">+</button>
            </div>
        `;
    }

    // Render single task row
    html += `<div class="cal-cell time-cell" style="display: flex; align-items: center; justify-content: center; font-weight: 600; color: var(--text-secondary);">Tareas</div>`;
    for (let d = 0; d < calendarRangeDays; d++) {
        const currentDate = new Date(calendarStartDate);
        currentDate.setDate(calendarStartDate.getDate() + d);
        const isoDate = currentDate.getFullYear() + "-" + 
                        String(currentDate.getMonth() + 1).padStart(2, '0') + "-" + 
                        String(currentDate.getDate()).padStart(2, '0');
                        
        // Filter tasks for this day
        const dayTasks = (tasks || []).filter(task => {
            if (!task.task_date) return false;
            // Handle task_date format (could be YYYY-MM-DD or full ISO)
            const tDate = task.task_date.split(" ")[0];
            return tDate === isoDate;
        });

        let taskHtml = "";
        dayTasks.forEach(task => {
            // Pick a status class or custom task type style
            const statusClass = task.status === "Open" ? "work-order" : 
                                task.status === "Working" ? "ftth" : 
                                task.status === "Completed" ? "repair-green" : "repair-purple";
            
            const statusLabel = task.status === "Open" ? "Abierta" : 
                                task.status === "Working" ? "Progreso" : 
                                task.status === "Completed" ? "Hecha" : "Canc.";
            
            taskHtml += `
                <div class="cal-task-card ${statusClass}" onclick="window.showTaskDetailModal('${task.task_id}')" style="margin-bottom: 6px; width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                        <span class="cal-task-title" style="margin: 0; font-weight: 600;">[Día ${currentDate.getDate()}] ${task.title}</span>
                        <span style="font-size: 9px; padding: 1px 4px; border-radius: 4px; background: rgba(255,255,255,0.4); font-weight: bold; text-transform: uppercase;">${statusLabel}</span>
                    </div>
                    <span style="font-size: 10px; opacity: 0.8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; max-width: 100%;">${task.desc || 'Sin descripción'}</span>
                </div>
            `;
        });

        html += `
            <div class="cal-cell" data-date="${isoDate}" style="padding: 8px; min-height: 180px; display: flex; flex-direction: column; justify-content: space-between; gap: 8px; vertical-align: top;">
                <div class="tasks-container" style="flex-grow: 1; display: flex; flex-direction: column; gap: 4px; width: 100%;">
                    ${taskHtml}
                </div>
                <button class="btn btn-outline" onclick="window.showAddTaskModal('${isoDate}')" style="width: 100%; font-size: 11px; padding: 4px; display: flex; align-items: center; justify-content: center; gap: 4px; height: auto;">
                    <span>+ Tarea</span>
                </button>
            </div>
        `;
    }

    calendarEl.innerHTML = html;
}

// Global functions for showing and hiding the task modals
window.showAddTaskModal = function(date) {
    const dateInput = document.getElementById("add-task-date");
    if (dateInput) {
        if (!date) {
            const today = new Date();
            const year = today.getFullYear();
            const month = String(today.getMonth() + 1).padStart(2, '0');
            const day = String(today.getDate()).padStart(2, '0');
            dateInput.value = `${year}-${month}-${day}`;
        } else {
            dateInput.value = date;
        }
    }
    const subjectInput = document.getElementById("add-task-subject");
    if (subjectInput) subjectInput.value = "";
    const descInput = document.getElementById("add-task-desc");
    if (descInput) descInput.value = "";
    
    const modal = document.getElementById("add-task-modal");
    if (modal) {
        modal.style.display = "flex";
        void modal.offsetWidth;
        modal.classList.add("open");
    }
};

window.closeAddTaskModal = function() {
    const modal = document.getElementById("add-task-modal");
    if (modal) {
        modal.classList.remove("open");
        setTimeout(() => {
            if (!modal.classList.contains("open")) {
                modal.style.display = "none";
            }
        }, 300);
    }
};

window.showTaskDetailModal = function(taskId) {
    const task = cachedTasks.find(item => item.task_id === taskId);
    if (!task) return;

    const subjectEl = document.getElementById("modal-task-subject");
    if (subjectEl) subjectEl.innerText = task.title || "—";
    
    const descEl = document.getElementById("modal-task-desc");
    if (descEl) descEl.innerText = task.desc || "Sin descripción.";
    
    let dateStr = "—";
    if (task.task_date) {
        try {
            const parts = task.task_date.split(" ")[0].split("-");
            if (parts.length === 3) {
                const dateObj = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
                dateStr = dateObj.toLocaleDateString("es-ES", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
                dateStr = dateStr.charAt(0).toUpperCase() + dateStr.slice(1);
            }
        } catch(e) {
            dateStr = task.task_date;
        }
    }
    const dateEl = document.getElementById("modal-task-date");
    if (dateEl) dateEl.innerText = dateStr;
    
    const statusValEl = document.getElementById("modal-task-status");
    if (statusValEl) {
        statusValEl.innerText = task.status === "Open" ? "Abierta" : task.status === "Working" ? "En Progreso" : "Completada";
        statusValEl.className = "badge " + (task.status === "Open" ? "info" : task.status === "Working" ? "warning" : "success");
    }

    const modal = document.getElementById("task-detail-modal");
    if (modal) {
        modal.style.display = "flex";
        void modal.offsetWidth;
        modal.classList.add("open");
    }
};

window.closeTaskDetailModal = function() {
    const modal = document.getElementById("task-detail-modal");
    if (modal) {
        modal.classList.remove("open");
        setTimeout(() => {
            if (!modal.classList.contains("open")) {
                modal.style.display = "none";
            }
        }, 300);
    }
};

// Keep legacy installation modal functions just in case they are triggered elsewhere
window.showInstallationModal = function(serviceId, time) {
    const inst = cachedInstallations.find(item => item.service_id === serviceId);
    if (!inst) return;
    document.getElementById("modal-client-val").innerText = inst.client || "—";
    document.getElementById("modal-service-val").innerText = inst.service_id || "—";
    document.getElementById("modal-plan-val").innerText = inst.plan || "—";
    document.getElementById("modal-ip-val").innerText = inst.ip || "—";
    document.getElementById("modal-router-val").innerText = inst.router || "—";
    let dateStr = "—";
    if (inst.installation_date) {
        try {
            const parts = inst.installation_date.split("-");
            if (parts.length === 3) {
                const dateObj = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
                dateStr = dateObj.toLocaleDateString("es-ES", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
                dateStr = dateStr.charAt(0).toUpperCase() + dateStr.slice(1);
            }
        } catch(e) {
            dateStr = inst.installation_date;
        }
    }
    document.getElementById("modal-date-val").innerText = dateStr;
    document.getElementById("modal-time-val").innerText = time || "—";
    const statusValEl = document.getElementById("modal-status-val");
    if (statusValEl) {
        statusValEl.innerText = inst.status || "—";
        statusValEl.className = "badge " + (inst.status === "Enabled" ? "success" : inst.status === "Defaulter" ? "danger" : "warning");
    }
    const linkEl = document.getElementById("modal-link-service");
    if (linkEl) {
        linkEl.href = `/app/customer/${inst.customer_id}`;
    }
    const modal = document.getElementById("installation-modal");
    if (modal) {
        modal.style.display = "flex";
        void modal.offsetWidth;
        modal.classList.add("open");
    }
};

window.closeInstallationModal = function() {
    const modal = document.getElementById("installation-modal");
    if (modal) {
        modal.classList.remove("open");
        // Wait for the CSS transition to finish before hiding the container
        setTimeout(() => {
            if (!modal.classList.contains("open")) {
                modal.style.display = "none";
            }
        }, 300);
    }
};

// =========================================================================
// LEAFLET MAP FUNCTIONS & COORDINATES DATA
// =========================================================================

const VE_MUNICIPALITY_COORDINATES = {
    // Caracas / Distrito Capital y Miranda
    "libertador": [10.5050, -66.9144],
    "chacao": [10.4914, -66.8576],
    "baruta": [10.4328, -66.8686],
    "sucre": [10.4853, -66.8189],
    "el hatillo": [10.4286, -66.8250],
    "los salias": [10.3794, -66.9461],
    "carrizal": [10.3475, -66.9744],
    "guaicaipuro": [10.3392, -67.0422], // Los Teques
    "plaza": [10.4636, -66.6192], // Guarenas
    "zamora": [10.4722, -66.5297], // Guatire
    
    // Carabobo
    "valencia": [10.1620, -68.0077],
    "naguanagua": [10.2541, -68.0125],
    "san diego": [10.2292, -67.9547],
    "guacara": [10.2272, -67.8767],
    "puerto cabello": [10.4674, -68.0124],
    
    // Aragua
    "girardot": [10.2504, -67.6014], // Maracay
    "santiago marino": [10.2221, -67.5028], // Turmero
    "jose felix ribas": [10.2319, -67.3341], // La Victoria
    
    // Zulia
    "maracaibo": [10.6427, -71.6125],
    "san francisco": [10.5562, -71.6742],
    "cabimas": [10.3957, -71.4398],
    "lagunillas": [10.1257, -71.2586], // Ciudad Ojeda
    
    // Lara
    "iribarren": [10.0683, -69.3467], // Barquisimeto
    "palavecino": [10.0264, -69.2612], // Cabudare
    
    // Anzoátegui
    "simon bolivar": [9.6000, -64.5000],
    "simon bolivar (bna)": [10.1362, -64.6862], // Barcelona
    "juan antonio sotillo": [10.2167, -64.6333], // Puerto La Cruz
    "diego bautista urbaneja": [10.2000, -64.6833], // Lechería
    "anaco": [9.4389, -64.4722],
    
    // Bolívar
    "caroni": [8.3000, -62.7000], // Ciudad Guayana / Puerto Ordaz
    "heres": [8.1167, -63.5500], // Ciudad Bolívar
    
    // Táchira
    "san cristobal": [7.7669, -72.2250],
    
    // Nueva Esparta
    "marino": [10.9575, -63.8569], // Porlamar
    "maneiro": [10.9833, -63.8000], // Pampatar
    
    // Default o estados de fallbacks (estados como tales)
    "distrito capital": [10.5050, -66.9144],
    "miranda": [10.3500, -66.6000],
    "aragua": [10.0000, -67.2500],
    "carabobo": [10.1000, -68.0000],
    "zulia": [10.0000, -72.0000],
    "lara": [10.1667, -69.6667],
    "anzoategui": [9.0000, -64.0000],
    "bolivar": [6.5000, -63.0000],
    "nueva esparta": [11.0000, -63.9000],
    "falcon": [11.0000, -70.0000],
    "portuguesa": [9.2500, -69.2500],
    "monagas": [9.5000, -63.0000],
    "barinas": [8.2500, -70.2500],
    "merida": [8.5000, -71.2500]
};

function initLeafletMap() {
    const mapContainer = document.getElementById("isp-map");
    if (!mapContainer) return;

    if (ispMapInstance) {
        try {
            ispMapInstance.remove();
        } catch(e) {
            console.error("Error removing old map instance:", e);
        }
        ispMapInstance = null;
    }

    const isDark = document.body.classList.contains("dark-theme");
    const defaultCenter = [10.4806, -66.9036]; // Caracas
    const defaultZoom = 6;

    try {
        ispMapInstance = L.map('isp-map', {
            center: defaultCenter,
            zoom: defaultZoom,
            scrollWheelZoom: false
        });

        const tileUrl = isDark 
            ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png' 
            : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
            
        const attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>';

        mapTileLayer = L.tileLayer(tileUrl, {
            attribution: attribution,
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(ispMapInstance);

        mapMarkersGroup = L.layerGroup().addTo(ispMapInstance);
    } catch(e) {
        console.error("Failed to initialize Leaflet map:", e);
    }
}

function updateMapData(analytics) {
    if (!ispMapInstance || !mapMarkersGroup) return;

    mapMarkersGroup.clearLayers();

    if (!analytics || !analytics.location_chart) return;

    const locationChart = analytics.location_chart;
    const labels = locationChart.labels || [];
    const values = locationChart.values || [];

    const maxValue = Math.max(...values, 1);
    const points = [];

    for (let i = 0; i < labels.length; i++) {
        const rawLocationName = labels[i];
        const clientCount = values[i];
        
        if (rawLocationName === "Sin Ubicación" || !clientCount) continue;

        const normName = rawLocationName.toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .replace(/municipio\s+/g, "")
            .trim();

        let coords = VE_MUNICIPALITY_COORDINATES[normName];

        if (!coords) {
            for (const key in VE_MUNICIPALITY_COORDINATES) {
                if (normName.includes(key) || key.includes(normName)) {
                    coords = VE_MUNICIPALITY_COORDINATES[key];
                    break;
                }
            }
        }

        if (!coords) {
            const stateFilter = document.getElementById("filter-state")?.value;
            if (stateFilter) {
                const normState = stateFilter.toLowerCase()
                    .normalize("NFD")
                    .replace(/[\u0300-\u036f]/g, "")
                    .trim();
                coords = VE_MUNICIPALITY_COORDINATES[normState];
            }
        }

        // Final random spread around Venezuela center if not matched to prevent overlap
        if (!coords) {
            coords = [8.0 + (Math.random() - 0.5) * 1.5, -66.0 + (Math.random() - 0.5) * 1.5];
        }

        // Calculate dynamic marker radius
        const radius = Math.max(8, (clientCount / maxValue) * 35);

        const circle = L.circleMarker(coords, {
            radius: radius,
            fillColor: '#2563eb',
            color: '#1d4ed8',
            weight: 1.5,
            opacity: 0.8,
            fillOpacity: 0.4
        });

        const popupContent = `
            <div class="map-popup-container">
                <div class="map-popup-title">${rawLocationName}</div>
                <div class="map-popup-row">
                    <span class="map-popup-label">Suscriptores:</span>
                    <span class="map-popup-value success">${clientCount}</span>
                </div>
                <div class="map-popup-row">
                    <span class="map-popup-label">Estatus:</span>
                    <span class="map-popup-value">Activo</span>
                </div>
            </div>
        `;

        circle.bindPopup(popupContent);
        mapMarkersGroup.addLayer(circle);
        
        points.push(coords);
    }

    if (points.length > 0) {
        try {
            const munFilter = document.getElementById("filter-municipality")?.value;
            if (munFilter && points.length === 1) {
                ispMapInstance.setView(points[0], 11);
            } else {
                ispMapInstance.fitBounds(points, { padding: [50, 50] });
            }
        } catch (e) {
            console.error("Error fitting map bounds:", e);
        }
    }
}



