# Reglas para agentes — l10n_ve

Localización fiscal de Venezuela. Acá van las reglas que **no se deducen leyendo el código**:
invariantes que ya se rompieron en producción al menos una vez, con la evidencia de qué pasó.

Convenciones del repo: **identificadores y nombres de archivo/carpeta en inglés**;
comentarios y docstrings en español, igual que lo que lee el
usuario final, y sin `_()`;
`ignore_permissions=True` en save/insert/delete; los backfills se exponen como `dry_run()` /
`execute()` manuales y **no** van en `patches.txt`; rama feature + PR a `development`.

---

## En lo fiscal se falla; no se elige un valor por defecto

Cuando falta el dato que decide un número que va a un documento fiscal —alícuota, tasa,
serie, sustraendo, base— **se corta**. No se toma el primero disponible, no se rellena con
un neutro, no se sigue de largo.

**Por qué es una regla y no una preferencia.** Un `throw` en pantalla lo resuelve alguien en
minutos. Un valor asumido en silencio se declara ante el SENIAT y aparece en una
fiscalización, cuando ya no se puede deshacer. Los dos errores no cuestan lo mismo, así que
no se eligen por igual.

Y el error silencioso es además **invisible para las pruebas**: nada falla, ningún log se
enciende, el documento se emite. La única señal llega meses después y desde afuera.

Ya tomó tres formas distintas, las tres en 2026. Sirven como catálogo de qué buscar:

**Devolver el mismo valor para dos causas distintas.** `has_active_digital_series` retorna
`False` tanto si la factura no tiene sucursal —caso legítimo, no aplica emitir— como si la
tiene pero no resuelve ninguna serie activa —mala configuración—. El bypass de
`retention_integration.py` no los distinguía: marcaba la retención `Not Applicable` y
retornaba `True`, o sea **éxito**. La retención no se emitía nunca y el estado mentía; antes
quedaba en `Error`, visible y reintentable. Entró con el PR #415 el 2026-07-14 y se midió
contra producción el 2026-08-03: **cero comprobantes afectados**, el agujero estaba pero no
se activó. **Cerrado en el PR #591**, en tres puntos:

- `get_active_billing_series` con sucursal vacía **lanza** en vez de devolver `(None, "")`.
- El bypass de `process_retention_voucher` pregunta sólo por `TFHKA Settings.enabled`. Esa
  es la única causa de `Not Applicable`; lo demás cae en la validación de integridad, que
  deja estado `Error` + log.
- `build_payload` corta si la serie quedó vacía, por si un caller futuro se saltea lo anterior.

`test_retention_series_fail_closed` pinnea los tres. Si alguno se pone en rojo, no se ajusta
el test: se revisa qué lo puso en rojo.

**Tomar "el primero disponible" cuando no hay coincidencia.** Se propuso que, si el tabulador
de ISLR no tiene alícuota para el tipo de persona del proveedor, se usara la primera con
`aliquot > 0`. Eso no es un respaldo: es aplicar la alícuota de **otro tipo de persona**. En
el site hay **65 de 66 tabuladores con un solo tipo**, así que esa "primera" es casi siempre
la del tipo equivocado; el único con dos, el `077`, va de **1%** (natural domiciliado) a
**5%** (jurídico domiciliado). Revertido en el PR #546.

Corolario, porque es lo que hace segura la búsqueda amplia: **filtrar en el buscador no es
validar**. Si se relaja el filtro de la UI para que muestre más opciones, la validación al
aplicar pasa a ser la única defensa y hay que reforzarla, no quitarla.

**Rellenar con un neutro que no es neutro.** `flt(self.doc.conversion_rate) or 1.0` parece
inofensivo, pero el sustraendo del tabulador está en bolívares —su campo hermano se llama
`payments_greater_than_bs`— y con tasa `1` se resta como si fueran dólares: hasta **1.218 de
más** en la base declarada. Un `or 1` sobre una tasa de cambio nunca es un default: es
afirmar que dos monedas valen igual. Corregido en el PR #546.

**Dónde no aplica.** Esto es para el número que se declara, no para todo. Un default
razonable en un buscador, en un valor de presentación o en un reintento de red está bien.
La pregunta que separa los casos: *si esto se equivoca, ¿el error sale impreso en un
documento fiscal?* Si la respuesta es sí, se falla.

---

## Cálculo de impuestos: un solo lugar

**Todo cálculo de impuestos vive en [`l10n_ve/controllers/taxes_and_totals.py`](l10n_ve/controllers/taxes_and_totals.py).**
Ningún otro módulo —portal, payload de HKA, reporte, print format, dashboard— deriva base,
IVA o total por su cuenta.

