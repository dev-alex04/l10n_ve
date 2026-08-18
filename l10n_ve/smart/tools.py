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
from frappe.utils import cint, flt

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



# ---------------------------------------------------------------------------
# Retenciones
# ---------------------------------------------------------------------------
#
# Comprobantes que ESTA empresa le emite a sus proveedores, de ISLR y de IVA.
# La otra cara —las retenciones que los entes de gobierno nos hacen a nosotros—
# vive en `VE Payment Government Withholding` y NO se expone: en el site medido
# tiene 0 filas y 0 configuración, así que una herramienta ahí devolvería un vacío
# que se lee como «no hay retenciones» en vez de «esto no se usa».

#: Los dos comprobantes, con lo que cambia entre uno y otro. Se declara la
#: diferencia en un solo lugar para no escribir dos veces la misma consulta.
_RETENCIONES = {
	"ISLR": {
		"doctype": "ISLR Withholding Voucher",
		"fecha": "posting_date",
		"retenido": "totals_islr_amount",
		"base": "totals_islr_base_amount",
	},
	"IVA": {
		"doctype": "VAT Withholding Voucher",
		"fecha": "issue_date",
		"retenido": "totals_tax_amount_vat",
		"base": "totals_total",
	},
}


#: Techo de filas por impuesto. Existe para que una ventana larga no traiga la
#: tabla entera a memoria, y **se reporta si se alcanza**: un total calculado
#: sobre una cohorte recortada es un número equivocado con cara de correcto, que
#: es peor que no dar número.
_TECHO_FILAS = 5000


def _retenciones_de(
	impuesto: str, desde: str, branch: str | None = None, supplier: str | None = None
) -> tuple[list[frappe._dict], bool]:
	"""Comprobantes EMITIDOS de un impuesto desde una fecha.

	Devuelve ``(filas, truncado)``. El filtro por proveedor va en la CONSULTA y no
	después en Python: traer cinco mil filas para quedarse con cuatro es pedirle a
	MariaDB el trabajo que después se tira.

	Se usa ``frappe.get_all`` y no SQL crudo a propósito: aplica los permisos del
	usuario de la sesión, que es lo que domina_smart promete. ``check_hka``, más
	arriba, usa ``frappe.db.sql`` y por lo tanto NO los aplica — es una diferencia
	conocida, y esta es la que hay que imitar.
	"""
	cfg = _RETENCIONES[impuesto]
	filtros = {"docstatus": 1, cfg["fecha"]: [">=", desde]}
	if branch:
		filtros["branch"] = branch
	if supplier:
		filtros["supplier"] = supplier

	filas = frappe.get_all(
		cfg["doctype"],
		filters=filtros,
		fields=[
			"name", "supplier", "supplier_name", "branch", "voucher_number",
			"bill_control", "digital_invoice_status",
			f"{cfg['fecha']} as fecha",
			f"{cfg['retenido']} as retenido",
			f"{cfg['base']} as base",
		],
		order_by=f"{cfg['fecha']} desc",
		limit=_TECHO_FILAS,
	)
	return filas, len(filas) >= _TECHO_FILAS


