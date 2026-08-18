"""Herramientas del agente para la localización fiscal de Venezuela.

domina_smart las descubre por convención al buscar ``<app>/smart/tools.py`` en
cada app instalada. No hace falta declarar nada en el hooks.py de esta app, y
domina_smart no importa l10n_ve: si no está instalada, estas herramientas
simplemente no existen.

**La trampa que hace falta esta herramienta.** ``AGENTS.md`` de esta app lo dice
con el número medido: ``hka_status`` NO es evidencia de certificación —está vacío
en miles de facturas sí certificadas—, y una métrica escrita como
``hka_status != 'Emitida'`` reportó **8.001 pendientes cuando el pendiente real
eran 2**.

Un agente que arme su propia query cae en eso sin excepción: el campo se llama
como la pregunta. Por eso acá no se escribe ninguna condición propia: se reusa
``_get_pending_hka_invoices``, que es la definición que usa el cron de verdad.
"""

import frappe
from frappe.utils import add_months, cint, flt, nowdate

MAX_ROWS = 25

#: Certificada = tiene número de control fiscal, o un log de envío exitoso. Es la
#: definición de AGENTS.md, y la misma que aplica el cron.
_CERTIFICADA = """(
	(si.bill_control IS NOT NULL AND si.bill_control != '')
	OR EXISTS (
		SELECT 1 FROM `tabVE Digital Invoice Log` l
		WHERE l.sales_invoice = si.name AND l.status = 'Success'
		  AND l.document_type = 'Sales Invoice'
	)
)"""


def _settings() -> dict:
	from l10n_ve.digital_invoice.tfhka_integration import _get_tfhka_settings

	return _get_tfhka_settings() or {}


def _series_activas() -> tuple[list[dict], set[str]]:
	"""Series activas y el conjunto de sucursales que cubren."""
	from l10n_ve.digital_invoice.tfhka_integration import _get_active_billing_series

	series = _get_active_billing_series()
	cubiertas = {b for s in series for b in (s.get("branches") or [])}
	return series, cubiertas


def _motivo(si: frappe._dict, cubiertas: set[str], cutoff: str) -> str:
	"""Por qué esta factura pagada todavía no llegó al SENIAT.

	El orden importa: es el mismo en que el cron descarta. Una factura con la
	sucursal fuera de serie nunca llega a evaluarse la tasa, así que reportar la
	tasa sería mandar a arreglar lo que no bloquea.
	"""
	if not si.branch or si.branch not in cubiertas:
		return "Sucursal fuera de toda serie activa"

	if cutoff and str(si.posting_date) < str(cutoff):
		return f"Anterior a la fecha de corte ({cutoff})"

	ultimo = frappe.db.get_value(
		"VE Digital Invoice Log",
		{"sales_invoice": si.name, "document_type": "Sales Invoice"},
		["status", "notes"],
		order_by="creation desc",
		as_dict=True,
	)
	if ultimo and ultimo.status == "Error":
		return f"Rechazada en el último intento: {(ultimo.notes or '').strip()[:160]}"

	# La tasa se evalúa de último porque es lo que el cron evalúa de último, y es
	# lo único que exige abrir el documento entero.
	try:
		from l10n_ve.digital_invoice.emission_rerate import stale_rate_reason

		razon = stale_rate_reason(frappe.get_doc("Sales Invoice", si.name))
		if razon:
			return f"Tasa desincronizada: {razon[:160]}"
	except Exception:
		pass

	return "En cola: sin bloqueo, el cron todavía no la alcanzó"


def _moneda_compania(company: str | None) -> str:
	"""En qué moneda están los campos ``base_*`` y ``outstanding_amount``."""
	if not company:
		return "?"
	return frappe.get_cached_value("Company", company, "default_currency") or "?"


def _por_moneda(filas: list) -> dict:
	"""Suma el pendiente agrupando por moneda, nunca en un solo número.

	Este sistema opera en USD y bolívares a la vez. Un total que los mezcla se
	lee como una cifra válida y no lo es.

	**`outstanding_amount` NO está en `si.currency`.** Está en la moneda de la
	compañía, igual que los `base_*`: una factura con ``currency='USD'`` y
	``grand_total=12.000`` trae ``outstanding_amount=9.025.131,60``, que son
	bolívares. Emparejarlo con `currency` reportaba la cartera certificada en
	«38.556.639,24 USD» — 750 veces el número real, con formato de cifra válida.

	`grand_total` sí va con `currency`; ese emparejamiento está bien y se usa tal
	cual más arriba.
	"""
	out: dict[str, float] = {}
	for r in filas:
		moneda = _moneda_compania(getattr(r, "company", None))
		out[moneda] = round(out.get(moneda, 0.0) + flt(r.outstanding_amount), 2)
	return out


