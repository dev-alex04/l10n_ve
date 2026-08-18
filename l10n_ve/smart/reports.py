"""Los reportes que esta app EXPONE al asistente.

domina_smart los descubre por convención —``<app>/smart/reports.py``— y no sabe
ninguno: acá se declara qué contesta cada uno y qué filtros acepta. Quien toca un
reporte puede corregir su descripción en el MISMO PR, que es la razón por la que
esto vive acá y no del otro lado.

**Los nombres son los REGISTRADOS, no los del JSON.** No siempre coinciden:
`iva_forma_30` declara llamarse «IVA Forma 30» en su archivo y está registrado en
minúsculas. Un nombre que no exista no falla con un error claro — falla con
«reporte no encontrado», que se lee como si el dato no existiera.

Los filtros salen del ``.js`` de cada reporte, que no se puede leer en tiempo de
ejecución: por eso se escriben. `company`, `from_date` y `to_date` son los de casi
todos; los que solo aceptan fecha de corte llevan `to_date` sin `from_date`.
"""

_PERIODO = ["company", "from_date", "to_date"]
_CORTE = ["company", "to_date"]

REPORTS = [
	# --- Libros y declaraciones fiscales ---
	{
		"report": "Sales book",
		"answers": "Libro de Ventas fiscal: las facturas emitidas del período con su base e IVA.",
		"filters": _PERIODO + ["branch"],
	},
	{
		"report": "purchase_book",
		"answers": "Libro de Compras fiscal: facturas de proveedores con su crédito de IVA.",
		"filters": _PERIODO + ["branch"],
	},
	{
		"report": "iva_forma_30",
		"answers": "La declaración de IVA (Forma 30) con sus casillas, como se presenta al SENIAT.",
		"filters": _PERIODO + ["excedente_anterior", "retenciones_anteriores"],
	},
	{
		"report": "VAT report",
		"answers": "Detalle del IVA factura por factura emitida.",
		"filters": _PERIODO + ["branch", "fiscal_year", "fiscal_month"],
	},
	{
		"report": "prorrata_iva",
		"answers": "Prorrata del crédito de IVA cuando hay ventas gravadas y exentas.",
		"filters": _PERIODO,
	},
	{
		"report": "IGTF received",
		"answers": "IGTF cobrado a clientes en el período.",
		"filters": _PERIODO,
	},
	# --- Retenciones ---
	{
		"report": "Customer Retention",
		"answers": (
			"Retenciones que los clientes nos hicieron, con su número de comprobante. "
			"OJO: cuando el comprobante falta, el monto retenido se muestra en 0 — para "
			"saber cuáles faltan usá check_customer_retentions, no este reporte."
		),
		"filters": _PERIODO + ["branch", "customer", "retention_type"],
	},
	{
		"report": "VAT Withholding",
		"answers": "Comprobantes de retención de IVA que emitimos a proveedores.",
		"filters": _PERIODO + ["supplier"],
	},
	{
		"report": "ISLR Withholding",
		"answers": "Comprobantes de retención de ISLR que emitimos a proveedores.",
		"filters": _PERIODO + ["supplier", "group_by"],
	},
	# --- Fiscal / regulatorio ---
	{
		"report": "VE HKA Invoices Status",
		"answers": (
			"Estado de certificación de cada factura ante el SENIAT vía HKA. Para el "
			"diagnóstico de qué NO llegó y por qué, check_hka es mejor: el campo de estado "
			"no es evidencia de certificación."
		),
		"filters": _PERIODO + ["document_type", "status"],
	},
	{
		"report": "VE Conatel Sales Report",
		"answers": "Ventas en el formato que pide CONATEL.",
		"filters": _PERIODO + ["branch", "cost_center", "customer"],
	},
	{
		"report": "VE Sales Invoices HQ",
		"answers": "Ventas consolidadas por casa matriz.",
		"filters": _PERIODO + ["branch", "main_branch"],
	},
	# --- Estados financieros y libros contables ---
	{
		"report": "ve_balance_sheet",
		"answers": "Balance General a una fecha.",
		"filters": _CORTE + ["presentation", "cost_center"],
	},
	{
		"report": "ve_profit_and_loss",
		"answers": "Estado de Resultados del período.",
		"filters": _PERIODO + ["presentation", "cost_center"],
	},
	{
		"report": "ve_cash_flow",
		"answers": "Flujo de Efectivo del período.",
		"filters": _PERIODO + ["cost_center"],
	},
	{
		"report": "ve_statement_changes_equity",
		"answers": "Estado de Cambios en el Patrimonio.",
		"filters": _PERIODO,
	},
	{
		"report": "trial_balance_vef",
		"answers": "Balance de comprobación en bolívares.",
		"filters": _PERIODO + ["show_zero_values"],
	},
	{
		"report": "ve_account_balances",
		"answers": "Saldo de cada cuenta contable a una fecha.",
		"filters": _CORTE,
	},
	{
		"report": "ve_analytical_ledger",
		"answers": "Mayor analítico: movimientos por cuenta y centro de costo.",
		"filters": _PERIODO + ["cost_center", "account", "include_cancelled"],
	},
	{
		"report": "ve_ledger_book",
		"answers": (
			"Libro Mayor. ENORME —decenas de miles de filas por mes—: pedilo siempre con "
			"cuenta y un rango corto."
		),
		"filters": _PERIODO + ["cost_center", "presentation"],
	},
	{
		"report": "ve_journal_book",
		"answers": "Libro Diario: los asientos del período.",
		"filters": _PERIODO + ["presentation"],
	},
	{
		"report": "ve_fixed_assets_schedule",
		"answers": "Activos fijos y su depreciación a una fecha.",
		"filters": _CORTE,
	},
]
