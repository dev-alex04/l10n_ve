---
title: Cómo funciona la facturación digital (HKA / SENIAT)
type: doc
summary: El circuito de certificación, por qué una factura no sale, y las trampas con su número medido
---

# Facturación digital ante el SENIAT

> **Procedencia.** Casi todo acá viene del `AGENTS.md` de `l10n_ve`, escrito por
> el equipo que opera el sistema, con los montos y conteos que se midieron en
> producción cuando cada regla se rompió. Lo que se dedujo leyendo el código va
> marcado como tal.

## Qué se envía

Solo documentos **emitidos por la empresa**: `01` factura, `02` nota de crédito,
`03` nota de débito. Las facturas de **compra nunca** van a HKA.

## El circuito

El cron corre cada pocos minutos y, por cada **serie activa**:

1. Toma las sucursales de esa serie.
2. Busca facturas `Paid`, `docstatus = 1`, no devolución, no nota de débito,
   **sin certificar**, con `posting_date >= cutoff_date`.
3. Descarta las que tienen la **tasa desincronizada** — y anota el motivo en
   `VE Digital Invoice Log`, para que salgan como *Error* con explicación en vez
   de quedarse en *Pendiente* sin decir por qué.
4. Envía el resto.

En modo `Internal` un error **frena la serie completa**, para no dejar huecos en
el correlativo local. En `Third Party` continúa, porque la numeración la lleva
HKA.

## Por qué una factura cobrada no está certificada

En el orden en que el cron descarta. **El orden importa**: una factura con la
sucursal fuera de serie nunca llega a evaluarse la tasa, así que reportar la tasa
sería mandar a arreglar lo que no bloquea.

| Motivo | ¿Es un problema? | Qué se hace |
|---|---|---|
| **Sucursal fuera de toda serie activa** | Puede ser intencional | Revisar si esa sucursal debe facturar digitalmente |
| **Anterior a la fecha de corte** | **No.** Es el diseño | Nada |
| **Rechazada en el último intento** | Sí | El log dice el error; se corrige y reintenta |
| **Tasa desincronizada** | Sí | Corregir la tasa del documento antes de que salga |
| **En cola** | No | El cron la va a alcanzar |

Medido sobre una copia del site el 2026-08-02:

```
2.354 cobradas sin certificar
  2.346  USD 70.603,73   anteriores a la fecha de corte  ← esperado
      8  USD    185,66   tasa desincronizada             ← lo real
```

**Reportar 2.354 alarma por nada.** El número que importa son los 8.

## El caso inverso: certificada y sin cobrar

El documento fiscal ya está ante el SENIAT y el dinero no entró. Es el más
delicado de los dos, porque **ya no se puede deshacer**: hay que anular con nota
de crédito y reemitir.

No debería ocurrir —el filtro exige `Paid`— así que cuando aparece, algo pasó
después: el pago se canceló, se desconcilió, o la factura se emitió por otra vía.
**Antes de proponer nada hay que entender por qué se emitió.**

## Trampas, con su número

**`hka_status` no es evidencia de certificación.** Está vacío en ~8.000 facturas
que sí tienen `bill_control`. Una métrica escrita como `hka_status != 'Emitida'`
reportó **8.001 pendientes cuando eran 2**.

**El `201` significa duplicado, no éxito.** Llegó a estampar el número de control
fiscal de otro cliente en una nota de débito.

**Borrar un documento fiscal reinicia el correlativo.** Frappe recicla el `name`,
y HKA —que deduplica por `TransaccionId`— responde con el eco de los datos del
documento original. Si hay que deshacer algo, se anula; no se borra.

**El guard de tasa compara contra `tasa_fecha`, no contra `posting_date`.**
Compararlo contra la tasa BCV del `posting_date` dio **9.193 falsos positivos**,
casi todos certificados correctamente.

**Nunca sostener locks durante la llamada de red.** HKA tarda entre 15 y 60
segundos. Entrar a esa llamada con el lock de la factura o del correlativo
tomado hace que cualquiera que toque esa factura —o cualquiera de esa serie—
espere y reciba un error. El síntoma en pantalla es *«El servidor estaba
demasiado ocupado»*, que en realidad es **MySQL 1205 (lock wait timeout)**, no
falta de capacidad.

**`_ensure_bill_no` no es idempotente:** consume un correlativo fiscal nuevo en
cada intento.

## Hueco conocido, sin arreglar

Las facturas que quedan en *Partly Paid* por un residuo de céntimos **nunca se
certifican**, porque el filtro mira `status` y no `outstanding_amount`. No es un
caso hipotético: es la consecuencia directa de emitir-al-pagar combinado con
redondeos.

## Cómo consultarlo

`check_hka` aplica la definición del cron y devuelve las dos cohortes con el
motivo de cada caso. **No armes una query propia**: el campo `hka_status` se
llama igual que la pregunta y es la trampa documentada arriba.