def check_retentions(months: int = 3, branch: str | None = None, limit: int = 10) -> dict:
	"""Salud de los comprobantes de retención: cuáles no llegaron al SENIAT.

	**Certificado = tiene número de control**, igual que en `check_hka` y por la
	misma razón que documenta el AGENTS.md de esta app: el campo de estado no es
	evidencia. Acá se midió el caso exacto —dos comprobantes con
	``digital_invoice_status = 'Error'`` cuyo ``hka_response`` traía serie, número
	de documento y número de control asignados—. El estado decía que falló y el
	documento estaba ante el SENIAT.

	Por eso se reportan DOS cosas distintas:

	* **sin_control** — el problema de verdad: emitido y sin número de control, o
	  sea que legalmente no existe ante el SENIAT.
	* **estado_inconsistente** — tiene control pero el estado dice Error. El
	  documento está bien; lo que está mal es el campo. No se arregla reemitiendo.

	NO se usa ``is_declared``: en las 454 filas del site medido vale 0 sin una sola
	excepción. Un indicador que nunca cambia no informa; reportarlo diría «368 sin
	declarar» todos los meses y nadie volvería a leerlo.
	"""
	meses = max(1, min(cint(months) or 3, 24))
	limite = max(1, min(cint(limit) or 10, MAX_ROWS))
	desde = frappe.utils.add_months(frappe.utils.nowdate(), -meses)

	def _muestra(filas):
		return [
			{
				"comprobante": r.name,
				"proveedor": r.supplier_name or r.supplier,
				"fecha": str(r.fecha) if r.fecha else None,
				"retenido_bs": flt(r.retenido),
				"numero_control": r.bill_control or None,
				"estado": r.digital_invoice_status or None,
			}
			for r in filas[:limite]
		]

	por_impuesto = {}
	for impuesto in _RETENCIONES:
		filas, truncado = _retenciones_de(impuesto, desde, branch)
		sin_control = [r for r in filas if not (r.bill_control or "").strip()]
		inconsistentes = [
			r for r in filas
			if (r.bill_control or "").strip() and (r.digital_invoice_status or "") == "Error"
		]

		# Quién concentra la retención. Va en el payload y NO en la descripción:
		# responde «¿a quién le retuvimos más?» sin sumarle un token al preámbulo,
		# que viaja en CADA llamada al modelo aunque nadie pregunte eso.
		#
		# Es además lo más cerca que queda de la consulta por proveedor, mientras
		# `get_supplier_retentions` siga afuera (ver la nota antes de TOOLS).
		acumulado: dict[str, float] = {}
		nombres: dict[str, str] = {}
		for r in filas:
			if not r.supplier:
				continue
			acumulado[r.supplier] = acumulado.get(r.supplier, 0.0) + flt(r.retenido)
			nombres[r.supplier] = r.supplier_name or r.supplier

		top = sorted(acumulado.items(), key=lambda kv: -kv[1])[:5]

		por_impuesto[impuesto] = {
			"emitidos": len(filas),
			# Si se alcanzó el techo, el total está calculado sobre una cohorte
			# recortada: se avisa en vez de dejarlo pasar como si fuera exacto.
			"parcial": truncado,
			"retenido_bs": round(sum(flt(r.retenido) for r in filas), 2),
			"top_proveedores": [
				{"supplier": s_id, "proveedor": nombres[s_id], "retenido_bs": round(monto, 2)}
				for s_id, monto in top
			],
			"sin_control": {
				"count": len(sin_control),
				"significa": "Emitido y SIN número de control: ante el SENIAT no existe",
				"muestra": _muestra(sin_control),
			},
			"estado_inconsistente": {
				"count": len(inconsistentes),
				"significa": (
					"Tiene número de control pero el estado dice Error. El documento está "
					"ante el SENIAT; lo que está mal es el campo. NO se reemite"
				),
				"muestra": _muestra(inconsistentes),
			},
		}

	return {
		"desde": desde,
		"branch": branch,
		"por_impuesto": por_impuesto,
		"moneda": "Bs",
		"nota": (
			"Los montos están en BOLÍVARES. Estos comprobantes no tienen campo de moneda: "
			"van en la moneda de la compañía, y la retención se declara en bolívares. NO los "
			"reportes como USD ni los conviertas."
		),
	}

# `get_supplier_retentions` —las retenciones de UN proveedor— se escribió, se probó
# contra datos reales y NO se incluye. Medido: sola no molesta (5/5), pero JUNTO a
# `check_retentions` tumba `natural-morosos-navegando` de domina_isp, un caso que no
# tiene nada que ver con retenciones: de 5/5 a 0/3, y a 2/5 tras recortarle la
# descripción. No es el tamaño del catálogo —una 18ª herramienta placebo no rompe
# nada— sino que las dos se parecen demasiado entre sí.
#
# Se despacha una sola y la otra queda pendiente de una redacción que no compita.


TOOLS = [
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
	{
		"name": "check_retentions",
		"handler": check_retentions,
		"writes": False,
		"description": (
			"Salud de los comprobantes de RETENCIÓN que esta empresa le emite a sus "
			"proveedores, de ISLR y de IVA.\n"
			"Usala para «cómo van las retenciones», «qué comprobantes no llegaron al "
			"SENIAT», «cuánto retuvimos este mes», «hay retenciones con problemas».\n"
			"NO es para facturas de venta — para eso está check_hka.\n"
			"\n"
			"Devuelve DOS cohortes que NO son lo mismo y se arreglan distinto:\n"
			"  · sin_control → emitido y sin número de control: ante el SENIAT no existe.\n"
			"    Es el problema de verdad.\n"
			"  · estado_inconsistente → tiene número de control pero el campo de estado dice\n"
			"    Error. El documento SÍ está ante el SENIAT; lo que está mal es el campo.\n"
			"    NO propongas reemitirlo: se reemitiría algo que ya existe.\n"
			"\n"
			"MONTOS EN BOLÍVARES, siempre. Estos comprobantes no tienen campo de moneda y la "
			"retención se declara en Bs. Nunca los reportes como USD ni los conviertas.\n"
			"No propongas anular ni reemitir un comprobante certificado: ante el SENIAT eso "
			"no es una corrección, es otro trámite. Describí el caso y quién debe verlo."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"months": {"type": "integer", "description": "Meses hacia atrás (por defecto 3, techo 24)."},
				"branch": {"type": "string", "description": "Acotar a una sucursal (VE Branch)."},
				"limit": {"type": "integer", "description": "Filas de muestra por cohorte (por defecto 10, techo 25)."},
			},
			"required": [],
		},
	},
]