| Primitiva | Para qué |
|---|---|
| `anchor_base_from_total(base_usd, vat_factor, rate, ...)` | ancla una base al total comercial. Es **la** primitiva del anclaje. |
| `compute_bs_tax_amounts(net_total_ref, iva_factor, rate, method)` | agregado del carril Bs: subtotal / IVA / total |

**Por qué es una regla y no una preferencia.** El site elige `tax_calculation_method`
("Desde la base imponible" / "Desde el total de la factura") en *Venezuela Account Settings*,
y ese switch cambia la derivación completa del carril Bs. Cualquier cálculo paralelo queda
desfasado apenas el site cambia de método, y nadie lo nota hasta que un cliente compara el
portal contra la factura.

Ya pasó dos veces con el mismo módulo: el portal derivaba `subtotal_bs = USD × tasa` a mano y
quedó **2,03 Bs** por debajo del documento fiscal; cuando se arreglaron los totales, las
**líneas** siguieron sin anclar y Σlíneas ≠ subtotal — que es una factura fiscalmente inválida.
Hoy el portal consume `compute_bs_tax_amounts` con import diferido desde
`domina_isp/www/invoice_customer/index.py`.

Reglas derivadas:

- Si necesitás un número que la primitiva no expone, **extendé la primitiva**. No calcules al lado.
- El IVA **nunca** se re-multiplica sobre una base ya redondeada: sale por **diferencia**, y la
  última fila VAT absorbe el remanente. Re-multiplicar fuga ±1 céntimo por factura.
- Nada de `1.16` / `0.16` hardcodeados: la alícuota sale de la fila de impuesto del documento.
- El carril USD es la fuente; el Bs se deriva. Nunca al revés.
- El método se fija **antes** de emitir. Cambiarlo con facturas o pagos en vuelo deja el portal
  divergiendo de documentos ya emitidos bajo el método anterior.

---

## HKA / The Factory HKA (facturación digital)

La arquitectura del módulo está en [`l10n_ve/digital_invoice/README.md`](l10n_ve/digital_invoice/README.md).
Ojo: HKA **no** vive solo en `digital_invoice/` — también lo tocan `overrides/sales_invoice.py`,
`tasks.py` (el cron), los doctypes de notas y comprobantes, el reporte *VE HKA Invoices Status*
y la vista previa en `public/js/`.

### Qué se envía y cuándo

Solo documentos **emitidos por la empresa**: `01` factura, `02` nota de crédito, `03` nota de
débito. Las facturas de **compra nunca** van a HKA.

El cron `send_pending_documents_to_hka` manda únicamente `status='Paid'`. Eso es **emitir-al-pagar,
por diseño** — no es un bug que haya que "arreglar". Lo que sí es un hueco real: las facturas que
quedan en *Partly Paid* por un residuo de céntimos nunca se certifican, porque el gate mira el
status y no el `outstanding`.

### `hka_status` NO es evidencia de certificación

Es un campo informativo y está **vacío en miles de facturas sí certificadas** (en prod: ~8.000 con
`bill_control` y `hka_status` vacío). La evidencia real de certificación es:

- `bill_control` (número de control fiscal), **o**
- un log `VE Digital Invoice Log` con resultado Success.

Para "pendientes de HKA" usá la definición canónica de `_get_pending_hka_invoices`. Una métrica
escrita como `hka_status != 'Emitida'` reportó **8.001 pendientes cuando el pendiente real eran 2**.

`hka_series` **jamás** se infiere del mapping sucursal→serie: la auditoría probó que diverge del
histórico. Solo se toma del propio documento (response/payload del log, o remarks).

### Nunca sostener locks de fila durante la llamada de red

La llamada a HKA tiene timeouts de 15-60 s. Si se entra a esa llamada con el lock de la factura
(`for_update`) o el del correlativo de la serie tomados, cualquiera que toque esa factura —o
**cualquier factura de esa serie**— espera y recibe un error.

Cómo se reconoce el síntoma: el front muestra *"El servidor estaba demasiado ocupado para procesar
esta solicitud"*. Eso es **MySQL 1205 (lock wait timeout)**, no falta de capacidad — en Frappe v15
esa excepción la levanta solo `ER.LOCK_WAIT_TIMEOUT`. Las métricas de InnoDB **no** lo delatan
(`lock_waits` es un gauge instantáneo y un evento de ~50 s se cuela entre muestras); la señal útil
es la **duración del job**.

