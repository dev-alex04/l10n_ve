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
		"answers": (
			"Los comprobantes de retención de IVA que EMITIMOS al pagarle a un proveedor: "
			"plata que le retuvimos y que le debemos al SENIAT. Es dinero que sale de "
			"nuestra caja hacia el fisco.\n"
			"Ojo con la dirección: lo que a NOSOTROS nos retienen los CLIENTES es lo "
			"contrario —hace que entre menos plata de la facturada— y no está en este "
			"reporte."
		),
		"filters": _PERIODO + ["supplier"],
	},
	{
		"report": "ISLR Withholding",
		"answers": (
			"Los comprobantes de retención de ISLR que EMITIMOS al pagarle a un proveedor: "
			"plata que le retuvimos y que le debemos al SENIAT. Es dinero que sale de "
			"nuestra caja hacia el fisco.\n"
			"Ojo con la dirección: lo que a NOSOTROS nos retienen los CLIENTES es lo "
			"contrario —hace que entre menos plata de la facturada— y no está en este "
			"reporte."
		),
		"filters": _PERIODO + ["supplier", "group_by"],
	},
	# --- Fiscal / regulatorio ---
	{
		"report": "VE HKA Invoices Status",
		"answers": (
			"Estado de certificación de cada factura ante el SENIAT vía HKA, con su propio "
			"resumen: total, emitidas, con error, pendientes y anuladas.\n"
			"OJO con «Emitidas»: se apoya en `bill_control` O en un log de envío exitoso, y "
			"para períodos históricos eso SOBREESTIMA. Medido en ene-jun 2026: el reporte "
			"cuenta 6.882 emitidas, y solo 2.386 tienen log de transmisión —todas de junio, "
			"que es cuando arrancó HKA—. Las otras traen un número de control cargado por "
			"otra vía.\n"
			"Si la pregunta es cuántas se TRANSMITIERON de verdad, usá check_period_impact, "
			"que separa las dos señales. Para el diagnóstico de qué no llegó y por qué, "
			"check_hka."
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
	# --- de ERPNext, verificados contra el mayor antes de exponerlos ---
	#
	# Exponer un reporte cuesta casi nada —el catálogo es dato que el modelo pide, no
	# prompt que carga siempre— pero exponer uno que no reconcilia sale caro: entrega
	# un número plausible y falso. Estos dos se probaron; otros tres se descartaron.
	# `Accounts Receivable` al 30-06-2026 devolvió −707.874,52 donde el mayor dice
	# +544.297,79, y `Trial Balance for Party` lista las 2.419 partes en vez de las
	# 416 con saldo. Para eso está `account_balance_by_party`.
	{
		"report": "Sales Register",
		"answers": (
			"Las facturas de venta emitidas en un período, una por fila. Es la que "
			"contesta «cuántas facturas se emitieron»: verificado contra el mayor, "
			"devuelve exactamente los mismos documentos. El Libro de Ventas fiscal "
			"agrupa distinto y da otro conteo."
		),
		"filters": _PERIODO + ["customer", "branch", "cost_center"],
	},
	{
		"report": "General Ledger",
		"answers": (
			"Mayor de una cuenta: cada movimiento con su contraparte y el saldo que va "
			"quedando. Sirve para explicar de dónde sale un saldo. ENORME —una cuenta "
			"bancaria de un mes son miles de filas—: pedilo siempre con `account` y un "
			"rango corto, y usá `contains` para una contraparte concreta."
		),
		"filters": _PERIODO + ["account", "party_type", "party", "cost_center", "project"],
	},
]
