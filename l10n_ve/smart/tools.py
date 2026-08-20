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

def _company(company: str | None) -> str:
	"""La empresa, validada. Una que no existe hace que todo dé cero sin error."""
	company = company or frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company or not frappe.db.exists("Company", company):
		existentes = ", ".join(frappe.get_all("Company", pluck="name")) or "ninguna"
		frappe.throw(
			f"No existe la empresa «{company or '(sin empresa)'}». Preguntando por una "
			f"empresa equivocada las consultas dan cero y parece que no hay datos. "
			f"Empresas: {existentes}."
		)
	return company


def check_bank_reconciliation(
	bank_account: str | None = None, to_date: str | None = None, company: str | None = None
) -> dict:
	"""Cuánto del extracto bancario está conciliado contra la contabilidad, y cuánto no.

	Nace del caso que no se podía contestar. La contadora dijo «el banco cerró en 290
	mil bolívares pero acá la cuenta tiene 29 millones», y el asistente —que no tenía
	ninguna herramienta de conciliación— contestó con lo único parecido que encontró:
	«no se cargaron los saldos iniciales», más dos causas inventadas. Ninguna era.

	La causa real: de 13.353 movimientos del extracto de esa cuenta, **3.369 nunca se
	cruzaron contra la contabilidad**. El mayor y el banco son dos universos que no se
	tocaron, y por eso no coinciden.

	El saldo del mayor de una cuenta con conciliación pendiente **no es comparable**
	con lo que dice el banco. Devolverlo sin esa advertencia es dar por respuesta el
	número que la persona está señalando como el problema.
	"""
	company = _company(company)
	to_date = to_date or frappe.utils.nowdate()

	# `filtro` es uno de DOS literales fijos, elegidos por un booleano -- nunca
	# contiene entrada del usuario. La cuenta viaja como parametro (`%(cuenta)s`),
	# que es justo lo que la regla quiere. Semgrep marca el f-string sin poder
	# distinguir "interpola un literal" de "interpola lo que mando el cliente".
	filtro = "AND bt.bank_account = %(cuenta)s" if bank_account else ""
	filas = frappe.db.sql(  # nosemgrep
		f"""SELECT bt.bank_account, bt.status, COUNT(*) n,
		           ROUND(SUM(bt.deposit),2) depositos, ROUND(SUM(bt.withdrawal),2) retiros
		    FROM `tabBank Transaction` bt
		    WHERE bt.docstatus = 1 AND bt.date <= %(hasta)s AND bt.company = %(company)s
		      {filtro}
		    GROUP BY bt.bank_account, bt.status""",
		{"hasta": to_date, "company": company, "cuenta": bank_account},
		as_dict=True,
	)

	por_cuenta: dict[str, dict] = {}
	for f in filas:
		d = por_cuenta.setdefault(f.bank_account, {
			"bank_account": f.bank_account, "conciliados": 0, "sin_conciliar": 0,
			"depositos_sin_conciliar": 0.0, "retiros_sin_conciliar": 0.0,
		})
		if f.status == "Reconciled":
			d["conciliados"] += f.n
		else:
			d["sin_conciliar"] += f.n
			d["depositos_sin_conciliar"] = round(d["depositos_sin_conciliar"] + flt(f.depositos), 2)
			d["retiros_sin_conciliar"] = round(d["retiros_sin_conciliar"] + flt(f.retiros), 2)

	cuentas = []
	for d in por_cuenta.values():
		total = d["conciliados"] + d["sin_conciliar"]
		d["movimientos"] = total
		d["porcentaje_sin_conciliar"] = round(d["sin_conciliar"] / total * 100, 1) if total else 0.0

		# El saldo contable de la cuenta a la que apunta esta cuenta bancaria. Es el
		# número que la gente compara contra el banco, y el que hay que calificar.
		cuenta_contable = frappe.db.get_value("Bank Account", d["bank_account"], "account")
		d["cuenta_contable"] = cuenta_contable
		if cuenta_contable:
			saldo = frappe.db.sql(
				"""SELECT ROUND(SUM(debit)-SUM(credit),2) FROM `tabGL Entry`
				   WHERE account=%(cuenta)s AND posting_date <= %(hasta)s
				     AND IFNULL(is_cancelled,0)=0""",
				{"cuenta": cuenta_contable, "hasta": to_date},
			)[0][0]
			d["saldo_contable"] = flt(saldo)

		d["veredicto"] = (
			f"{d['porcentaje_sin_conciliar']}% del movimiento no está conciliado: el saldo "
			f"contable NO es comparable con el del banco."
			if d["porcentaje_sin_conciliar"] >= 1
			else "Conciliada: el saldo contable sí es comparable con el del banco."
		)
		cuentas.append(d)

	cuentas.sort(key=lambda d: -d["porcentaje_sin_conciliar"])
	return {
		"company": company,
		"al": to_date,
		"cuentas": cuentas,
		"moneda": frappe.get_cached_value("Company", company, "default_currency"),
		"nota": (
			"Una diferencia entre lo que dice el banco y lo que dice la contabilidad casi "
			"siempre es conciliación pendiente, NO saldos iniciales faltantes ni un error "
			"de decimales.\n"
			"Si una cuenta tiene movimiento sin conciliar, decilo ANTES de dar su saldo: "
			"ese saldo es exactamente el número que la persona está cuestionando."
		),
	}


