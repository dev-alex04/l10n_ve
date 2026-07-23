# Facturación Digital — Integración TFHKA (The Factory HKA)

Módulo de integración con la API de **The Factory HKA** para la emisión, anulación y consulta de documentos fiscales electrónicos ante el SENIAT (Venezuela).

---

## Documentos Soportados

| Código | Documento | DocType Frappe | Estado |
|--------|-----------|----------------|--------|
| `01` | Factura de Venta | `Sales Invoice` | ✅ Producción |
| `02` | Nota de Crédito | `VE Sales Credit Note` | ✅ Producción |
| `03` | Nota de Débito | `VE Sales Debit Note` | ✅ Producción |
| `05` | Comprobante Retención IVA | — | ⏳ Pendiente |
| `06` | Comprobante Retención ISLR | — | ⏳ Pendiente |

> **Nota**: Las Facturas de Compra **no se envían a HKA**. Solo se transmiten documentos emitidos por la empresa. Los comprobantes de retención (IVA/ISLR) se encuentran planificados para la Fase 3.

---

## Arquitectura

```
digital_invoice/
├── __init__.py
├── tfhka_client.py          # Cliente HTTP — Auth JWT, emisión, anulación
├── payload_builder.py       # Constructor de payload JSON (tipos 01/02/03)
├── tfhka_integration.py     # Orquestador — validaciones, cron, reparación
├── test_payload_builder.py  # Tests unitarios del builder
└── README.md                # Este archivo
```

### Diagrama de componentes

```
┌─────────────────────────────────────────────────────────────────┐
│                     Capa de Presentación                        │
│  ┌──────────────────────┐  ┌──────────────────────────────┐     │
│  │  Botón JS             │  │  Modal Preview               │     │
│  │  send_invoice_manually│  │  get_invoice_preview_data    │     │
│  └──────────┬───────────┘  └──────────────┬───────────────┘     │
└─────────────┼──────────────────────────────┼────────────────────┘
              │                              │
              ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   tfhka_integration.py                           │
│  ┌────────────────┐  ┌──────────────────┐  ┌────────────────┐   │
│  │ process_invoice│  │ send_pending_*   │  │ Validaciones   │   │
│  │ (manual)       │  │ (cron cada 5min) │  │ pre-envío      │   │
│  └───────┬────────┘  └────────┬─────────┘  └────────────────┘   │
└──────────┼─────────────────────┼────────────────────────────────┘
           │                     │
     ┌─────▼─────┐        ┌─────▼─────┐
     │  payload   │        │  tfhka    │
     │  builder   │───────▶│  client   │──────▶ API TFHKA
     └───────────┘ JSON    └───────────┘ HTTP    (REST/JWT)
```

---

## Componentes

### `tfhka_client.py` — Cliente HTTP

Maneja toda la comunicación con la API REST de TFHKA.

| Método | Descripción |
|--------|-------------|
| `authenticate()` | Login JWT, almacena token en memoria |
| `emitir_documento(payload)` | Envío de documento fiscal |
| `void_fiscal_document(...)` | Anulación de documento |
| `download_file(...)` | Descarga de XML/PDF certificado |
| `get_document_status(...)` | Consulta de estado ante HKA |

**Configuración**: Las credenciales se almacenan en `site_config.json`:

```json
{
  "digital_billing_settings": {
    "url": "https://api.tfhka.com/v1",
    "user": "usuario",
    "password": "clave"
  }
}
```

El client implementa **retry automático** con backoff exponencial y re-autenticación transparente cuando el token JWT expira.

---

### `payload_builder.py` — Constructor de Payload

Transforma un documento Frappe (`Sales Invoice`, `VE Sales Credit Note`, `VE Sales Debit Note`) al formato JSON exigido por la API TFHKA.

**Clase principal**: `TFHKAPayloadBuilder`

| Sección del Payload | Datos clave |
|---------------------|-------------|
| `identificacionDocumento` | Tipo (01/02/03), número, fecha emisión |
| `vendedor` | RIF empresa, razón social, dirección fiscal |
| `comprador` | RIF cliente, razón social, dirección |
| `detallesItems` | Código PLU, cantidad, precio, IVA por ítem |
| `totales` | Gravado, exento, subtotal, IVA, IGTF, total |
| `totalesOtraMoneda` | Totales en USD (cuando `currency ≠ company_currency`) |
| `formasPago` | Formas de pago (99 = crédito, o por línea de pago) |
| `informacionAdicional` | Zona, nodo, serie, tasa BCV, período |

**Resolución de tipo de documento**:

```python
if doc.is_return:        → "02"  # Nota de Crédito
elif doc.is_debit_note:  → "03"  # Nota de Débito
else:                    → "01"  # Factura
```

**Dependencia externa**: `num2words` — Conversión de montos a texto en español.

---

### `tfhka_integration.py` — Orquestador

Contiene toda la lógica de negocio que conecta Frappe con HKA. Se divide en dos flujos principales:

#### Flujo Manual (botón)