def check_hka(branch: str | None = None, limit: int = 10) -> dict:
	"""Diagnóstico de facturación digital: qué no llegó al SENIAT, y por qué.

	Dos cohortes, y las dos son anomalías de signo opuesto:

    * **Cobradas sin certificar** — el cliente pagó y el documento fiscal no
      existe. Cada una viene con su motivo.
    * **Certificadas sin cobrar** — el documento ya está ante el SENIAT y el
      dinero no entró. Es la más delicada: una factura mal emitida no se
      deshace, se anula con nota de crédito y se reemite.
	"""
	limit = max(1, min(cint(limit) or 10, MAX_ROWS))
	cfg = _settings()
	if not cfg:
		return {"error": "La integración con HKA está deshabilitada en TFHKA Settings."}

	cutoff = cfg.get("cutoff_date")
	series, cubiertas = _series_activas()

	filtro_branch = "AND si.branch = %(branch)s" if branch else ""
	params = {"branch": branch, "cutoff": cutoff}

	# --- cobradas y sin certificar ---
	pendientes = frappe.db.sql(f"""
		SELECT si.name, si.branch, si.customer_name, si.posting_date,
		       si.grand_total, si.currency, si.status
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1 AND si.status = 'Paid'
		  AND si.is_return = 0 AND si.is_debit_note = 0
		  AND NOT {_CERTIFICADA}
		  {filtro_branch}
		ORDER BY si.posting_date
	""", params, as_dict=True)

	por_motivo: dict[str, dict] = {}
	for si in pendientes:
		m = _motivo(si, cubiertas, cutoff)
		# El monto va POR MONEDA. Un total que suma bolívares con dólares se ve
		# perfectamente bien y no significa nada — es la regla del glosario.
		b = por_motivo.setdefault(m, {"reason": m, "count": 0, "monto_por_moneda": {}, "muestra": []})
		b["count"] += 1
		moneda = si.currency or "?"
		b["monto_por_moneda"][moneda] = round(b["monto_por_moneda"].get(moneda, 0.0) + flt(si.grand_total), 2)
		if len(b["muestra"]) < limit:
			b["muestra"].append({
				"invoice": si.name, "cliente": si.customer_name,
				"sucursal": si.branch, "fecha": str(si.posting_date),
				"total": flt(si.grand_total), "moneda": si.currency,
			})

	# --- certificadas y sin cobrar ---
	sin_cobrar = frappe.db.sql(f"""
		SELECT si.name, si.branch, si.customer_name, si.posting_date, si.status,
		       si.grand_total, si.outstanding_amount, si.currency, si.bill_control,
		       si.company
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1 AND si.status != 'Paid'
		  AND si.is_return = 0 AND si.is_debit_note = 0
		  AND si.status NOT IN ('Credit Note Issued', 'Return')
		  AND {_CERTIFICADA}
		  {filtro_branch}
		ORDER BY si.outstanding_amount DESC
	""", params, as_dict=True)

	return {
		"configuracion": {
			"fecha_de_corte": cutoff,
			"envio_automatico": cfg.get("enable_auto_send"),
			"series_activas": [s["name"] for s in series],
			"sucursales_cubiertas": sorted(cubiertas),
		},
		"cobradas_sin_certificar": {
			"total": len(pendientes),
			"significa": "El cliente pagó y el documento fiscal todavía no existe ante el SENIAT",
			"por_motivo": sorted(por_motivo.values(), key=lambda b: -b["count"]),
		},
		"certificadas_sin_cobrar": {
			"total": len(sin_cobrar),
			"pendiente_por_moneda": _por_moneda(sin_cobrar),
			"aviso_moneda": (
				"El pendiente está en moneda de la COMPAÑÍA (bolívares); el total de cada "
				"factura está en la suya. No los sumes ni los presentes con la misma etiqueta."
			),
			"significa": (
				"El documento fiscal ya está ante el SENIAT y el dinero no entró. Una "
				"factura mal emitida NO se deshace: se anula con nota de crédito y se "
				"reemite. Antes de proponer nada, hay que entender por qué se emitió."
			),
			"muestra": [
				{
					"invoice": r.name, "cliente": r.customer_name, "sucursal": r.branch,
					"fecha": str(r.posting_date), "estado": r.status,
					"total": flt(r.grand_total), "moneda_total": r.currency,
					"pendiente": flt(r.outstanding_amount),
					"moneda_pendiente": _moneda_compania(r.company),
					"control_fiscal": r.bill_control,
				}
				for r in sin_cobrar[:limit]
			],
		},
		"nota": (
			"«Certificada» significa que tiene número de control fiscal o un log de envío "
			"exitoso. NO se usa hka_status: está vacío en miles de facturas sí certificadas "
			"y una métrica basada en ese campo reportó 8.001 pendientes cuando eran 2."
		),
	}