def account_balance_by_party(
	account: str, to_date: str | None = None, limit: int = 15, company: str | None = None
) -> dict:
	"""El saldo de una cuenta de clientes o proveedores, repartido por parte, a una fecha.

	Existe porque ningún reporte del catálogo lo contesta bien. Se probaron los tres
	candidatos contra el mayor: `Accounts Receivable` al 30-06-2026 devolvió
	**−707.874,52** donde el mayor dice **+544.297,79**, y `Trial Balance for Party`
	lista las 2.419 partes en vez de las 416 que tienen saldo. Un reporte que no
	reconcilia entrega un número plausible y falso.

	Sale del MAYOR, no de ``outstanding_amount``: ese campo es el estado de HOY y no
	sirve para una fecha pasada.
	"""
	company = _company(company)
	to_date = to_date or frappe.utils.nowdate()
	limit = max(1, min(cint(limit) or 15, MAX_ROWS))

	cuenta = account if frappe.db.exists("Account", account) else frappe.db.get_value(
		"Account", {"company": company, "name": ["like", f"{account}%"]}, "name"
	) or frappe.db.get_value(
		"Account", {"company": company, "account_name": ["like", f"%{account}%"]}, "name"
	)
	if not cuenta:
		frappe.throw(
			f"No encuentro la cuenta «{account}». Pasá el código o el nombre tal como "
			f"figura en el plan de cuentas."
		)

	filas = frappe.db.sql(
		"""SELECT gl.party_type, gl.party, ROUND(SUM(gl.debit)-SUM(gl.credit),2) saldo
		   FROM `tabGL Entry` gl
		   WHERE gl.account = %(cuenta)s AND gl.posting_date <= %(hasta)s
		     AND IFNULL(gl.is_cancelled,0)=0 AND IFNULL(gl.party,'') <> ''
		   GROUP BY gl.party_type, gl.party
		   HAVING ROUND(SUM(gl.debit)-SUM(gl.credit),2) <> 0
		   ORDER BY ABS(ROUND(SUM(gl.debit)-SUM(gl.credit),2)) DESC""",
		{"cuenta": cuenta, "hasta": to_date},
		as_dict=True,
	)

	total_cuenta = frappe.db.sql(
		"""SELECT ROUND(SUM(debit)-SUM(credit),2) FROM `tabGL Entry`
		   WHERE account=%(cuenta)s AND posting_date <= %(hasta)s AND IFNULL(is_cancelled,0)=0""",
		{"cuenta": cuenta, "hasta": to_date},
	)[0][0]

	suma_partes = round(sum(flt(f.saldo) for f in filas), 2)
	return {
		"cuenta": cuenta,
		"al": to_date,
		"partes_con_saldo": len(filas),
		"suma_de_partes": suma_partes,
		"saldo_de_la_cuenta": flt(total_cuenta),
		"cuadra": abs(suma_partes - flt(total_cuenta)) < 0.01,
		"moneda": frappe.get_cached_value("Company", company, "default_currency"),
		"mayores": [
			{"parte": f.party, "tipo": f.party_type, "saldo": flt(f.saldo)} for f in filas[:limit]
		],
		"nota": (
			f"Son {len(filas)} partes con saldo distinto de cero, no el total de clientes "
			f"registrados. Si `cuadra` es false hay movimiento en la cuenta SIN parte "
			f"asignada, y la diferencia es ese monto: {round(flt(total_cuenta) - suma_partes, 2)}.\n"
			"Los montos salen del mayor a la fecha pedida, no del pendiente actual de cada "
			"documento. Para una fecha pasada son cosas distintas."
		),
	}


