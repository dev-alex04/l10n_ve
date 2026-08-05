---
title: Glosario fiscal de Venezuela
type: glossary
summary: Qué significa «certificada», «control fiscal», «serie» y por qué hka_status no sirve
---

Vocabulario de la facturación digital ante el SENIAT. Varios términos se parecen
a lo que significan en otro lado y **no son lo mismo**.

**HKA / The Factory HKA** — el proveedor autorizado que certifica los documentos
fiscales ante el SENIAT. Cuando alguien dice «se envió a HKA» quiere decir que el
documento quedó registrado fiscalmente.

**Certificada / emitida ante el SENIAT** — el documento fiscal existe. La
evidencia es **`bill_control`** (el número de control fiscal) **o** un
`VE Digital Invoice Log` con `Success`.

> ⚠️ **`hka_status` NO es evidencia de certificación.** Está vacío en miles de
> facturas sí certificadas. Una métrica escrita como `hka_status != 'Emitida'`
> reportó **8.001 pendientes cuando el pendiente real eran 2**. No lo uses para
> contar nada: usá `check_hka`, que aplica la definición del cron.

**Número de control fiscal (`bill_control`)** — lo asigna HKA al certificar. Su
presencia es prueba de que el documento llegó al SENIAT.

**Serie de facturación (`VE Digital Billing Series`)** — agrupa sucursales bajo
un correlativo fiscal. Solo se envían documentos de sucursales que pertenecen a
una serie **activa**. Una sucursal fuera de toda serie activa **no factura
digitalmente**, y eso puede ser intencional.

**Modo de operación** — `Internal` (el correlativo lo lleva el sistema; un error
frena la serie completa para no saltear números) o `Third Party` (lo lleva HKA).

**Fecha de corte (`cutoff_date`)** — desde cuándo se envía a HKA. Todo lo
anterior queda sin certificar **a propósito**: no es un error ni algo que haya
que arreglar.

**Emitir-al-pagar** — solo se manda a HKA lo que está `Paid`. Es diseño, no un
bug. Consecuencia conocida: una factura que queda en *Partly Paid* por un residuo
de céntimos **nunca se certifica**, porque el filtro mira el estado y no el
pendiente.

**Tasa desincronizada** — la tasa del documento no corresponde a su fecha de
emisión. El chequeo es *fail-closed*: si no cuadra, la factura no sale. Se hace
**antes** de enviar porque una factura mal emitida no se deshace.

**`tasa_fecha`** — la fecha contra la que se valida la tasa. Para clientes
**naturales** es el 1° del mes; para **jurídicos** se resuelve por lookup
inverso. **No es la `posting_date`**: compararla contra la tasa del `posting_date`
da miles de falsos positivos (una consulta ingenua devolvió 9.193).

**Anular y reemitir** — la única forma de deshacer una factura certificada: nota
de crédito y emisión nueva. **Es irreversible y no se decide desde un chat.**

**Código 201 de HKA** — significa **duplicado**, no éxito. Llegó a estampar el
número de control de otro cliente en una nota de débito.

## Qué NO hace el asistente con esto

- **No propone anular ni reemitir** una factura certificada. Describe el caso y
  quién debe revisarlo.
- **No cuenta pendientes con `hka_status`.** Usa `check_hka`.
- **No suma montos de distinta moneda.** Acá se opera en USD y bolívares a la
  vez; cada cifra va con su moneda dicha.
- **No reporta el total sin el desglose.** La mayoría de los «pendientes» lo
  están por la fecha de corte, que es lo esperado.
