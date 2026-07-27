// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

// Filtros del Reporte HQ de facturas de venta. Mismos filtros que el Libro de
// Ventas (Company / Fechas / Sucursal) para que sea intercambiable; la
// diferencia está en el ACCESO (rol dedicado VE Sales Book HQ) y en que aquí
// irán las columnas HQ (serie-número, municipio/sucursal) sin tocar el libro.

frappe.query_reports["VE Sales Invoices HQ"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company"),
    },
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.month_start(),
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.month_end(),
    },
    {
      fieldname: "branch",
      label: __("Sucursal"),
      fieldtype: "Link",
      options: "VE Branch",
      get_query: () => ({
        filters: { company: frappe.query_report.get_filter_value("company") },
      }),
    },
  ],
};
