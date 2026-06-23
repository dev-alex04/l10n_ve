// Copyright (c) 2026, Domina Software and contributors

let dailySalesChartInstance = null;
let balanceDonutChartInstance = null;
let currentCurrency = "USD";
let allMunicipalities = [];
let calendarRangeDays = 7;
let calendarStartDate = null;
let cachedInstallations = [];
let cachedTasks = [];

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
    
    const formatDate = (d) => {
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    document.getElementById("filter-date-from").value = formatDate(firstDay);
    document.getElementById("filter-date-to").value = formatDate(today);

    // Load filter options from backend
    loadFilterOptions(() => {
        // Fetch dashboard data with default filters
        reloadDashboard();
    });

    // Attach change events to filters
    const filterIds = ["filter-company", "filter-branch", "filter-router", "filter-state", "filter-municipality", "filter-currency", "filter-date-from", "filter-date-to"];
    filterIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener("change", () => {
                if (id === "filter-currency") {
                    currentCurrency = el.value;
                }
                if (id === "filter-state") {
                    updateMunicipalityDropdown();
                }
                reloadDashboard();
            });
        }
    });

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
        });
    }

    function updateThemeButton(isDark) {
        if (!themeToggleBtn) return;
        const iconName = isDark ? "sun" : "moon";
        const text = isDark ? "Modo Claro" : "Modo Oscuro";
        themeToggleBtn.innerHTML = `<i data-lucide="${iconName}" style="width: 16px; height: 16px;"></i> <span>${text}</span>`;
        if (window.lucide) lucide.createIcons();
    }

    // Calendar controls listeners
    const calBtnToday = document.getElementById("cal-btn-today");
    if (calBtnToday) {
        calBtnToday.addEventListener("click", () => {
            const today = new Date();
            const dayOfWeek = today.getDay();
            calendarStartDate = new Date(today);
            calendarStartDate.setDate(today.getDate() - dayOfWeek);
            renderCalendar(cachedInstallations);
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
            renderCalendar(cachedInstallations);
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
            renderCalendar(cachedInstallations);
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
                renderCalendar(cachedInstallations);
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
            
            const url = "/api/method/l10n_ve.www.isp_dashboard_portal.index.create_task";
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
    const url = "/api/method/l10n_ve.www.isp_dashboard_portal.index.get_filter_options";
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
    calendarStartDate = null;
    const filters = {
        company: document.getElementById("filter-company").value,
        branch: document.getElementById("filter-branch").value,
        router: document.getElementById("filter-router").value,
        state: document.getElementById("filter-state").value,
        municipality: document.getElementById("filter-municipality").value,
        currency: document.getElementById("filter-currency").value,
        date_from: document.getElementById("filter-date-from").value,
        date_to: document.getElementById("filter-date-to").value
    };

    fetchDashboardData(filters, (data) => {
        let dashboardData = data;
        if (!dashboardData) {
            console.log("No data returned from backend, using high-fidelity mock data.");
            dashboardData = getMockData();
        }
        renderDashboard(dashboardData);
    });
}

// =========================================================================
// API & RENDER CONTROLLER
// =========================================================================

function fetchDashboardData(filters, callback) {
    // Use GET with query params — no CSRF token required for read-only endpoints
    const apiMethod = "l10n_ve.www.isp_dashboard_portal.index.get_dashboard_data";
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
    const kpis = data.kpi_cards || {};

    // ── 1. KPI Cards ──────────────────────────────────────────────────────

    // Por Cobrar
    const pendienteUsd = parseFloat(kpis.total_pendiente_usd || kpis.grand_total || 0);
    const pendienteVef = parseFloat(kpis.total_pendiente_vef || 0);
    const count = kpis.unpaid_orders_count || 0;
    
    const displayPendiente = currentCurrency === "VEF" ? fmtVES(pendienteVef) : fmtUSD(pendienteUsd);
    const subtextPendiente = currentCurrency === "VEF" ? fmtUSD(pendienteUsd) : fmtVES(pendienteVef);
    
    setText("kpi-pendiente-val", displayPendiente);
    setText("kpi-pendiente-count", `Equiv. ${subtextPendiente}<br><span style="opacity: 0.8;">${count} factura${count !== 1 ? "s" : ""} pendiente${count !== 1 ? "s" : ""}</span>`);

    // Cobrado REF ($)
    const cobUsdTotal = parseFloat(kpis.collected_usd_total || 0);
    const cobUsdBase  = parseFloat(kpis.collected_usd_base  || 0);
    const cobUsdTax   = parseFloat(kpis.collected_usd_tax   || 0);
    const cobUsdTotalVes = cobUsdTotal * window.exchange_rate;
    
    setText("kpi-cobrado-usd-val", fmtUSD(cobUsdTotal));
    setText("kpi-cobrado-usd-sub", `Equiv. ${fmtVES(cobUsdTotalVes)}<br><span style="opacity: 0.8; font-size: 10px;">Base ${fmtUSD(cobUsdBase)} + IVA ${fmtUSD(cobUsdTax)}</span>`);

    // Cobrado Bs.
    const cobVesTotal = parseFloat(kpis.collected_ves_total || 0);
    const cobVesBase  = parseFloat(kpis.collected_ves_base  || 0);
    const cobVesTax   = parseFloat(kpis.collected_ves_tax   || 0);
    const cobVesTotalUsd = cobVesTotal / (window.exchange_rate || 1);
    
    setText("kpi-cobrado-ves-val", fmtVES(cobVesTotal));
    setText("kpi-cobrado-ves-sub", `Equiv. ${fmtUSD(cobVesTotalUsd)}<br><span style="opacity: 0.8; font-size: 10px;">Base ${fmtVES(cobVesBase)} + IVA ${fmtVES(cobVesTax)}</span>`);

    // Gastos
    const gastosUsd = parseFloat(kpis.total_expenses_usd || 0);
    const gastosVef = parseFloat(kpis.total_expenses_vef || 0);
    const gastosUsdEquivVes = gastosUsd * window.exchange_rate;
    const gastosVefEquivUsd = gastosVef / (window.exchange_rate || 1);
    
    setText("kpi-gastos-usd-val", fmtUSD(gastosUsd));
    setText("kpi-gastos-ves-val", `Equiv. ${fmtVES(gastosUsdEquivVes)}<br><span style="display: block; margin-top: 4px; font-weight: 600; color: var(--text-primary); font-size: 13px;">${fmtVES(gastosVef)}</span>Equiv. ${fmtUSD(gastosVefEquivUsd)}`);

    // Disponible USD & Bs.
    const dispUsd = parseFloat(kpis.available_usd !== undefined ? kpis.available_usd : cobUsdTotal - gastosUsd);
    const dispVes = parseFloat(kpis.available_vef !== undefined ? kpis.available_vef : cobVesTotal - gastosVef);
    const dispUsdEquivVes = dispUsd * window.exchange_rate;
    const dispVesEquivUsd = dispVes / (window.exchange_rate || 1);
    
    setText("kpi-disp-usd-val", fmtUSD(dispUsd));
    setText("kpi-disp-usd-sub", `Equiv. ${fmtVES(dispUsdEquivVes)}<br><span style="opacity: 0.8;">Cobrado − Gastos</span>`);
    setText("kpi-disp-ves-val", fmtVES(dispVes));
    setText("kpi-disp-ves-sub", `Equiv. ${fmtUSD(dispVesEquivUsd)}<br><span style="opacity: 0.8;">Cobrado − Gastos</span>`);

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
    renderSalesTodayTable(data.sales_today);
    renderTaxKpiCards(data.tax_totals);

    // ── 6. Calendar (tasks) ──────────────────────────────────────────────
    cachedTasks = data.calendar_tasks || [];
    renderCalendar(cachedTasks);

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
            html += `
                <div class="expense-item">
                    <div class="expense-info">
                        <span>${item.category}</span>
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

// Ventas del Día Table
function renderSalesTodayTable(sales) {
    const tbody = document.getElementById("sales-today-tbody");
    if (!tbody) return;

    let list = sales || [];
    if (list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center" style="padding: 20px; text-align: center; color: var(--text-secondary);">No hay ventas registradas el día de hoy.</td></tr>`;
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
// Populates the single combined IVA + IGTF (all-time) KPI card
function renderTaxKpiCards(taxTotals) {
    const t = taxTotals || {};
    const fmtUSD = (n) => "REF " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const fmtVES = (n) => "Bs. " + parseFloat(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    setText("kpi-iva-usd-val",  fmtUSD(t.iva_usd));
    setText("kpi-iva-ves-val",  fmtVES(t.iva_ves));
    setText("kpi-igtf-usd-val", fmtUSD(t.igtf_usd));
    setText("kpi-igtf-ves-val", fmtVES(t.igtf_ves));
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
        if (calendarRangeDays === 7) {
            titleEl.innerText = "Calendario para tareas (Semanal)";
        } else if (calendarRangeDays === 15) {
            titleEl.innerText = "Calendario para tareas (15 Días)";
        } else if (calendarRangeDays === 30) {
            titleEl.innerText = "Calendario para tareas (Mensual)";
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
                                task.status === "Working" ? "ftth" : "repair-green";
            
            taskHtml += `
                <div class="cal-task-card ${statusClass}" onclick="window.showTaskDetailModal('${task.task_id}')" style="margin-bottom: 6px; width: 100%;">
                    <span class="cal-task-title">[Día ${currentDate.getDate()}] ${task.title}</span>
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
            const parts = task.task_date.split("-");
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