#: Una factura "tiene retención del cliente pendiente" con la MISMA definición que
#: usa `tasks.send_missing_retentions_reminders`, el cron que persigue el
#: comprobante. Se repite acá y no se importa porque allá vive embebida en el
#: envío de correo; si esa definición cambia, esta tiene que cambiar con ella.
#:
#: Las cuatro condiciones importan: emitida, cliente que retiene, factura con
#: número fiscal, y línea de retención con monto. Sin la tercera entran facturas
#: que todavía no existen ante el SENIAT y nadie puede retener sobre ellas.
_RETENIDA_POR_CLIENTE = """
	si.docstatus = 1
	AND (
		c.is_special_taxpayer = 1
		OR (c.tabulator_islr IS NOT NULL AND c.tabulator_islr != '' AND c.tabulator_islr != 'None')
	)
	AND si.bill_no IS NOT NULL AND si.bill_no != ''
	AND si.bill_control IS NOT NULL AND si.bill_control != ''
	AND stc.charge_type IN ('VAT Withholding', 'ISLR')
	AND stc.tax_amount != 0
"""

#: Vacío = el cliente no nos entregó el comprobante. El campo depende del impuesto.
_SIN_COMPROBANTE = """
	(
		(stc.charge_type = 'VAT Withholding' AND (si.vat_withholding_voucher_number IS NULL
			OR si.vat_withholding_voucher_number = '' OR si.vat_withholding_voucher_number = 'None'))
		OR
		(stc.charge_type = 'ISLR' AND (si.islr_receipt_number IS NULL
			OR si.islr_receipt_number = '' OR si.islr_receipt_number = 'None'))
	)
"""


def check_customer_retentions(months: int = 3, branch: str | None = None, limit: int = 15) -> dict:
	"""Retenciones que nos hicieron los clientes y cuyo comprobante NO llegó.

	Es el reverso de ``check_retentions``: aquélla mira los comprobantes que
	emitimos nosotros hacia el SENIAT; ésta, los que **nos deben entregar**.

	Por qué importa y no es burocracia: cuando un contribuyente especial paga una
	factura, retiene una parte del IVA o del ISLR y la entera él al SENIAT. Ese
	dinero ya salió del cobro. **Sin el comprobante no se puede acreditar**, así
	que figura como una factura cobrada de menos y el monto retenido queda en el
	aire hasta que el cliente lo entregue.

	El reporte «Customer Retention» muestra el número de comprobante, pero no deja
	filtrar por los que faltan — y peor: cuando falta, la columna de monto retenido
	se muestra en 0, así que la fila parece "sin retención" en vez de "pendiente".
	Por eso acá se cuenta al revés: lo que falta primero.
	"""
	meses = max(1, min(cint(months) or 3, 24))
	tope = max(1, min(cint(limit) or 15, MAX_ROWS))
	desde = add_months(nowdate(), -meses)

	condiciones = [_RETENIDA_POR_CLIENTE, "si.posting_date >= %(desde)s"]
	params = {"desde": desde}
	if branch:
		condiciones.append("si.branch = %(branch)s")
		params["branch"] = branch

	base = " AND ".join(f"({c})" for c in condiciones)

	filas = frappe.db.sql(
		f"""
		SELECT
			si.customer, si.customer_name, si.name AS factura, si.bill_no,
			si.posting_date, si.currency, stc.charge_type,
			ABS(stc.base_tax_amount) AS monto,
			CASE WHEN {_SIN_COMPROBANTE} THEN 0 ELSE 1 END AS tiene_comprobante
		FROM `tabSales Invoice` si
		JOIN `tabSales Taxes and Charges` stc ON stc.parent = si.name
		JOIN `tabCustomer` c ON c.name = si.customer
		WHERE {base}
		ORDER BY si.posting_date
		""",
		params,
		as_dict=True,
	)

	faltan = [f for f in filas if not f.tiene_comprobante]
	llegaron = [f for f in filas if f.tiene_comprobante]

	por_cliente: dict[str, dict] = {}
	for f in faltan:
		b = por_cliente.setdefault(
			f.customer, {"cliente": f.customer_name or f.customer, "facturas": 0, "monto": 0.0}
		)
		b["facturas"] += 1
		b["monto"] = round(b["monto"] + flt(f.monto), 2)

	ranking = sorted(por_cliente.values(), key=lambda b: -b["monto"])[:tope]
	total_pendiente = round(sum(flt(f.monto) for f in faltan), 2)

	return {
		"periodo": f"desde {desde}",
		"significa": (
			"El cliente retuvo IVA o ISLR al pagar y todavía no entregó el comprobante. "
			"Sin ese papel el monto retenido NO se puede acreditar ante el SENIAT."
		),
		"sin_comprobante": len(faltan),
		"con_comprobante": len(llegaron),
		"monto_pendiente": total_pendiente,
		"moneda": _moneda_compania(None),
		"por_cliente": ranking,
		"nota": (
			"Los montos son de la moneda de la compañía. «sin_comprobante» cuenta LÍNEAS "
			"de retención, no facturas: una factura puede tener IVA e ISLR y contar dos veces."
		),
	}