⚠️ **Gotcha que hay que respetar si tocás esto:** `_ensure_bill_no` **no es idempotente** —consume
un correlativo fiscal nuevo en cada intento—, y hoy el `for_update` mal ubicado es lo **único** que
impide que el cron y el botón envíen el mismo documento a la vez. Soltar los locks a secas, sin
poner primero un mutex por documento, abre **doble emisión fiscal**. El fix correcto (mutex Redis
SETNX+TTL, más `commit()` antes del IO) está propuesto y **todavía no mergeado**.

### `TransaccionId` único en el tiempo

Usá `build_transaction_id(base, doc)` de `payload_builder.py`. **Nunca** derives el identificador
solo del `name` del documento: borrar el último documento de una serie **reinicia el correlativo**
(`revert_series_if_last` de Frappe, comportamiento by-design que no se puede apagar), el name se
recicla, y HKA —que deduplica por `TransaccionId`— responde `201` con el eco de los datos del
documento original.

### El código `201` significa "duplicado", no "éxito"

Hoy `_process_response` trata `200` y `201` como éxito y copia el `numeroControl` de la respuesta.
Con un `TransaccionId` reciclado eso llegó a **estampar el control fiscal de otro cliente** en una
nota de débito. Con `build_transaction_id` ya no debería reproducirse, pero:

- **No amplíes** la lista de códigos tratados como éxito.
- Si tocás esa rama, tratá el `201` como sospecha de duplicado, no como emisión buena.

### No borrar documentos fiscales

Además de reiniciar el correlativo (arriba), deja la serie desalineada respecto de lo que HKA ya
registró. Si hay que deshacer algo, se anula; no se borra.

### Siempre se busca la tasa usando el MES EN CURSO

Nunca la fecha del documento, ni el mes del período que factura. Lo que se declara ante el SENIAT
es la tasa del día en que el documento se **emite**.

La regla vive en **un solo lugar**, `get_ve_exchange_rate_for_customer`, y todo el ecosistema le
pregunta a ella: el motor de facturación, el retasado al aprobar, y las cuatro vistas del portal
de cliente en `domina_isp/www/`. Si aparece un `nowdate()` con un `get_first_day` al lado
resolviendo una tasa, es una copia de esta regla y hay que reemplazarla por la llamada.

| Cliente | Tasa |
|---|---|
| Jurídico | la de **hoy** |
| Natural | la del **1° del mes en curso** |

El parámetro `date` de esa función se conserva por compatibilidad de firma pero **no participa de
la regla**: pasarle el `posting_date` era justamente el camino por el que entraba la fecha
equivocada. Si necesitás la tasa de un documento, preguntale a esa función; no la derives.

**Caso que lo fijó (2026-08-03):** `ACC-SINV-2026-13754`, cliente natural. La factura era de julio
y se emitió el 1° de agosto con la tasa del 1° de julio, porque la regla del natural era «el 1° del
mes **de la factura**» y nada la retasaba al aprobarla. Salió con base imponible Bs 109.200,76
cuando correspondían Bs 128.726,43: **Bs 19.526 de base y Bs 3.124 de IVA por debajo**.

El retasado al aprobar (`rerate_juridical_before_submit`, enganchado en `before_validate`) aplica a
los **dos** tipos de cliente. Excluía al natural, y esa exclusión era el bug.

### El guard de tasa compara contra `tasa_fecha`, no contra `posting_date`

`_validate_tasa_coherencia` valida contra `tasa_fecha = _compute_tasa_fecha(doc)`, que para los dos
tipos de cliente resuelve la fecha REAL de la tasa que porta el documento (lookup inverso).
Comparar `conversion_rate` contra la tasa BCV del `posting_date` da **miles de falsos positivos**
(una consulta ingenua devolvió 9.193, casi todas certificadas correctamente).

`stale_rate_reason` sí mira el `posting_date`, pero **sólo en una dirección**: frena cuando la tasa
es más VIEJA que la fecha (la fecha se movió y la tasa se quedó → base por debajo). Una tasa más
NUEVA es el estado normal en tránsito entre la aprobación y la certificación, que es la que mueve
el `posting_date` a la fecha de emisión. Bloquear eso deja la factura trabada para siempre: le
falta exactamente lo que la certificación le daría (`ACC-SINV-2026-13707`).

Cuidado con la asimetría que ya causó facturas trabadas: quien **escribe** la tasa usa un lookup
permisivo (con fallback a la fila más cercana) y quien la **valida** exige la fila de la fecha
exacta. Si agregás un lookup nuevo, seguí el criterio estricto.