1. Calcular fecha de tasa BCV (jurídico: exacta, natural: 1er día del mes)
2. Validar coherencia de tasa con Currency Exchange
3. Actualizar fechas fiscales (`posting_date` = hoy)
4. Resolver serie activa por sucursal + empresa
5. Asignar `bill_no` con incremento atómico SQL
6. Construir payload JSON
7. Validar integridad de factura (Σ items vs `base_net_total`)
8. Validar payload vs factura (VES + USD + IGTF, tolerancia ±0.02)
9. Validar zona/nodo (solo facturas, no NC/ND)
10. Enviar a HKA y procesar respuesta

#### Flujo Automático (cron)

| Aspecto | Detalle |
|---------|---------|
| Frecuencia | Cada 5 minutos (`*/5 * * * *`) |
| Horario activo | 05:00 – 21:00 |
| Batch size | 100 facturas por ciclo |
| Delay entre llamadas | 0.5 segundos |
| Filtro | `docstatus=1`, `status='Paid'`, `is_return=0`, sin `bill_control` |
| Circuit breaker | Se detiene si HKA reporta "rango de numeración agotado" |

**Modos de operación por serie**:

| Modo | Comportamiento ante error |
|------|--------------------------|
| **Internal** | STOP — Protege consecutividad del correlativo local |
| **Third Party** | CONTINUE — HKA controla la numeración |

**Funciones auxiliares**:

| Función | Propósito |
|---------|-----------|
| `_sanitize_customer_master_data()` | Limpia tabs/newlines en `customer_name` antes del envío |
| `_repair_partial_hka_invoices()` | Recupera `bill_no`/`bill_control` de logs tras timeout |
| `_sync_gl_entries_date()` | Sincroniza GL Entry, Payment Schedule y Payment Ledger Entry |

---

## DocTypes de Soporte

### `TFHKA Settings` (Single DocType)

Configuración global de la integración.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `enabled` | Check | Habilita/deshabilita la integración |
| `enable_auto_send` | Check | Activa el envío automático por cron |
| `environment` | Select | Demo / Production (indicativo) |
| `cutoff_date` | Date | Fecha mínima para procesar facturas |

### `VE Digital Billing Series`

Series de facturación digital con bloques de numeración asignados por TFHKA.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `company` | Link → Company | Empresa asociada |
| `status` | Select | Active / Exhausted |
| `operation_mode` | Select | Internal / Third Party |
| `serie` | Data | Serie TFHKA (ej: `ARA-02`) |
| `prefix` | Data | Prefijo del control (ej: `00`) |
| `range_from` / `range_to` | Int | Bloque de números de control |
| `invoice_number_correlative` | Int | Próximo número de factura |
| `credit_note_number_correlative` | Int | Próximo número de NC |
| `debit_note_number_correlative` | Int | Próximo número de ND |
| `branches` | Table | Sucursales asociadas |

### `VE Digital Invoice Log`

Registro de auditoría de todas las operaciones con HKA.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `document_type` | Select | Sales Invoice / VE Sales Credit Note / VE Sales Debit Note |
| `sales_invoice` | Dynamic Link | Referencia al documento |
| `endpoint` | Data | Emision / HKA Cron / Reparacion / GL Sync |
| `status` | Select | Success / Error |
| `payload_sent` | Code (JSON) | Payload enviado |
| `response_received` | Code (JSON) | Respuesta de HKA |

Los logs de error incluyen **deduplicación automática** (no se crea duplicado si ya existe uno reciente para la misma factura en las últimas 24h).

---

## Tests

Archivo: `test_payload_builder.py` — 10 tests unitarios.

| Test | Qué valida |
|------|------------|
| `test_factura_basica_estructura` | Keys del payload en camelCase |
| `test_factura_basica_totales` | 100 USD + 16% IVA = 116 |
| `test_factura_identificacion_documento` | `tipoDocumento=01`, `numeroDocumento` |
| `test_nota_credito_tipo_documento` | `tipoDocumento=02` para NC |
| `test_nota_debito_tipo_documento` | `tipoDocumento=03` para ND |
| `test_factura_exenta` | Exento → `montoExentoTotal`, IVA=0 |
| `test_factura_multimoneda_totales_otra_moneda` | Sección `TotalesOtraMoneda` presente |
| `test_formas_pago_credito` | Sin payments → forma `99` |
| `test_formas_pago_con_pagos` | Con payments → formas individuales |
| `test_parse_tax_id_*` (4) | Parsing de RIF en distintos formatos |

Ejecutar:

```bash
bench run-tests --app l10n_ve --module l10n_ve.digital_invoice.test_payload_builder
```

---

## Hooks Registrados

```python
# hooks.py
scheduler_events = {
    "cron": {
        "*/5 * * * *": ["l10n_ve.digital_invoice.tfhka_integration.send_pending_invoices_to_hka"],
    },
    "daily": [
        "l10n_ve.tasks.cleanup_resolved_digital_invoice_error_logs",
    ],
    "monthly": [
        "l10n_ve.tasks.purge_old_digital_invoice_success_logs",
    ],
}
```

---

## Pendientes (Fase 3)

- [ ] Builder para Comprobantes de Retención IVA (tipo `05`)
- [ ] Builder para Comprobantes de Retención ISLR (tipo `06`)
- [ ] Ampliar `VE Digital Invoice Log` para soportar tipos de retención
- [ ] Envío automático de NC/ND por cron
- [ ] Validación de consecutividad de numeración (requisito SENIAT)
- [ ] Mapeo de UOM → códigos UNECE Recommendation 20