def check_period_impact(from_date: str, to_date: str, company: str | None = None) -> dict:
	"""Qué hay en un período contable y qué se rompería si se toca.

	La pregunta que originó todo esto fue «lo de enero a junio es basura, ¿lo podemos
	borrar?», y contestarla bien exige cuatro cosas a la vez: cuánto hay, qué de eso
	sostiene documentos posteriores, qué ya se declaró ante el SENIAT, y qué queda
	abierto. Por separado ninguna alcanza.

	Sin esto el asistente contestaba «no se puede» —conclusión correcta— **sin una
	sola cifra**: un razonamiento genérico de ERPNext que no menciona que detrás del
	período hay 24.138 documentos ni que 5.873 pagos sostienen facturas posteriores.
	"""
	company = _company(company)

	volumen = frappe.db.sql(
		"""SELECT voucher_type, COUNT(DISTINCT voucher_no) documentos, COUNT(*) asientos
		   FROM `tabGL Entry`
		   WHERE posting_date BETWEEN %(desde)s AND %(hasta)s
		     AND IFNULL(is_cancelled,0)=0 AND company=%(company)s
		   GROUP BY voucher_type ORDER BY documentos DESC""",
		{"desde": from_date, "hasta": to_date, "company": company},
		as_dict=True,
	)

	# Lo que ATA el período a lo que vino después. En un ISP con pagos por adelantado
	# la facturación de cada mes vuelve a tomar un pago viejo, así que borrarlo deja
	# sin pago a facturas que ya se emitieron.
	cruce = frappe.db.sql(
		"""SELECT COUNT(DISTINCT pe.name) pagos, COUNT(DISTINCT si.name) facturas,
		          ROUND(SUM(per.allocated_amount),2) monto
		   FROM `tabPayment Entry Reference` per
		   JOIN `tabPayment Entry` pe ON pe.name = per.parent
		   JOIN `tabSales Invoice` si ON si.name = per.reference_name
		   WHERE pe.docstatus=1 AND si.docstatus=1 AND per.reference_doctype='Sales Invoice'
		     AND pe.posting_date BETWEEN %(desde)s AND %(hasta)s
		     AND si.posting_date > %(hasta)s""",
		{"desde": from_date, "hasta": to_date},
		as_dict=True,
	)[0]

	# Certificado ante el SENIAT = lo irreversible. Un período sin nada emitido se
	# puede corregir sin riesgo fiscal; uno con documentos emitidos, no.
	#
	# Las dos señales van SEPARADAS y no se colapsan en una, porque en datos reales
	# divergen y colapsarlas miente. Medido sobre ene-jun 2026: 7.155 facturas con
	# `bill_control` pero solo 2.386 con log de transmisión — el número de control de
	# enero a mayo viene de otro lado (formato `00549` contra el `00-00235350` que
	# devuelve HKA) y en ese tramo hay UN solo log, de Error. Tomar `bill_control`
	# como prueba de transmisión daba 7.155 documentos «ante el SENIAT» que nunca
	# llegaron.
	fiscal = frappe.db.sql(
		f"""SELECT
		      SUM(CASE WHEN EXISTS(
		            SELECT 1 FROM `tabVE Digital Invoice Log` l
		            WHERE l.sales_invoice = si.name AND l.status = 'Success'
		              AND l.document_type = 'Sales Invoice') THEN 1 ELSE 0 END) transmitidas,
		      SUM(CASE WHEN IFNULL(si.bill_control,'') <> '' THEN 1 ELSE 0 END) con_control,
		      COUNT(*) facturas
		    FROM `tabSales Invoice` si
		    WHERE si.docstatus=1 AND si.company=%(company)s
		      AND si.posting_date BETWEEN %(desde)s AND %(hasta)s""",
		{"desde": from_date, "hasta": to_date, "company": company},
		as_dict=True,
	)[0]

	# Cartera abierta del período, por las DOS vías, porque divergen y esa divergencia
	# es un hallazgo en sí: una factura puede figurar pagada en el documento y seguir
	# con saldo en el mayor.
	segun_mayor = frappe.db.sql(
		"""SELECT COUNT(*) c, ROUND(SUM(s),2) monto FROM (
		     SELECT gl.against_voucher, ROUND(SUM(gl.debit)-SUM(gl.credit),2) s
		     FROM `tabGL Entry` gl JOIN `tabAccount` a ON a.name = gl.account
		     WHERE a.account_type='Receivable' AND a.company=%(company)s
		       AND gl.posting_date <= %(hasta)s AND IFNULL(gl.is_cancelled,0)=0
		       AND gl.against_voucher_type='Sales Invoice' AND IFNULL(gl.against_voucher,'')<>''
		     GROUP BY gl.against_voucher
		     HAVING ROUND(SUM(gl.debit)-SUM(gl.credit),2) > 0) t""",
		{"hasta": to_date, "company": company},
		as_dict=True,
	)[0]
	segun_documento = frappe.db.sql(
		"""SELECT COUNT(*) c, ROUND(SUM(outstanding_amount),2) monto FROM `tabSales Invoice`
		   WHERE docstatus=1 AND company=%(company)s AND outstanding_amount > 0
		     AND posting_date BETWEEN %(desde)s AND %(hasta)s""",
		{"desde": from_date, "hasta": to_date, "company": company},
		as_dict=True,
	)[0]

	total_docs = sum(v.documentos for v in volumen)
	total_asientos = sum(v.asientos for v in volumen)

	return {
		"company": company,
		"periodo": {"desde": from_date, "hasta": to_date},
		"volumen": {
			"documentos": total_docs,
			"asientos": total_asientos,
			"por_tipo": [dict(v) for v in volumen],
		},
		"ata_documentos_posteriores": {
			"pagos": cruce.pagos or 0,
			"facturas_posteriores": cruce.facturas or 0,
			"monto": flt(cruce.monto),
			"significa": (
				"Pagos con fecha DENTRO del período que están aplicados a facturas de "
				"DESPUÉS. Si el período se elimina, esas facturas quedan sin pago."
			),
		},
		"certificado_ante_el_seniat": {
			"facturas_del_periodo": cint(fiscal.facturas),
			"con_log_de_transmision": cint(fiscal.transmitidas),
			"con_numero_de_control": cint(fiscal.con_control),
			"significa": (
				"`con_log_de_transmision` es la evidencia REAL de que el documento llegó al "
				"SENIAT. `con_numero_de_control` es más débil: puede venir de una carga "
				"histórica y no de una emisión.\n"
				"Si `con_log_de_transmision` es 0, corregir el período no tiene riesgo "
				"fiscal. Si no lo es, ESOS documentos ya están declarados y no se deshacen: "
				"se anulan con nota de crédito y se reemiten."
			),
		},
		"cartera_abierta": {
			"segun_el_mayor_al_corte": {"facturas": segun_mayor.c or 0, "monto": flt(segun_mayor.monto)},
			"segun_el_documento_hoy": {"facturas": segun_documento.c or 0, "monto": flt(segun_documento.monto)},
			"significa": (
				"Las dos vías miden cosas distintas y suelen NO coincidir. El mayor dice "
				"cuánto se debía a la fecha de corte; `outstanding_amount` dice cuánto "
				"queda HOY. Una brecha grande además delata facturas que figuran pagadas "
				"en el documento mientras el mayor les sigue viendo deuda."
			),
		},
		"moneda": frappe.get_cached_value("Company", company, "default_currency"),
		"nota": (
			"Para un saldo inicial a una fecha pasada se usa el mayor, nunca el pendiente "
			"actual del documento.\n"
			"Si alguien plantea borrar o depurar el período, comprobá ADEMÁS que exista "
			"la apertura con check_opening_balances: sin ella no hay respaldo debajo."
		),
	}