TOOLS = [
	{
		"name": "check_customer_retentions",
		"handler": check_customer_retentions,
		"writes": False,
		"description": (
			"Retenciones que los CLIENTES nos hicieron y cuyo comprobante todavía no "
			"entregaron.\n"
			"Usala para «qué comprobantes de retención faltan», «quién no me mandó el "
			"comprobante», «cuánto tengo retenido sin acreditar».\n"
			"NO la confundas con check_retentions, que mira los comprobantes que emitimos "
			"NOSOTROS. Ésta es el reverso: lo que nos deben entregar. Sin ese papel el monto "
			"retenido no se puede acreditar ante el SENIAT."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"months": {"type": "integer", "description": "Meses hacia atrás. Por defecto 3."},
				"branch": {"type": "string", "description": "Sucursal (VE Branch), opcional."},
				"limit": {"type": "integer", "description": "Cuántos clientes listar."},
			},
		},
	},
	{
		"name": "check_hka",
		"handler": check_hka,
		"writes": False,
		"description": (
			"Diagnóstico de facturación digital ante el SENIAT (HKA / The Factory HKA).\n"
			"Usala para «qué facturas no se enviaron a HKA», «por qué esta factura no se "
			"certificó», «hay facturas cobradas sin documento fiscal», «cómo va la "
			"facturación digital».\n"
			"\n"
			"Devuelve DOS cohortes opuestas:\n"
			"  · cobradas_sin_certificar → el cliente pagó y el documento fiscal no existe.\n"
			"    Viene desglosado POR MOTIVO: sucursal fuera de serie activa, anterior a la\n"
			"    fecha de corte, rechazo del último intento, tasa desincronizada, o "
			"simplemente en cola.\n"
			"  · certificadas_sin_cobrar → el documento ya está ante el SENIAT y el dinero\n"
			"    no entró.\n"
			"\n"
			"REPORTÁ EL MOTIVO, no solo el total. Cada motivo se arregla distinto y varios "
			"no son un error: «anterior a la fecha de corte» es el comportamiento esperado.\n"
			"\n"
			"Los montos vienen agrupados POR MONEDA. Este sistema opera en USD y bolívares "
			"a la vez: decí siempre cuál, y nunca los sumes.\n"
			"\n"
			"NO propongas anular ni reemitir una factura ya certificada. Ante el SENIAT eso "
			"exige nota de crédito y reemisión, es irreversible, y no es una decisión que "
			"se tome desde un chat: describí el caso y quién debe revisarlo."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"branch": {"type": "string", "description": "Acotar a una sucursal (VE Branch)."},
				"limit": {"type": "integer", "description": "Filas de muestra por motivo (por defecto 10, techo 25)."},
			},
			"required": [],
		},
	},
]
