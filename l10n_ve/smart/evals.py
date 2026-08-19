"""Casos de eval de esta app. Los descubre el arnés de domina_smart.

`check_hka` llegó a producción **sin un solo caso**, y no por descuido: mientras
los evals vivieron en domina_smart, escribir uno exigía abrir un PR en otro
repositorio. Esa fricción es exactamente el motivo por el que los casos viven al
lado de las herramientas que miden.

Contrato con el arnés: dicts planos, sin importar nada de domina_smart — igual
que `TOOLS` en `smart/tools.py`.
"""

#: Herramientas de domina_isp. No se importan: se nombran, y el arnés omite el
#: caso si esa app no está instalada. l10n_ve funciona sin el ISP.
ISP = ["find_customer", "get_account_status", "check_health", "list_services"]



def get_cases(fx):
	"""Los casos fiscales. No usan fixtures: preguntan por cohortes, no por un documento.

	Las tres tensiones que miden:

	1. Lo fiscal es su propia herramienta. «No se envió a HKA» no es un problema de
	   cobranza aunque la palabra «factura» aparezca en las dos.
	2. Certificada sin cobrar y cobrada sin certificar son anomalías de signo
	   opuesto, y las dos salen de la misma llamada. Pedir una no justifica dos.
	3. Ante una factura ya certificada, el asistente NO debe proponer anularla.
	   Ante el SENIAT eso no se deshace: se anula con nota de crédito y se reemite.
	"""
	return [
		{
			"id": "comprobantes-que-faltan",
			"question": "¿qué comprobantes de retención me faltan?",
			"expect": ["check_customer_retentions"],
			"forbid": ["check_hka"],
			"note": "Los que FALTAN son los que el cliente no entregó. check_hka mira otra "
			"cosa: si la factura llegó al SENIAT.",
		},
		{
			"id": "reporte-por-nombre-inventado",
			"question": "corré el libro de compras del mes pasado",
			"expect": ["list_reports"],
			"first": "list_reports",
			"note": "El nombre real es `purchase_book`, no «Purchase Book». Tiene que pedir "
			"la lista antes de correr nada: inventar el nombre falla como si el dato no "
			"existiera.",
		},
		{
			"id": "cuanto-vendi",
			"question": "¿cuánto vendimos el mes pasado según el libro de ventas?",
			"expect": ["run_report"],
			"note": "Pregunta de total, no de tabla. La herramienta devuelve totales sobre "
			"todas las filas más el link al reporte.",
		},
		{
			"id": "saldo-de-una-cuenta",
			"question": "¿cuál es el saldo de la cuenta Anticipo de Clientes al 30 de junio de 2026?",
			"expect": ["run_report"],
			"note": "Medido en el caso del saneo de Galanet: el modelo respondió «no encontré "
			"ninguna cuenta con ese nombre» porque era la fila 15 de 31 y la muestra son 10. "
			"El dato estaba. Para eso existe `contains`.",
		},
		{
			"id": "saldos-iniciales-premisa-falsa",
			"question": "entiendo que ya cargaron los saldos iniciales, ¿me lo confirmás?",
			"expect": ["check_opening_balances"],
			"note": "Premisa falsa, y la más cara del lote. Medido antes de que existiera la "
			"herramienta: el modelo miró que las cuentas tenían saldo y CONFIRMÓ que la "
			"apertura estaba cargada. No lo estaba. Quien iba a depurar el semestre creía "
			"tener un respaldo que no existía.",
		},
		{
			"id": "borrar-periodo-mirar-antes",
			"question": "quiero borrar todos los movimientos contables anteriores a julio, "
			"que ya tengo mis saldos iniciales cargados",
			"expect": ["check_opening_balances"],
			"note": "Antes de opinar sobre borrar un período hay que verificar el respaldo "
			"que se da por sentado. Contestar de memoria —aunque la conclusión sea la "
			"correcta— deja al usuario sin la única cifra que decide.",
		},
		{
			"id": "apertura-no-explica-el-banco",
			"question": "el banco cerró en 290 mil bolívares pero acá la cuenta tiene 29 "
			"millones, ¿qué está pasando?",
			"forbid": ["check_opening_balances"],
			"note": "Este caso falló 4 de 4 mientras solo tenía el `forbid`, y esa terquedad "
			"fue el diagnóstico: NINGUNA herramienta contestaba «¿por qué el banco no "
			"cuadra?», así que el modelo agarraba la única de diagnóstico contable que "
			"tenía y contestaba con «no hay saldos iniciales» más dos causas inventadas. "
			"Prohibir sin ofrecer alternativa no alcanza — prefiere desobedecer a no "
			"contestar. La causa real eran 3.369 movimientos sin conciliar.",
		},
		{
			"id": "borrar-periodo-con-cifras",
			"question": "lo que está en el sistema de enero a junio de 2026 es basura, "
			"¿lo podemos eliminar y arrancar limpio desde julio?",
			"expect": ["check_period_impact"],
			"note": "Se midió dos veces que el modelo contesta «no se puede» —conclusión "
			"correcta— con CERO herramientas y cero cifras: un razonamiento genérico de "
			"ERPNext. La conclusión correcta sin evidencia no le sirve a quien tiene que "
			"defenderla frente a su cliente.",
		},
		{
			"id": "cuantas-facturas-en-el-periodo",
			"question": "¿cuántas facturas de venta se emitieron entre enero y junio de 2026?",
			"forbid": ["check_opening_balances"],
			"note": "Se puede contestar por dos vías legítimas —`Sales Register`, que "
			"reconcilia con el mayor, o check_period_impact— así que no se fija cuál. Lo "
			"que sí se fija es que un conteo de documentos no se conteste con la apertura.",
		},
		{
			"id": "balance-igual-hay-que-correrlo",
			"question": "necesito el balance de comprobación al 30 de junio de 2026 para "
			"decidir cuáles cuentas hay que reversar",
			"expect": ["run_report"],
			"note": "Pide un DOCUMENTO. Advertir que no hay apertura está bien de yapa, "
			"pero no reemplaza correr el reporte: se midió que dejó de correrlo y entregó "
			"solo la advertencia. Una advertencia correcta no es la respuesta a otra "
			"pregunta.",
		},
		{
			"id": "retenciones-como-van",
			"question": "como van las retenciones este mes?",
			"expect": ["check_retentions"],
			"first": "check_retentions",
			"max_calls": 1,
			"note": "La pregunta abierta del área de administración, sin nombrar ISLR ni IVA.",
		},
		{
			"id": "retenciones-sin-control",
			"question": "hay comprobantes de retencion que no hayan llegado al SENIAT?",
			"expect": ["check_retentions"],
			"forbid": ["check_hka"],
			"first": "check_retentions",
			"note": "TRAMPA DE VECINDAD, y es la que más importa de este par: check_hka y "
			"check_retentions son las dos «diagnóstico ante el SENIAT». La palabra que "
			"desempata es «retención» — check_hka mira facturas de VENTA y no ve un solo "
			"comprobante de retención, así que contestar con ella daría un cero que parece "
			"un dato.",
		},
		{
			"id": "retenciones-no-confundir-con-facturas",
			"question": "que facturas de venta no se certificaron ante el SENIAT?",
			"expect": ["check_hka"],
			"forbid": ["check_retentions"],
			"first": "check_hka",
			"note": "La trampa al revés. «SENIAT» ya no alcanza para elegir desde que hay dos "
			"herramientas fiscales: acá lo que manda es «facturas de venta».",
		},
		{
			"id": "hka-cobradas-sin-certificar",
			"question": "que facturas cobradas no se enviaron a HKA y por que?",
			"expect": ["check_hka"],
			"forbid": ISP,
			"first": "check_hka",
			"max_calls": 1,
			"note": "El «por qué» es la mitad que importa: la herramienta ya trae el motivo de "
			"cada una. No debe salir a buscar clientes.",
		},
		{
			"id": "hka-certificadas-sin-cobrar",
			"question": "hay facturas emitidas ante el SENIAT que no se hayan cobrado?",
			"expect": ["check_hka"],
			"forbid": ISP,
			"first": "check_hka",
			"max_calls": 1,
			"note": "La cohorte inversa. Sale de la misma llamada que la anterior.",
		},
		{
			"id": "hka-como-va",
			"question": "como va la facturacion electronica?",
			"expect": ["check_hka"],
			"forbid": ISP,
			"first": "check_hka",
			"max_calls": 1,
			"note": "Pregunta abierta, sin la palabra HKA ni SENIAT. Es como la haría alguien "
			"de administración.",
		},
		{
			"id": "hka-no-confundir-con-cobranza",
			"question": "cuanto me deben los clientes en total?",
			"forbid": ["check_hka"],
			"note": "Trampa de vecindad. check_hka tiene una cohorte «certificadas sin cobrar», "
			"y es un subconjunto: 438 documentos contra 5.368 deudores. Contestar la "
			"cartera con el número fiscal da una cifra 12 veces menor con cara de "
			"correcta.\n"
			"La primera versión de este caso preguntaba «¿tengo facturas sin cobrar?» y "
			"era injusta: esa frase describe literalmente la cohorte fiscal, así que el "
			"modelo elegía bien y el caso lo contaba mal. Ante una pregunta ambigua la "
			"respuesta correcta es preguntar, no acertar la moneda; lo que sí se puede "
			"medir es que una pregunta INEQUÍVOCA de cartera no se conteste con la "
			"herramienta fiscal.",
		},
		{
			"id": "hka-mirar-antes-de-opinar",
			"question": "hay alguna factura certificada que este mal?",
			"expect": ["check_hka"],
			"first": "check_hka",
			"max_calls": 1,
			"note": "Antes de opinar, mirar. Suena obvio y no lo es: la versión previa de este "
			"caso agregaba «deberíamos anularla», y con esa segunda cláusula el modelo "
			"contestaba 1 de cada 5 veces con la política correcta —no se anula, se emite "
			"nota de crédito— PERO sin consultar el dato. Buen consejo sobre un problema "
			"que no verificó que existiera.\n"
			"Que no proponga anular es una regla de REDACCIÓN y vive en knowledge/hka.md; "
			"acá no se puede medir, porque este arnés puntúa herramientas elegidas y no "
			"prosa. Mezclarlas hacía un caso que fallaba el 20% de las veces sin decir "
			"cuál de las dos mitades había fallado.",
		},
	]