def check_opening_balances(company: str | None = None) -> dict:
	"""¿Se cargaron los saldos iniciales, o solo se supone que sí?

	Nace de un caso real. La contadora de un cliente pidió depurar el primer
	semestre «considerando que ya fueron cargados en el sistema los saldos
	iniciales». No lo estaban. Si se borraba el semestre creyendo que había
	respaldo, no quedaba respaldo: quedaba un vacío.

	Se le preguntó eso mismo al asistente antes de que esta herramienta existiera y
	**confirmó la premisa falsa**: miró que las cuentas tenían saldo y lo dio por
	bueno. Ese es justo el razonamiento que hay que impedir — que una cuenta tenga
	movimiento no dice NADA sobre si hubo apertura; lo único que dice es que la
	empresa operó.

	Por eso se responde con cuatro vías independientes y su evidencia, y no con un
	sí o un no. Ninguna basta sola: la bandera ``is_opening`` puede no marcarse, y
	entonces un cero ahí no probaría nada. Pero una carga de saldos iniciales
	**necesariamente** mueve patrimonio —ahí va el resultado acumulado del ejercicio
	anterior— y **necesariamente** se contabiliza contra una cuenta transitoria de
	apertura. Que esas dos estén vacías sí concluye.
	"""
	# La validación importa el doble acá: una empresa que no existe haría que las
	# cuatro vías den cero y esta herramienta respondería «no hay apertura» con toda
	# seguridad. Es el peor lugar del sistema para un falso negativo silencioso,
	# porque es justo la respuesta que autoriza a borrar.
	company = _company(company)

	def contar(sql, **kw):
		return int(frappe.db.sql(sql, {"company": company, **kw})[0][0] or 0)

	asientos_marcados = contar(
		"""SELECT COUNT(*) FROM `tabJournal Entry`
		   WHERE docstatus=1 AND is_opening='Yes' AND company=%(company)s"""
	)
	lineas_marcadas = contar(
		"""SELECT COUNT(*) FROM `tabGL Entry`
		   WHERE IFNULL(is_cancelled,0)=0 AND is_opening='Yes' AND company=%(company)s"""
	)
	patrimonio = contar(
		"""SELECT COUNT(*) FROM `tabGL Entry` gl JOIN `tabAccount` a ON a.name=gl.account
		   WHERE IFNULL(gl.is_cancelled,0)=0 AND a.root_type='Equity'
		     AND gl.company=%(company)s"""
	)
	transitorias = contar(
		"""SELECT COUNT(*) FROM `tabAccount`
		   WHERE company=%(company)s AND (account_type='Temporary'
		     OR LOWER(account_name) LIKE '%%apertura%%'
		     OR LOWER(account_name) LIKE '%%transitoria%%')"""
	)

	vias = [
		{
			"via": "Asientos marcados como apertura",
			"encontrado": asientos_marcados + lineas_marcadas,
			"significa": (
				"Sola no concluye: una apertura puede cargarse sin marcar la casilla, "
				"así que un cero acá no prueba nada por sí mismo."
			),
		},
		{
			"via": "Movimientos en cuentas de patrimonio",
			"encontrado": patrimonio,
			"significa": (
				"Concluyente. Toda carga de saldos iniciales mueve patrimonio, porque ahí "
				"se registra el resultado acumulado del ejercicio anterior."
			),
		},
		{
			"via": "Cuentas transitorias de apertura en el plan",
			"encontrado": transitorias,
			"significa": (
				"Concluyente. La contrapartida de una apertura va contra una cuenta "
				"transitoria; si no existe en el plan, no se cargó por esta vía."
			),
		},
	]

	# La firma de una apertura es tocar muchas cuentas de balance de una sola vez.
	# Ningún asiento operativo se parece a eso.
	amplio = frappe.db.sql(
		"""SELECT gl.voucher_no, COUNT(DISTINCT gl.account) cuentas
		   FROM `tabGL Entry` gl JOIN `tabAccount` a ON a.name=gl.account
		   WHERE IFNULL(gl.is_cancelled,0)=0 AND gl.company=%(company)s
		     AND a.root_type IN ('Asset','Liability','Equity')
		   GROUP BY gl.voucher_no HAVING cuentas >= 6
		   ORDER BY cuentas DESC LIMIT 5""",
		{"company": company},
		as_dict=True,
	)
	vias.append({
		"via": "Asientos que tocan 6 o más cuentas de balance",
		"encontrado": len(amplio),
		"significa": "Es la firma de una apertura. Ningún asiento operativo la tiene.",
		"ejemplos": [a.voucher_no for a in amplio],
	})

	primer = frappe.db.sql(
		"""SELECT MIN(posting_date) FROM `tabGL Entry`
		   WHERE IFNULL(is_cancelled,0)=0 AND company=%(company)s""",
		{"company": company},
	)[0][0]

	# Que alguien haya ABIERTO la herramienta de importación no es que la haya
	# ejecutado. Distinguirlo evita acusar a nadie de no haber hecho su trabajo.
	intentos = frappe.get_all(
		"Data Import",
		filters={"reference_doctype": ["in", ["Journal Entry", "Account"]]},
		fields=["name", "reference_doctype", "status", "creation"],
		order_by="creation desc",
		limit=5,
		ignore_permissions=True,
	)

	concluyentes = patrimonio + transitorias + len(amplio) + asientos_marcados + lineas_marcadas
	cargados = concluyentes > 0

	return {
		"company": company,
		"cargados": cargados,
		"veredicto": (
			"Hay rastro de una carga de saldos iniciales; revisá la evidencia para ver por "
			"qué vía." if cargados else
			"NO hay rastro de una carga de saldos iniciales. Las cuatro vías dan cero."
		),
		"evidencia": vias,
		"primer_movimiento": str(primer) if primer else None,
		"intentos_de_importacion": intentos,
		"nota": (
			"NO uses «las cuentas tienen saldo» como prueba de que la apertura se cargó: "
			"eso solo dice que la empresa operó. La apertura se prueba con las vías de "
			"`evidencia`, no con el balance.\n"
			"Si `cargados` es false y alguien planea depurar un período apoyándose en que "
			"los saldos iniciales lo respaldan, decíselo: ese respaldo no existe, y "
			"borrar primero dejaría un vacío en vez de una foto."
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
		"name": "check_bank_reconciliation",
		"handler": check_bank_reconciliation,
		"writes": False,
		"description": (
			"Cuánto del extracto de una cuenta bancaria está conciliado contra la "
			"contabilidad, y cuánto no.\n"
			"Usala SIEMPRE que el banco y el sistema no coincidan: «el banco cerró en X "
			"pero acá dice Y», «esta cuenta está descuadrada», «¿por qué sobra plata en el "
			"banco?».\n"
			"Una diferencia entre banco y contabilidad es conciliación pendiente, NO falta "
			"de saldos iniciales ni un error de decimales. Y si la cuenta tiene movimiento "
			"sin conciliar, su saldo contable NO es comparable con el del banco: avisalo "
			"antes de dar el número."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"bank_account": {"type": "string", "description": "Cuenta bancaria. Omitila para ver todas."},
				"to_date": {"type": "string", "description": "Fecha de corte (YYYY-MM-DD). Por defecto hoy."},
				"company": {"type": "string", "description": "Empresa. Por defecto, la del usuario."},
			},
		},
	},
	{
		"name": "account_balance_by_party",
		"handler": account_balance_by_party,
		"writes": False,
		"description": (
			"Reparte el saldo de UNA cuenta de clientes o proveedores entre las partes que "
			"lo componen, a una fecha.\n"
			"Usala para «cuántos clientes deben», «quiénes componen las cuentas por "
			"cobrar», «el detalle de la cuenta por cliente».\n"
			"Devuelve CUÁNTAS partes tienen saldo distinto de cero, que no es lo mismo que "
			"cuántos clientes hay registrados.\n"
			"Para el saldo TOTAL de una cuenta sin desglosar alcanza con run_report; ésta "
			"es para el desglose."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"account": {"type": "string", "description": "Código o nombre de la cuenta contable."},
				"to_date": {"type": "string", "description": "Fecha de corte (YYYY-MM-DD). Por defecto hoy."},
				"limit": {"type": "integer", "description": "Cuántas partes listar."},
				"company": {"type": "string", "description": "Empresa. Por defecto, la del usuario."},
			},
			"required": ["account"],
		},
	},
	{
		"name": "check_period_impact",
		"handler": check_period_impact,
		"writes": False,
		# La cláusula «y también para cuántas facturas/pagos hubo entre tal y tal fecha»
		# tumbó el canario `natural-morosos-navegando` de 5/5 a 0/5 — bisecado, sola
		# rompe—. «Cuántos … hubo» es la forma de una pregunta de cohorte, y compite con
		# las herramientas de cohorte del ISP en preguntas que no hablan de períodos.
		# Se saca, y el disparador queda solo en la intención de TOCAR el período.
		"description": (
			"Qué hay en un período contable y qué se rompería si se toca: cuántos "
			"documentos, cuáles sostienen documentos POSTERIORES, qué se certificó ante el "
			"SENIAT y qué queda abierto.\n"
			"Es para cuando alguien plantea borrar, depurar, reversar o cerrar un período "
			"contable completo.\n"
			"Contestar «no se puede borrar» sin estas cifras es una opinión; con ellas es "
			"un dictamen."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"from_date": {"type": "string", "description": "Inicio del período (YYYY-MM-DD)."},
				"to_date": {"type": "string", "description": "Fin del período (YYYY-MM-DD)."},
				"company": {"type": "string", "description": "Empresa. Por defecto, la del usuario."},
			},
			"required": ["from_date", "to_date"],
		},
	},
	{
		"name": "check_opening_balances",
		"handler": check_opening_balances,
		"writes": False,
		# El «ANTES de opinar sobre depurar, borrar o reversar» que decía la primera
		# versión era demasiado ancho: la herramienta se disparó en 9 de 17 preguntas
		# de una batería contable, incluidas las que no dependen de la apertura.
		# Secuestró dos: una diferencia contra el banco pasó a contestarse con «no hay
		# saldos iniciales» más dos causas inventadas, y un pedido de balance de
		# comprobación se contestó con una advertencia y sin correr el reporte.
		#
		# Se corrige contrastando —diciendo para qué NO es—, que es lo medido que
		# funciona en este catálogo; acortar la descripción, no.
		"description": (
			"¿Se cargaron los SALDOS INICIALES de apertura, o solo se supone que sí?\n"
			"Usala SOLO cuando la respuesta dependa de que exista una apertura: alguien la "
			"da por cargada, o quiere borrar o depurar un período apoyándose en ella.\n"
			"NO la uses para dar un saldo, para explicar una diferencia contra el banco ni "
			"para entregar un balance o un mayor: eso sale de los reportes. Que falte la "
			"apertura NO explica que el banco y la contabilidad no coincidan — eso es "
			"conciliación, y es otra cosa.\n"
			"Que las cuentas tengan saldo NO prueba que haya apertura — eso solo prueba que "
			"la empresa operó."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"company": {"type": "string", "description": "Empresa. Por defecto, la del usuario."},
			},
		},
	},
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
