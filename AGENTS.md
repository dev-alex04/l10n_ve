# Reglas para agentes — l10n_ve

Localización fiscal de Venezuela. Acá van las reglas que **no se deducen leyendo el código**:
invariantes que ya se rompieron en producción al menos una vez, con la evidencia de qué pasó.

Convenciones del repo: identificadores en inglés; texto de UI en español y sin `_()`;
`ignore_permissions=True` en save/insert/delete; los backfills se exponen como `dry_run()` /
`execute()` manuales y **no** van en `patches.txt`; rama feature + PR a `development`.

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

### El guard de tasa compara contra `tasa_fecha`, no contra `posting_date`

`_validate_tasa_coherencia` valida contra `tasa_fecha = _compute_tasa_fecha(doc)`: para clientes
**naturales** es el 1° del mes; para **jurídicos** se resuelve por lookup inverso desde la tasa.
Comparar `conversion_rate` contra la tasa BCV del `posting_date` da **miles de falsos positivos**
(una consulta ingenua devolvió 9.193, casi todas certificadas correctamente).

Cuidado con la asimetría que ya causó facturas trabadas: quien **escribe** la tasa usa un lookup
permisivo (con fallback a la fila más cercana) y quien la **valida** exige la fila de la fecha
exacta. Si agregás un lookup nuevo, seguí el criterio estricto.
