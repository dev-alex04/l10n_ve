# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.66.2] - 2026-09-11

### 🐛 Correcciones (Fixes)
- Se corrigió un error en el reporte de **Retención de Clientes**, el cual mostraba incorrectamente la misma información que el Libro de Ventas. [29fa0d46]
- Se optimizó la seguridad en la consulta de Retención de Clientes al eliminar la interpolación directa de variables del request, fortaleciendo la integridad de la base de datos. [f59f65c6]

---

## [v2.66.1] - 2026-09-11

### 🐛 Correcciones (Fixes)
- Corregido el error en la integración con HKA que causaba que el Periodo y la Nota del PDF mostraran el mes de servicio en lugar del mes de emisión. [20d13812]

---

## [v2.66.0] - 2026-09-10

### ✨ Funcionalidades (Features)
- Se integró la funcionalidad para generar Diferencial Cambiario (incluyendo escenarios de pérdida) en pagos a proveedores, añadiendo accesos rápidos tanto en la barra superior como en el menú de acciones. 326cdf11, 6180df7c, 60f7bc95
- Mejora en la visibilidad de documentos relacionados mediante la incorporación de Journal Entry en el dashboard de Conexiones de Payment Entry. c486f282
- Optimización de la integridad de datos al poblar automáticamente los campos `reference_type` y `reference_name` en las filas de proveedores del Journal Entry. 7e64a59e
- Implementación de referencia directa registrando el identificador del pago en el campo `cheque_no` del Journal Entry para facilitar la conciliación. ff6cfd25
- Se agregó trazabilidad bidireccional entre documentos mediante el uso de comentarios automáticos y el campo `user_remark`. 4a2aaf32

### 🐛 Correcciones (Fixes)
- Corrección en la tipificación contable para asegurar que los asientos generados utilicen el tipo "Exchange Gain Or Loss". 243ff37a
- Solución de un error técnico en `frm.page.remove_custom_button` que interrumpía la ejecución del script de `refresh` en la interfaz de usuario. 898ebdd9

---

## [v2.65.0] - 2026-09-10

### ✨ Funcionalidades (Features)
- Se implementaron filtros de fecha "Desde" y "Hasta" en el reporte de Cuentas por Pagar para mejorar la segmentación y consulta de información financiera. [97a33637]

---

## [v2.64.1] - 2026-09-10

### 🐛 Correcciones (Fixes)
- Se corrigió la actualización de la bandera de comprobante dentro de la función `create_government_withholding_journal_entry` para asegurar la integridad de los asientos contables de retención. ff35c367
- Se implementó el refresco del indicador de comprobante de retención faltante durante el proceso de carga de recaudos. fe761bb0

---

## [v2.64.0] - 2026-09-08

### ✨ Funcionalidades (Features)
- Se habilitó la compatibilidad de modos de pago globales para usuarios pertenecientes a sucursales raíz.

### 🐛 Correcciones (Fixes)
- Implementación de una política de "fail closed" en la función de verificación de usuarios de sucursal raíz cuando no existen sucursales configuradas, reforzando la seguridad del flujo.
- Optimización del registro de errores (log_error) para sucursales raíz, limitando su ejecución a una única vez por petición para reducir redundancia en los logs.

---

## [v2.63.0] - 2026-09-08

### 🐛 Correcciones (Fixes)
- **Seguridad en CI/CD:** Se corrigió una vulnerabilidad potencial de inyección de comandos en el sistema de notificaciones de Telegram y se implementó el principio de privilegios mínimos para los permisos del flujo de trabajo. d042c654

---

## [v2.63.0] - 2026-09-07

### ✨ Funcionalidades (Features)
- Se actualizaron los fixtures de transacciones bancarias para mostrar las etiquetas descriptivas «Crédito» y «Débito» en las operaciones de depósito y retiro. [119c16e5]

---

## [v2.62.3] - 2026-09-07

### 🐛 Correcciones (Fixes)
- Se ajustó la lógica de asignación en el módulo de cobros para que el centro de costo se determine a partir de la factura y no de la sucursal del cobro. [413c15a5]

---

## [v2.62.2] - 2026-09-07

### 🐛 Correcciones (Fixes)
- Se mejoró la lógica de obtención de tasas del BCV para cubrir feriados intermedios utilizando el último valor conocido. af6619bc
- Ajuste en la extracción de la fecha valor desde el componente correcto y soporte para la continuidad de datos durante fines de semana en el módulo BCV. cbb7bfbf

---

## [v2.62.1] - 2026-09-06

### 🐛 Correcciones (Fixes)
- **Permisos:** Se corrigió un error en la visualización de la lista donde se mostraban documentos sin sucursal asociada, validando correctamente el acceso a través del enlace. (#697) [31997d4e]

---

## [v2.62.0] - 2026-09-03

### ✨ Funcionalidades (Features)
- Se actualizó la lógica de ejecución del lote de notas (HKA), permitiendo que el proceso se realice también los días 14 de cada mes, adicionalmente a la ejecución de fin de mes. [d53cde4a]

---

## [v2.61.3] - 2026-09-02

### 🐛 Correcciones (Fixes)
- **hka**: Se corrigió un error donde la anulación directa solo se procesaba a nivel de interfaz; ahora el cierre se ejecuta correctamente en el servidor para garantizar la consistencia de la operación. [d09f071](https://github.com/repo/commit/d09f0713)

---

## [v2.61.2] - 2026-09-02

### 🐛 Correcciones (Fixes)
- **HKA:** Se corrigió un error en la lógica de mensajería que dirigía a los usuarios a botones que ya no se encontraban activos. a788ff19

---

## [v2.61.1] - 2026-09-01

### 🐛 Correcciones (Fixes)
- Se ocultó el botón de anular factura en la integración con HKA, atendiendo a la deshabilitación de esta función por parte del proveedor a partir del 1 de septiembre. [e9b735b3]

---

## [v2.61.0] - 2026-09-01

### ✨ Funcionalidades (Features)
- Implementación del envío automatizado de Notas de Crédito (NC) y Notas de Débito (ND) de venta el último día del mes. 580901c7

### 🐛 Correcciones (Fixes)
- Ajuste en la lógica de persistencia del período al encolar el worker para garantizar la consistencia de los datos frente al tiempo de ejecución. 381baabd
- Corrección en la validación del período de envío para asegurar la correcta sincronización con el día de ejecución. e4e865f6
- Optimización del procesamiento de lotes de notas para evitar solapamientos con la medianoche e inclusión del mes en el `job_id`. 89dd0fa9
- Refinamiento en el filtrado del lote mensual para procesar exclusivamente documentos pertenecientes al mes correspondiente. e51f48b2
- Reajuste en la programación del horario de ejecución del lote de notas a las 15:23. 0c563492

---

## [v2.60.2] - 2026-09-01

### 🐛 Correcciones (Fixes)
- Se corrigió un error en el proceso de configuración donde la función `create_sales_taxes_and_charges_template` no era idempotente, garantizando ahora que las ejecuciones repetidas no generen conflictos o registros duplicados. [cede52aa]

---

## [v2.60.1] - 2026-08-28

### 🐛 Correcciones (Fixes)
- Se ocultó el botón de conciliación directa en las entradas de pago (payment_entry) al realizar procesamientos por lote para asegurar la consistencia del flujo de trabajo (#674).

---

## [v2.60.0] - 2026-08-28

### ✨ Funcionalidades (Features)
- Implementación del nuevo campo de número de cuenta en la tabla de detalles de los Asientos de Diario (Journal Entry) bajo el ticket DLE-10. b1254ea5

### 🐛 Correcciones (Fixes)
- Prevención de condiciones de carrera (race conditions) en el manejador de cuentas de los asientos de diario para asegurar la integridad de los datos. e7a0e599
- Optimización de la sincronización del número de cuenta mediante el ajuste de la propiedad `fetch_if_empty`. 1738f433
- Simplificación de la lógica de asignación del número de cuenta, eliminando procesos redundantes de inferencia de nombres. 1d545396
- Mejora en la consistencia de la interfaz y delegación del proceso de obtención de datos (fetch) directamente al framework Frappe. 10a0e79c

---

## [v2.59.0] - 2026-08-28

### ✨ Funcionalidades (Features)
- Se implementó la lógica para ocultar el campo de selección "Utilizar para gastos" en las sucursales de Venezuela (VE Branch). 04e6ec8b

---

## [v2.58.0] - 2026-08-27

### ✨ Funcionalidades (Features)
- Se habilitó la capacidad de procesar pagos para Notas de Débito de compra. 427400c2

### 🐛 Correcciones (Fixes)
- Se ajustó la lógica de anulación de pagos para garantizar que el saldo de la Nota de Débito se reintegre correctamente al anular la transacción. 6a885fd9

---

## [v2.57.5] - 2026-08-26

### 🐛 Correcciones (Fixes)
- Se corrigió un error en el módulo de empresas donde el formato del número de control se devolvía de forma literal sin realizar las sustituciones de valores correspondientes. fca88528

---

## [v2.57.4] - 2026-08-24

### 🐛 Correcciones (Fixes)
- Se corrigió una vulnerabilidad crítica de seguridad en el proceso de generación de PDFs, donde el inlineado de CSS permitía el acceso no autorizado a archivos del sistema de archivos local. (#667)

---

## [v2.57.3] - 2026-08-24

### 🐛 Correcciones (Fixes)
- Se corrigió el cálculo en el libro de ventas para asegurar que la base por alícuota refleje correctamente la base real de la factura. (#666)

---

## [v2.57.2] - 2026-08-24

### ✨ Funcionalidades (Features)
- Implementación de lógica para interceptar correos electrónicos antes del envío del payload al proveedor HKA. (#626)

---

## [v2.57.1] - 2026-08-24

### ✨ Funcionalidades (Features)
- Se realizó una refactorización en la localización de Venezuela (l10n_ve) para remover el módulo de reporte pro. [c0a28e19]

### 🐛 Correcciones (Fixes)
- Ajuste en la configuración del Workspace para establecer la Conciliación de Cajas como una URL funcional y corregir la sincronización del contador de enlaces (link_count). [f5e00db5]

---

## [v2.57.0] - 2026-08-24

### ✨ Funcionalidades (Features)
- Implementación de permisos exclusivos para el Reporte Gerencial, restringiendo su acceso únicamente al rol de **Executive Reporting Manager**. (6ae33dc5)

### 🐛 Correcciones (Fixes)
- Corrección en la lógica de restricciones del Reporte Gerencial para asegurar que el reporte siempre mantenga un propietario asignado. (6bc13525)

---

## [v2.56.1] - 2026-08-24

### 🐛 Correcciones (Fixes)
- Se corrigió un error en el módulo de clientes que provocaba que el estado no guardado persistiera incorrectamente tras refrescar el formulario. [976734f2]

---

## [v2.56.0] - 2026-08-24

### ✨ Funcionalidades (Features)
- Se agregó el parámetro `ignore_permissions` en el filtro de comprobantes para el reporte de cuentas por cobrar. [521b91dd]

---

## [v2.55.0] - 2026-08-23

### ✨ Funcionalidades (Features)
- Se implementó el filtro «Sucursal Principal» y la funcionalidad de consolidación (rollup) de subárboles en el Libro de Ventas. [6473f545]

### 🐛 Correcciones (Fixes)
- Corregida la lógica en el Libro de Ventas donde el HQ perdía la referencia de hoja (leaf) en la jerarquía, extendiendo el comportamiento más allá de la sucursal principal. [f3cf2ac7]

---

## [v2.54.1] - 2026-08-22

### 🐛 Correcciones (Fixes)
- Se corrigió un error en el alineador de tasas del BCV que modificaba la fecha de emisión en los documentos en estado borrador. b95a95c3

---

## [v2.54.0] - 2026-08-20

### ✨ Funcionalidades (Features)
- Se incorporó el nuevo filtro por municipio en el reporte de Facturas de Venta HQ. bd605836

### 🐛 Correcciones (Fixes)
- Optimización de rendimiento mediante la delegación del filtrado de sucursales directamente a la consulta SQL (pushdown). 3ae4f8a4
- Corrección en la visualización de municipios dentro de la estructura de árbol del reporte. 3ae4f8a4

---

## [v2.53.0] - 2026-08-20

### ✨ Funcionalidades (Features)
- Implementación de la propiedad `ignore_permissions` aplicada exclusivamente al filtro de tipo de comprobante (`voucher_type`) en el módulo de reportes. 1578b508
- Habilitación de `ignore_permissions` en los filtros de reportes y aplicación de formateo seguro mediante Jinja para el reporte de libro diario (`ve_journal_book`). fd495996

---

## [v2.52.0] - 2026-08-20

### ✨ Funcionalidades (Features)
- **Gestión de Nombres**: Se implementó el uso de **Naming Series** para las entidades de Clientes (Customer) y Proveedores (Supplier), permitiendo una estandarización más flexible de los identificadores.
- **Interfaz de Usuario**: Se agregaron títulos descriptivos en los campos de tipo **Link**, mejorando la legibilidad y la experiencia de búsqueda dentro de la plataforma. [0a5b0e77]

---

## [v2.51.1] - 2026-08-19

### 🐛 Correcciones (Fixes)
- Se integró una advertencia en el módulo **smart** referente a la sobreestimación de facturas «Emitidas» en el reporte HKA al consultar periodos históricos, mejorando la precisión en la interpretación de los datos reportados. [32f10e7c]

---

## [v2.51.0] - 2026-08-19

### ✨ Funcionalidades (Features)
- Implementación de nuevas capacidades en el módulo smart: se añadieron las funciones `check_bank_reconciliation` para la verificación de conciliaciones bancarias y `account_balance_by_party` para la consulta de saldos de cuenta por tercero. [8261be1]

---

## [v2.50.1] - 2026-08-19

### ✨ Funcionalidades (Features)
- Integración de los campos `bill_no` y `bill_control` en el Libro Mayor General (GL Entry) al procesar asientos contables (JE) para mejorar la trazabilidad y visualización de documentos. a0c0182
- Implementación de lógica para la gestión de retenciones de ISLR sobre facturas de compra una vez que estas han sido aprobadas. a31033b

### 🐛 Correcciones (Fixes)
- Ajuste en el módulo de compras para eliminar valores predeterminados arbitrarios en el cálculo de retenciones retroactivas, garantizando la integridad de los datos fiscales. 4f769f8

---

## [v2.50.0] - 2026-08-19

### ✨ Funcionalidades (Features)
- **Mejoras integrales al Libro Diario:** Se implementaron optimizaciones significativas que incluyen un nuevo selector de moneda, validación de cuadratura de asientos contables y ajustes para cumplir con el formato legal requerido. (87369bb)

### 🐛 Correcciones (Fixes)
- **Lógica de conversión de divisas:** Se corrigió el comportamiento del sistema para evitar que se asuma una tasa de cambio 1:1 automáticamente en el libro diario cuando no existe una tasa configurada. (5e8c8b9)
- **Formateo de datos en reportes:** Se aplicó un formateo seguro para fechas y montos en la plantilla HTML del reporte `ve_journal_book`, mejorando la integridad visual de los datos. (a779c60)

---

## [v2.49.0] - 2026-08-19

### ✨ Funcionalidades (Features)
- Implementación de la validación de impacto de periodo (`check_period_impact`) en el módulo smart.
- Adición de los reportes de Registro de Ventas (Sales Register) y Libro Mayor (General Ledger) al catálogo del sistema. d59d042

---

## [v2.48.1] - 2026-08-19

### 🐛 Correcciones (Fixes)
- **Localización Venezuela (l10n_ve):** Se corrigió la lógica de importación de `ClosedAccountingPeriod` y se optimizó el sistema de registros para evitar la saturación de los logs con entradas redundantes de una misma factura. (e45ccd0)

---

## [v2.48.0] - 2026-08-19

### ✨ Funcionalidades (Features)
- Implementación de descubrimiento automático de suites de prueba basado en archivos, eliminando la necesidad de realizar registros manuales. [c23193f](https://github.com/repo/commit/c23193f)

---

## [v2.48.0] - 2026-08-19

### ✨ Funcionalidades (Features)
* Implementación de la función `check_opening_balances` dentro del módulo smart para la validación de saldos iniciales.

### 🐛 Correcciones (Fixes)
* Resolución de errores en dos casos específicos de ejecución de sentencias `eval` que se encontraban rotos.

---

## [v2.47.0] - 2026-08-19

### ✨ Funcionalidades (Features)
- **Localización Venezuela (l10n_ve):** Se han expuesto 22 reportes legales y fiscales dentro del módulo. Se integró una nueva funcionalidad de validación que notifica al usuario sobre los comprobantes de retención faltantes. [fa56b7e]

---

## [v2.46.0] - 2026-08-18

### ✨ Funcionalidades (Features)
- Se integró la nueva validación **check_retentions** dentro del módulo smart para monitorear y verificar la salud de los comprobantes de retención. [63f1e0e]

---

## [v2.45.0] - 2026-08-17

### ✨ Funcionalidades (Features)
- Implementación de nuevas columnas de porcentaje en los reportes de retenciones de ISLR e IVA, incluyendo soporte completo para exportaciones en formatos Excel y PDF [75f4923].
- Optimización y simplificación de la lógica para el formateo de valores porcentuales en el módulo de reportes [d644627].

---

## [v2.44.0] - 2026-08-17

### ✨ Funcionalidades (Features)
- Implementación de restricción de acceso al **Reporte Gerencial**, limitando su uso exclusivo a usuarios con el rol **Executive Reporting Manager**. [ffcab25]

### 🐛 Correcciones (Fixes)
- Ajuste en la lógica de permisos para acotar las excepciones de rol específicamente al módulo de reportes, evitando que afecten globalmente a otras secciones de la aplicación. [66ee6ce]

---

## [v2.43.0] - 2026-08-17

### ✨ Funcionalidades (Features)
- Se implementó el parámetro `is_fiscal_device` para permitir omitir la validación de duplicidad en el campo `bill_no` cuando se utiliza el mismo proveedor. [162de80]

---

## [v2.41.1] - 2026-08-05

### 🐛 Correcciones (Fixes)
- Se corrigió un error en el módulo `check_hka` donde el monto pendiente se etiquetaba incorrectamente como USD en lugar de Bolívares. [fcb20ff]

---

## [v2.41.0] - 2026-08-05

### ✨ Funcionalidades (Features)
- Se implementó la capacidad de diagnóstico de HKA para el agente inteligente. [9a900c7]
- Se integró conocimiento especializado sobre las reglas de HKA para mejorar la comprensión y el contexto del asistente. [8b9090e]

---

## [v2.40.1] - 2026-08-04

### 🐛 Correcciones (Fixes)
- Se corrigió la lógica de generación del XML de ISLR para asegurar que el campo `FechaOperacion` utilice la fecha de emisión del comprobante en lugar de la fecha actual o de sistema. (c45b738)

---

## [v2.40.0] - 2026-08-04

### ✨ Funcionalidades (Features)
- Se implementó la búsqueda libre de ISLR en el módulo de compras para mayor flexibilidad en el registro de transacciones.

### 🐛 Correcciones (Fixes)
- Corrección en el cálculo de ISLR para transacciones en divisas (USD).
- Se ajustó la lógica de asignación de alícuotas según el tipo de persona y se corrigió la validación de la tasa de cambio necesaria para el cálculo. f692fd2

---

## [v2.39.5] - 2026-08-04

### ✨ Funcionalidades (Features)
- Rediseño de la interfaz en el módulo de retenciones, simplificando la selección a dos botones principales para la gestión de IVA e ISLR (e624080).

---

## [v2.39.4] - 2026-08-04

### ✨ Funcionalidades (Features)
- Se desactivó la validación obligatoria del campo de Retención de Impuestos en el módulo de proveedores. (5b8af92)

---

## [v2.39.3] - 2026-08-04

### 🐛 Correcciones (Fixes)
- Se corrigió la lógica de obtención de la fecha de la tasa en el módulo HKA, asegurando que la información se extraiga correctamente desde la regla y no desde el monto. [f73bdb8]

---

## [v2.39.2] - 2026-08-04

### 🐛 Correcciones (Fixes)
- Se corrigió la generación del XML de ISLR para evitar el truncado de los números de documento y se optimizó el reporte incluyendo la fila procesada. 03c8a24
- Implementación de saneamiento de datos en los campos NumeroFactura, NumeroControl y RifRetenido dentro del XML de ISLR para garantizar el cumplimiento de los esquemas técnicos del SENIAT. 4dd86ac

---

## [v2.39.1] - 2026-08-04

### ✨ Funcionalidades (Features)
- Se actualizó la lógica del módulo HKA para que el campo de fecha deje de ser obligatorio, documentando formalmente esta regla de negocio en AGENTS.md.

### 🐛 Correcciones (Fixes)
- Se ajustó el sistema para que la tasa se ancle a la fecha actual y se corrigió el comportamiento del retraso en personas naturales.
- Se solucionó un error de procesamiento en registros jurídicos que causaba fallos cuando la tasa era posterior a la fecha de referencia.

---

## [v2.39.0] - 2026-08-04

### ✨ Funcionalidades (Features)
- **Sandbox:** Ahora se realiza la degradación automática de TFHKA a modo Demo durante el proceso de saneamiento de copias, garantizando que los entornos de prueba no afecten servicios productivos. [9e03ae8]

---

## [v2.38.2] - 2026-08-03

### 🐛 Correcciones (Fixes)
- Optimización del proceso de exportación HQ: se implementó el encolamiento para la generación de archivos Excel en lugar de procesarlos en memoria, mejorando el rendimiento y la escalabilidad del sistema. [f9edeb1]

---

## [v2.38.1] - 2026-08-03

### 🐛 Correcciones (Fixes)
- Se ajustó la validación del aviso de comprobante faltante en el módulo de retenciones para que la evaluación se realice correctamente según el tipo de comprobante. [f600c44]

---

## [v2.38.0] - 2026-08-03

### ✨ Funcionalidades (Features)
- **Retenciones:** Se agregó la validación de quincena en la fecha del comprobante, con un tooltip que indica el período vigente. Impide fechar un comprobante dentro de una quincena ya cerrada. (#511) [c2071d6] [3f768a2] [596e529]

### 🐛 Correcciones (Fixes)
- **Workspaces:** La inyección de los accesos de l10n_ve en los workspaces de ERPNext pasó a ser declarativa: un manifiesto por workspace destino en `l10n_ve/workspace_injection/`, en lugar de ~700 líneas de código imperativo. Corrige cuatro defectos: se eliminaba un enlace propio de ERPNext (`Accounting Dimension`), se duplicaban las Notas de Crédito y Débito en Ventas en cada migración, las tarjetas se agrupaban de forma no determinista por colisiones de orden, y la tarjeta *Reportes Venezuela* no llegaba a mostrarse (sus reportes aparecían bajo una tarjeta ajena). (#524) [05d2ce7] [977afd9] [d6861aa]
- **Migración:** La tasa de cambio dejó de recalcularse en cada `bench migrate`. Ya se actualiza cada hora por agenda; el llamado en la migración hacía peticiones de red que ataban el proceso a un servicio externo y volvía a tasar facturas en borrador. (#524) [16c897e]
- **Retenciones:** Los documentos ahora dicen "Retención de IVA" y no "de VAT". El identificador interno se mostraba tal cual en la descripción de la factura y en el asiento contable, contradiciendo al comprobante del cliente, al Libro de Ventas y a la declaración. (#526) [c668974]
- **Traducciones:** Se eliminó la entrada duplicada de *Branch* en `es.csv`. (#522) [404b028]

---

## [v2.37.0] - 2026-08-02

### ✨ Funcionalidades (Features)
- Implementación de la lógica para el guardado del ecosistema y saneo fiscal de una copia dentro del entorno sandbox. [2fac5f3]

---

## [v2.36.2] - 2026-08-01

### ✨ Funcionalidades (Features)
- **Centralización de impuestos:** Se definieron las reglas de HKA y se centralizó la lógica del cálculo de impuestos dentro del módulo de agentes para mejorar la consistencia del sistema. [6182541]

---

## [v2.36.2] - 2026-08-01

### 🐛 Correcciones (Fixes)
- Se implementó una validación crítica en el módulo de HKA para evitar la certificación de facturas cuya tasa de cambio no coincida con su fecha de emisión original. 4b4b900

---

## [v2.36.1] - 2026-08-01

### 🐛 Correcciones (Fixes)
- Se actualizó el reporte HKA: se eliminó la columna de **Estado Factura** y se incorporó el **monto pendiente** para mejorar la precisión de la información financiera. [abfdf3a]

---

## [v2.36.0] - 2026-08-01

### ✨ Funcionalidades (Features)
- **UI:** Se implementó la agrupación de información fiscal del cliente y la funcionalidad para filtrar extractos bancarios. [a12989c]

---

## [v2.35.0] - 2026-08-01

### ✨ Funcionalidades (Features)
- El Tabulador ISLR se puede filtrar por código, sin recorrer el catálogo entero. [cc986ec]

### 🐛 Correcciones (Fixes)
- El modal del diferencial cambiario ya no parte la frase en tres líneas: el formateador de moneda envolvía el monto en un elemento de bloque que rompía el párrafo. [e1376d1]

---

## [v2.34.0] - 2026-07-31

### ✨ Funcionalidades (Features)
- **Retasado a tasa de emisión antes de aprobar la factura.** Para el cliente jurídico, la factura se lleva a la tasa BCV del día antes de quedar emitida. Antes se corregía después de aprobar, lo que obligaba a regenerar el mayor del documento: medido sobre producción, el 78% de las facturas caía en las condiciones que saltaban esa corrección y se emitía con una tasa que no correspondía. [4014b53] [f61e3a4]
- El botón de Factura Digital acepta borradores: los aprueba y los envía en un paso, y la vista previa muestra la tasa con la que realmente se va a emitir el documento. [9554ef5]
- Botón de diferencial cambiario en las facturas de compra, para liquidar el residuo de una factura parcialmente pagada. [007ccc0]
- Tarifas de timbre fiscal de 13 estados, verificadas contra gaceta. [db5764b]
- Los avisos de retención se envían también de inmediato al facturar, además del cron. [62589de]

### 🐛 Correcciones (Fixes)
- Los anticipos aplicados dejan de bloquear el retasado. Medido sobre facturas reales: no se duplica ningún asiento y el diferencial queda registrado una sola vez. [ae75c5b]
- Los avisos de retención corrigen la fecha tope (día 22), los destinatarios y una carrera al encolar. [857cab9]
- El diferencial cambiario en compras exige permisos y que la factura esté parcialmente pagada. [5f11e74]

### ⚡ Rendimiento (Performance)
- Los recordatorios de retención usan precarga por lotes y plantilla única. [b08501e]

---

## [v2.33.0] - 2026-07-30

### 🐛 Correcciones (Fixes)
- La categoría de retención del proveedor ahora es visible y opcional cuando no es contribuyente con RIF jurídico, en vez de ocultarse. [b675b43]

---

## [v2.32.0] - 2026-07-30

### ✨ Funcionalidades (Features)
- La vista previa de facturación digital muestra la tasa con la que realmente se va a emitir el documento, no la que porta la factura. [64d6476]
- El reporte HQ suma columnas consolidadas de Base e IVA, y el Excel incluye resumen fiscal con formato. [38f0983]
- El Mayor Analítico permite filtrar sólo movimientos aprobados, con opción de incluir cancelados. [0ce0040]

### 🐛 Correcciones (Fixes)
- Los bloqueos de fila se liberan antes del viaje de red a HKA, eliminando los errores de espera de bloqueo (1205) durante la emisión. [291af66]
- La cuenta de anticipo se elige por tipo de entidad y no por dirección del pago: los reembolsos a clientes ya no caían en la cuenta de proveedores. [8012a2e]
- La casilla de cancelados ya no altera el saldo del Mayor Analítico; los documentos anulados quedan marcados. [a87015f]
- El Excel del reporte HQ se genera en segundo plano, con totales consolidados y encabezado fijo. [0e09ab3]
- El PDF del Mayor Analítico recupera el rombo de marca. [704980f]

---

## [v2.31.0] - 2026-07-28

### ✨ Funcionalidades (Features)
- El reporte HQ incorpora el logo de la empresa en el PDF, filtros rápidos, indicador de carga, etiquetas legibles y descripción por columna. [1cc0e96] [5868cfd] [99193a4]
- El Estado pasa a ser filtro rápido en la lista de Recibos de Pago. [416327b]
- Los resúmenes de mayor de Cliente y Proveedor se renombran a Saldo a Favor. [d25e4b4]

### ⚡ Rendimiento (Performance)
- El reporte HQ pasa de 12,2 MB a 2,6 MB por corrida. [181bd1a]

---

## [v2.30.0] - 2026-07-27

### ✨ Funcionalidades (Features)
- El reporte HQ suma ejecución manual, exportación a Excel en memoria, filtro y columna de Sucursal Principal, y los colores de marca en su indicador. [566dedb] [332d555] [8369e60] [eaaf9e9]
- Los accesos de sucursal quedan restringidos a usuarios del sistema, evitando agregar usuarios externos. [cd8a62f3]
- El historial del sistema muestra fecha y hora exactas. [67dbc18]
- Los modos de pago incorporan el campo Enviar por Correo. [d1b75ab]

### 🐛 Correcciones (Fixes)
- Branch se traduce como «Sucursal» y no como «Rama». [915313a]
- El filtro de facturas sin número de control pasa a ser opcional y preserva la partida doble y los asientos de apertura. [03a96f2] [41e630c]
- El número de factura se formatea correctamente en los comprobantes de retención de HKA. [fe39f85]

---

## [v2.29.0] - 2026-07-27

### ✨ Funcionalidades (Features)
- El reporte HQ suma documento fiscal, municipio y consolidación padre-hijo, con su descripción sobre la tabla. [88bd14e] [73f9571]

### 🐛 Correcciones (Fixes)
- Las notas de crédito y débito heredan la tasa de cambio de la factura original, y el asiento de ajuste queda alineado con esa herencia. [d8f8b44] [f60000b]

---

## [v2.28.0] - 2026-07-26

### ✨ Funcionalidades (Features)
- La Factura de Compra muestra Total Base + IVA, agrupa la base imponible bajo Total Retenido y suma columnas en bolívares en el grid de impuestos. [5fd874d] [7e527c2]
- Se crea el rol VE Sales Book HQ desde la instalación, con su traducción y enlace en el espacio de trabajo de Administración. [b6d091d] [adba862] [6b1d2bc]

### 🐛 Correcciones (Fixes)
- La tasa BCV se precarga con su fecha valor futura, eliminando la carrera de medianoche. [6028a5c]
- Las facturas en borrador alinean su tasa cuando el BCV publica la del día. [73e44ab]
- La vista previa fiscal servía el comprobante de retención en lugar de la factura. [966c573]
- El reporte de estado HKA corrige etiquetas, traducción, estado de factura y excluye borradores. [41c9ffa]

---

## [v2.27.0] - 2026-07-24

### ✨ Funcionalidades (Features)
- Retenciones de entes gubernamentales al cobrar: timbre fiscal, ISAE y Responsabilidad Social, con su cuenta contable y auto-configuración de tasa en la instalación. [9501dc3] [561967d] [ca074cb] [8424f8e]
- Primera fase del reporte HQ de facturas de venta. [f5c02ab]
- Balance de la selección en tiempo real en la Conciliación de Pagos. [b303440]
- Las descripciones del Mayor se expresan en lenguaje local. [c745bcf]

### 🐛 Correcciones (Fixes)
- El número de factura admite caracteres libres sin espacios, y los correos de proveedores se separan correctamente en los comprobantes. [4a67595]
- El override de Cuentas por Cobrar se adapta a ERPNext 15.106. [c317a11]
- Las direcciones independientes ya no se enlazan automáticamente a proveedores antiguos. [f6d1379]

---

## [v2.26.0] - 2026-07-22

### ✨ Funcionalidades (Features)
- Envío masivo automatizado de recordatorios de retención pendientes a contribuyentes especiales. [06d46f1]
- El reporte de Cuentas por Cobrar suma filtros Desde y Hasta. [e69127b]
- Aplicación de retenciones sobre facturas ya aprobadas y enviadas a HKA que salieron sin ellas. [7220896]
- Actualización del espacio de trabajo de conciliaciones bancarias. [7c6fa68]

### 🐛 Correcciones (Fixes)
- Se restauran los property setters de l10n_ve que se perdieron al renombrar el módulo. [de6537c]
- El Libro de Ventas atribuye correctamente las retenciones sin fecha y excluye las posteriores al período consultado. [1061738] [09aa019]
- Los reportes muestran la razón social del cliente o proveedor en vez de su identificador interno. [229a729]

---

## [v2.25.0] - 2026-07-18

### ✨ Funcionalidades (Features)
- Retasado a la tasa de emisión para clientes jurídicos al enviar a HKA. [e9136db]
- Las notas de crédito y débito fiscales usan la tasa BCV de su propia fecha de emisión. [64acc3f]
- Reporte de antigüedad de saldos multimoneda con filtros de sucursal y rango. [5b9865b]
- La ficha del cliente muestra saldo a favor / en contra y sus conexiones con notas de crédito y débito. [f78e12c] [3e44b4f]
- Botones de creación de retenciones de IVA e ISLR desde la Nota de Débito de Compra. [ac5ba0e]

### 🐛 Correcciones (Fixes)
- El IGTF Percibido cuadra con el Libro de Ventas. [406c809]
- Se omite el retasado cuando el cliente está deshabilitado. [6c05ab5]
- Se corrige el parseo de fechas de comprobante en los Libros de Ventas y Compras. [79cfced]
- Las series alfanuméricas con guiones funcionan en los comprobantes de retención. [11f88b1]

---

## [v2.24.3] - 2026-07-16

### 🐛 Correcciones (Fixes)
- El identificador de transacción de HKA pasa a ser único, evitando el rechazo por documento duplicado. [332fb1a]
- La vista previa sirve el PDF de la última emisión. [d274e93]
- El correo del proveedor se resuelve en cascada en el comprobante de retención. [a5ed344]
- El botón de Comprobante de Retención ISLR se oculta cuando el monto es cero. [ef2e459]
- Se corrigen los totales en bolívares de las devoluciones y el mapeo de sucursal en facturas de reemplazo. [5a50e21]
- Se desactiva el asiento de pérdida de precisión en las notas de crédito de retorno. [7f46b08]
- Se evita la duplicación y el cruce de direcciones principales en proveedores. [6fcb143]
- La clasificación de RIF cubre los casos sin guion. [0c4208b]

---

## [v2.24.2] - 2026-07-14

### 🐛 Correcciones (Fixes)
- El cron de envío a HKA deja de tener ventana horaria y corre las 24 horas. [efda055]

---

## [v2.24.1] - 2026-07-13

### ✨ Funcionalidades (Features)
- Identidad de marca Domina de fábrica: logo del Escritorio y del inicio de sesión, splash, favicon y kit oficial. [75e2d3c] [7d1c029]
- El endpoint del BCV queda configurado de fábrica, con auto-reparación en cada migración. [97a2f2c]

### 🐛 Correcciones (Fixes)
- Se corrige un error que rompía la vista previa de toda factura. [d6fc2f6]

---

## [v2.23.0] - 2026-07-13

### ✨ Funcionalidades (Features)
- La lógica de facturación digital se desacopla del dominio ISP. [4332cf4]

### 🐛 Correcciones (Fixes)
- El número de factura admite letras. [7005dd2]
- Se corrige el cálculo del monto del documento en los comprobantes de retención de ISLR. [ca5ab4d]
- La descarga masiva ya no queda en estado fallido por el tamaño del archivo comprimido. [a4ebc90]
- Se puede cancelar un recibo cuando la factura aún está por emitir. [5cd6e77]

---

## [v2.22.0] - 2026-07-10

### ✨ Funcionalidades (Features)
- Método de cálculo del IVA configurable: base imponible o total de la factura, con ayuda dinámica y validación obligatoria. [a7fa577] [282342a]
- Reporte detallado de ventas de CONATEL con cálculo bimonetario unificado. [e55c6e7]
- Rediseño del Libro de Compras y adición del Sustraendo al reporte de ISLR, excluyendo documentos anulados. [d51f1e6]
- La sucursal suma el campo de nombre comercial. [15148ce]

### 🐛 Correcciones (Fixes)
- Se endurece el comportamiento a prueba de fallos de la serie digital. [f0d4c47]
- El registro de HKA ya no puede crearse manualmente, garantizando la integridad de los registros automáticos. [9c7dc39]
- Se omite el asiento de ajuste de precisión bajo el método de cálculo desde el total de la factura. [ed84830]

---

## [v2.21.0] - 2026-07-10

### ✨ Funcionalidades (Features)
- Generación del comprobante de retención de IVA e ISLR directamente desde la Factura de Compra. [8706348]
- Emisión a HKA en un clic desde la factura, con protección contra duplicados. [9e97574]

---

## [v2.20.1] - 2026-07-09

### 🐛 Correcciones (Fixes)
- Restricción de permisos sobre el doctype de log de HKA para evitar su creación manual por parte de los usuarios, garantizando la integridad de los registros automáticos. [9c7dc39]

---

## [v2.20.0] - 2026-07-08

### ✨ Funcionalidades (Features)
- Implementación de series y sucursales dinámicas para la generación de comprobantes de retención de IVA e ISLR. 70b2253

---

## [v2.19.0] - 2026-07-08

### ✨ Funcionalidades (Features)
- Incorporación del reporte de conciliación bancaria avanzada en los espacios de trabajo. [8e743be]

### 🐛 Correcciones (Fixes)
- Resolución de incidencias en los fixtures de Workspace y Role, incluyendo la restauración del setter de propiedades. [e44d448]
- Ajuste en la visibilidad de los espacios de trabajo administrativos y corrección en la lógica de redirección al escritorio mediante fixtures. [90b19df]

---

## [v2.18.1] - 2026-07-07

### 🐛 Correcciones (Fixes)
- Se ajustó la visibilidad de los campos técnicos `hka_status` y `hka_series` en el módulo HKA para asegurar que permanezcan ocultos (`hidden=1`) en la interfaz. [ee16138]

---

## [v2.18.0] - 2026-07-06

### ✨ Funcionalidades (Features)
- Incorporación de los campos técnicos `hka_status` y `hka_series` en los documentos de venta, permitiendo una trazabilidad detallada de la integración con HKA.

### 🐛 Correcciones (Fixes)
- Implementación de validaciones de semántica estricta para los campos `hka_status` y `hka_series`, garantizando la integridad de los datos para procesos de auditoría fiscal.
- Refactorización de la derivación canónica hacia el esquema `digital_invoice/hka_status` junto con la ejecución de un backfill de datos históricos para la entidad de producto.

---

## [v2.17.0] - 2026-07-06

### ✨ Funcionalidades (Features)
- Se añadieron nuevos campos para teléfonos de soporte y cobranzas en el doctype **VE Branch**, junto con una reestructuración estética de la sección de contacto en tres columnas para mejorar la usabilidad. 7e1c5f0, f586ea6, fd747e3, 00ede07
- Extensión de la validación `_validate_tasa_coherencia` en la integración con **HKA** para incluir a clientes jurídicos, implementando una política de seguridad *fail-closed*. a28590c

### 🐛 Correcciones (Fixes)
- Corrección de error en el árbol de sucursales que se visualizaba vacío para usuarios con permisos de acceso restringido. e253a1c
- Resolución de excepción de ejecución "too many values to unpack" en la utilidad de sistema `is_juridical_customer`. d601f3d
- Ajuste crítico en la lógica de **HKA**: la fecha de la tasa BCV ahora se resuelve a partir de la tasa del documento en lugar del `posting_date`, garantizando consistencia fiscal. 555c8fb
- Optimización de base de datos mediante una consulta *sargable* en la función `resolve_exchange_rate_date` para mejorar el rendimiento en búsquedas de tasas de cambio. 03adfea

---

## [v2.16.0] - 2026-07-05

### ✨ Funcionalidades (Features)
- **Compras:** Se actualizaron los accesos de los botones de Notas de Crédito (NC) y Notas de Débito (ND) para que apunten correctamente a los doctypes de VE Purchase. eb07bb8

---

## [v2.15.0] - 2026-07-05

### ✨ Funcionalidades (Features)
- Se restringió la visibilidad del número de referencia en la interfaz de usuario para que sea accesible únicamente por usuarios con rol de Administrador. [f3fa087]

---

## [v2.14.3] - 2026-07-05

### 🐛 Correcciones (Fixes)
- Se habilitó la visualización del número de referencia en los extractos bancarios dentro de la interfaz de usuario. [df536d5]

---

## [v2.14.2] - 2026-07-05

### 🐛 Correcciones (Fixes)

- **Cálculo de IGTF:** Se corrigió el cálculo de IGTF en el módulo de cobros para casos donde el monto está expresado en Bs. pero el pago se procesa en USD. [2f4ffed]
- **Conversión de Moneda:** Ajustada la lógica de conversión a USD en el cálculo de KPIs reales y en los reportes de Excel para facturas pendientes y borradores, asegurando el uso de la tasa de cambio del periodo correspondiente. [aa21323, 3aaa310]
- **Lógica de Facturación:** Se actualizó el criterio de facturas pendientes por cobrar para excluir correctamente aquellas que ya poseen un saldo pendiente (outstanding_amount) de cero. [6dd2419]
- **Arquitectura de Reportes:** Refactorización integral de la función de descarga de detalles de KPI en Excel, segmentándola en funciones helper especializadas para mejorar la mantenibilidad y el determinismo en el cálculo de campos en VEF. [022a7da, ab2b776]
- **Conteo de Documentos:** Corregido el conteo de facturas en estado borrador y pendientes que poseen controles pre-asignados. [6c6faf2]
- **Interfaz de Usuario:** Eliminación de los enlaces de agenda y planificación en el menú de navegación principal. [c624b79]
- **Estabilidad:** Solucionado un error de sintaxis en el script de reporte gerencial que afectaba la ejecución del módulo. [fba859c]

---

## [v2.14.1] - 2026-07-05

### 🐛 Correcciones (Fixes)
- **Reporte Gerencial**: Se corrigió la lógica de cálculo de ratios cuando se presentan totales negativos y se subsanó un error técnico en el uso de `hasattr` sobre objetos de tipo diccionario. [7371dc0](7371dc0)

---

## [v2.14.0] - 2026-07-04

### ✨ Funcionalidades (Features)
- Se implementaron mejoras significativas en el reporte pro/gerencial, incluyendo la capacidad de filtrar retenciones en cero para una visualización de datos más precisa y limpia. (a9c5c99)

---

## [v2.13.0] - 2026-07-04

### ✨ Funcionalidades (Features)
- Actualización y optimización integral del Reporte Gerencial y Reporte Pro, incluyendo mejoras en el formato visual y centrado de tablas.
- Refactorización de la API para el manejo de descargas de detalles KPI en Excel, mejorando la estructura del módulo de reportes.

### 🐛 Correcciones (Fixes)
- Resolución de vulnerabilidad crítica de seguridad BOLA (Broken Object Level Authorization) mediante la implementación de filtrado jerárquico de sucursales.
- Corrección en el cálculo de ratios de Base, IVA e IGTF para los procesos de cobro en divisas USD y VES.
- Ajuste en la lógica de obtención de datos para tarjetas KPI, normalizando la referencia a las tablas de entradas de pago.
- Mejora en la visualización de las vistas de lista de facturas de venta y compra mediante la implementación de columnas dinámicas para campos de fecha.

---

## [v2.12.0] - 2026-07-03

### ✨ Funcionalidades (Features)
- Se agregó el campo de logo en la entidad Bank y se implementó la integración con soporte para códigos SWIFT de 4 dígitos. 37c95a3

### 🐛 Correcciones (Fixes)
- Ajuste en la configuración de visibilidad de campos en la vista de lista (`in_list_view`). 500d7c7

---

## [v2.11.0] - 2026-07-03

### ✨ Funcionalidades (Features)
- Se extendió la validación de coherencia de tasa (_validate_tasa_coherencia) para incluir a personas jurídicas bajo un esquema de fail-closed en el módulo HKA. [948f6c1]
- Incorporación del nuevo campo "Teléfono de cobranzas" en el modelo de VE Branch. [d34726e]

### 🐛 Correcciones (Fixes)
- Corrección en la lógica de resolución de la tasa BCV: ahora se determina a partir de la tasa del documento en lugar de la fecha de contabilización (posting_date). [50b70fd]
- Refactorización de la función resolve_exchange_rate_date para implementar una consulta sargable, optimizando el rendimiento y el uso de índices en la base de datos. [eb3ce28]

---

## [v2.10.1] - 2026-07-03

### 🐛 Correcciones (Fixes)
- Se corrigió un error de lógica ("too many values to unpack") en la función de utilidad `is_juridical_customer` que afectaba el procesamiento de tipos de cliente. [5f8cd83]

---

## [v2.10.0] - 2026-07-02

### ✨ Funcionalidades (Features)
- Optimización del rendimiento en base de datos mediante el ajuste del orden de columnas en el índice compuesto de **Sales Invoice**. (78cf0e8)
- Implementación de validaciones dinámicas y estáticas para filtros de fechas en **Reporte Pro**. (78cc35e)
- Mejora en la velocidad de carga y alineación técnica de los KPIs de flujo de caja real en **Reporte Pro**. (e6a0640)

---

## [v2.9.3] - 2026-06-22

### 🐛 Correcciones (Fixes)
- Se implementó la validación del campo `posting_date` antes de actualizar la tasa de cambio en los asientos de pago (Payment Entry) para garantizar la consistencia de los datos financieros. [8aca506]

---

## [v2.9.2] - 2026-06-22

### 🐛 Correcciones (Fixes)
- Se corrigió un error en el proceso de Payment Entry donde la tasa de cambio no se actualizaba automáticamente al modificar la fecha de contabilización. [76feac4]

---

## [v2.9.1] - 2026-06-22

### 🐛 Correcciones (Fixes)
- Se mitigó una vulnerabilidad de seguridad relacionada con la lectura no autorizada de archivos. [c018567]
- Se corrigió un error en el cálculo del total dentro del libro de compras para garantizar la integridad de los reportes financieros. [c018567]
- Se eliminó un fallo que provocaba la duplicación en la descarga de archivos PDF, optimizando la gestión de documentos. [c018567]

---

## [v2.9.0] - 2026-06-22

### ✨ Funcionalidades (Features)
- Se habilitó el soporte para letras y caracteres alfanuméricos en el número de control de facturas de máquinas fiscales, tanto en el módulo de ventas como en el de compras.
- Inclusión de guiones como caracteres válidos en el campo de número de control para facturas de venta.

### 🐛 Correcciones (Fixes)
- Resolución de incidencias técnicas en los reportes de IGTF y Libro Mayor para garantizar la integridad de los datos.
- Corrección de un error de ejecución (AttributeError) que se presentaba en las órdenes de compra y venta al realizar el cálculo de retenciones de ISLR.
- Mejora en la robustez del módulo de retenciones mediante una gestión más segura de los campos de los documentos.

---

## [v2.8.0] - 2026-06-20

### ✨ Funcionalidades (Features)
- **Descarga masiva de facturas (HKA):** Se implementó la capacidad de descargar facturas sin límites, procesando la información en lotes de 1000 registros y añadiendo persistencia del progreso para garantizar la integridad del proceso. d294068

### 🐛 Correcciones (Fixes)
- **Validación de Workspace:** Cambio del tipo de enlace en "Cajas" a tipo URL para prevenir errores de validación durante los procesos de importación. 87741f8
- **Interfaz de Usuario:** Renombramiento del acceso "Cajas" a "Conciliación de Cajas" en el workspace para mejorar la claridad semántica. f384dbb

---

## [v2.7.0] - 2026-06-19

### ✨ Funcionalidades (Features)
- Se implementó el nuevo método de API `get_portal_banks` con soporte para almacenamiento en caché, optimizando el tiempo de respuesta en la obtención de bancos del portal. [2eea280]

---

## [v2.6.4] - 2026-06-19

### ✨ Funcionalidades (Features)
- Refactorización de la localización venezolana (l10n_ve) para trasladar el motor de conciliación al módulo mint, incluyendo un shim de compatibilidad para asegurar la transición arquitectónica. (e19e512)

### 🐛 Correcciones (Fixes)
- Mejora en la robustez de la lógica de validación para referencias de tipo integer, optimizando el manejo de tipos de datos en el sistema. (c1a842f)

---

## [v2.6.3] - 2026-06-17

### ✨ Funcionalidades (Features)
- **Optimización de reportes**: Se mejoró el rendimiento del libro mayor analítico (**analytical_ledger**) y se agregaron índices de base de datos en los ítems de retención para agilizar el procesamiento de datos.
- **Mejora en base de datos**: Implementación de índices de consulta en diversos DocTypes de la localización venezolana (**l10n_ve**), optimizando la velocidad de respuesta del sistema en operaciones regionales.

---

## [v2.6.2] - 2026-06-16

### 🐛 Correcciones (Fixes)
- Se corrigió un error en los reportes contables que traducía las claves de DocType, asegurando que los identificadores internos se mantengan consistentes. [2a3799d]

---

## [v2.6.1] - 2026-06-16

### 🐛 Correcciones (Fixes)
- Se optimizó el filtro de clientes en el panel de control (dashboard) mediante la implementación de un componente de Autocomplete y una consulta personalizada para mejorar la precisión y el rendimiento de las búsquedas. [6407a54]

---

## [v2.6.0] - 2026-06-16

### ✨ Funcionalidades (Features)
- Implementación de la lógica para la conciliación de cobros contra su depósito bancario correspondiente, optimizando el flujo de cierre de caja.
- Incorporación del helper técnico `_is_cash_like_receive` para la identificación y manejo especializado de pagos en efectivo en el módulo de cobros.

### 🐛 Correcciones (Fixes)
- Mejora de la robustez y "hardening" en los procesos de conciliación bancaria para la localización de Venezuela (l10n_ve).
- Corrección crítica en el cálculo de montos de depósitos (ajuste de factor x100) y fortalecimiento de la lógica de conciliación en el módulo de cobros.

---

## [v2.5.1] - 2026-06-14

### 🐛 Correcciones (Fixes)
- Se implementaron mejoras de seguridad y optimización de rendimiento en el proceso de descarga HKA y en la generación de reportes AR/AP. [254609a]

---

## [v2.5.0] - 2026-06-14

### ✨ Funcionalidades (Features)
- Implementación de **base_total_exempt** (VEF) como la fuente de verdad central para el cálculo y gestión de montos exentos en el módulo de contabilidad. [8c18002]

### 🐛 Correcciones (Fixes)
- Ajuste en la lógica de **total_exempt** para utilizar **net_amount**, asegurando la consistencia técnica y paridad de datos con el campo **base_total_exempt**. [6c6e191]

---

## [v2.4.0] - 2026-06-13

### ✨ Funcionalidades (Features)
- Implementación de soporte para **Property Setters** en los campos de sucursal, mejorando la flexibilidad y el control del sistema de permisos. [8d4ac97]

---

## [v2.3.0] - 2026-06-13

### ✨ Funcionalidades (Features)
- Implementación de la descarga masiva para facturas de venta certificadas de HKA. [744e6aa]

### 🐛 Correcciones (Fixes)
- Implementación de controles de seguridad BOLA (Broken Object Level Authorization) en los procesos de descarga masiva y ejecución de jobs. [c2ad799]
- Ajuste en `process_download_job` definiendo `ignore_permissions = True` para asegurar la ejecución correcta del proceso interno. [355cc79]
- Aplicación de optimizaciones y mejoras técnicas en el módulo de descarga HKA. [9386a2b]

---

## [v2.2.2] - 2026-06-13

### 🐛 Correcciones (Fixes)
- Refactorización de la función `_get_allowed_branches` en el dashboard para implementar validaciones específicas por empresa. (3fb7620)
- Ajuste en la validación de sucursales para omitir la verificación cuando no existan sucursales tipo VE configuradas. (8b5d93d)

---

## [v2.2.1] - 2026-06-12

### 🐛 Correcciones (Fixes)
- Se corrigió la lógica de aplicación de parches de reportes para asegurar su ejecución correcta tanto en workers web como en workers de cola (RQ). 5312f62
- Mejora en la estabilidad del entorno de pruebas mediante la restauración segura de frappe.local.db en los tests de parches. 35996f8

---

## [v2.2.0] - 2026-06-11

### ✨ Funcionalidades (Features)
- Se implementó la visualización de la conversión a USD como valor principal en las tarjetas numéricas del dashboard y se optimizó el diseño de la tarjeta de tasa.
- Se añadió el desglose de referencia en USD bajo los valores expresados en bolívares en tarjetas numéricas y gráficos.

### 🐛 Correcciones (Fixes)
- Ajuste en la lógica del dashboard para utilizar la tasa de cambio específica de cada transacción al calcular la referencia en USD en las tarjetas [caccb45].

---

## [v2.1.1] - 2026-06-11

### 🐛 Correcciones (Fixes)
- Se corrigió el atajo de "Conciliar Banco" en el Workspace, asegurando que el tipo de acceso sea mediante URL para su correcto funcionamiento. [4ca061f]

---

## [v2.1.0] - 2026-06-09

### ✨ Funcionalidades (Features)
- **Contabilidad:** Se implementó el asentamiento automático del IGTF en el proceso de cobros.
- **Reportes:** Se ajustó el campo RIF por Documento en el reporte de IGTF para mayor precisión en la información.

### 🐛 Correcciones (Fixes)
- **PDF:** Se resolvió un error de deadlock que afectaba la generación de archivos PDF.
- **Review:** Se integraron optimizaciones y correcciones técnicas derivadas de revisiones de código y sugerencias de IA.

---

## [v2.0.1] - 2026-06-08

### 🐛 Correcciones (Fixes)
- **Dashboard**: Se optimizó el proceso de exportación mediante el uso de recursos nativos y se implementó la validación obligatoria de permisos de lectura para asegurar la integridad del acceso a los datos. [f0f2f10]

---

## [v2.0.0] - 2026-06-08

### ✨ Funcionalidades (Features)
- Implementación de la obligatoriedad del centro de costos a nivel de sucursal para asegurar la integridad de los datos contables. [25a8b25]

---

## [v1.11.0] - 2026-06-08

### ✨ Funcionalidades (Features)
- Se integraron mini tarjetas informativas al reporte exportable de Excel del dashboard. ef30b5b

### 🐛 Correcciones (Fixes)
- Corrección en la lógica de sumatoria de los totales para asegurar la precisión de los datos presentados. ef30b5b

---

## [v1.10.1] - 2026-06-07

### 🐛 Correcciones (Fixes)
- Se implementó el uso de `safe_get_pdf` para asegurar la correcta generación y descarga de reportes en formato PDF, específicamente para los módulos de Customer Retention e IGTF. [31cb9c7]

---

## [v1.10.0] - 2026-06-07

### ✨ Funcionalidades (Features)
- Implementación de reporte gerencial jerárquico en moneda local (bolívares) e integración de zona HKA vinculada a la dirección para la localización de Venezuela (l10n_ve).
- Mejora en la interfaz y usabilidad de la vista de lista de impuestos municipales.

### 🐛 Correcciones (Fixes)
- Corrección de seguridad en el Dashboard: se restringió la visualización de IGTF, FX y Gastos aplicando un filtrado estricto por sucursal permitida para el usuario.

---

## [v1.9.0] - 2026-06-07

### ✨ Funcionalidades (Features)
- **Reestructuración del Dashboard Gerencial**: Se rediseñó la disposición de las tarjetas de métricas, moviéndolas sobre la tabla principal, y se implementó la lógica para calcular sumatorias directamente desde los datos de la tabla (1d37631, cfd8ad1).
- **Nuevo Diseño Premium**: Actualización visual del dashboard utilizando un tema "premium slate" para mejorar la experiencia de usuario (845a520).
- **Soporte para IGTF**: Adición de columnas y tarjetas específicas para el seguimiento del Impuesto a las Grandes Transacciones Financieras (1d37631).
- **Plantillas de Impresión**: Incorporación de plantillas HTML personalizadas para la generación de reportes de localización (22938fa).
- **Optimización de Exportación**: Implementación de un parche optimizado para la exportación a Excel en los módulos de contabilidad y localización venezolana (2c07f9c).
- **Etiquetado Beta**: Inclusión de etiquetas (BETA) en los módulos de administración para identificar funciones en periodo de prueba (cfd8ad1).

### 🐛 Correcciones (Fixes)
- **Consistencia Financiera**: Alineación de los cálculos financieros entre el panel gerencial y el panel ISP para asegurar la integridad de la información (171606c).
- **Refactor de Reportes**: Ajustes técnicos en la generación de libros contables y exportaciones a Excel basados en revisiones de calidad (c7136b2).
- **Equivalencias de Facturación**: Corrección en el cálculo y visualización de equivalentes de facturación dentro del nuevo tema del dashboard (845a520).

---

## [v1.8.0] - 2026-06-05

### ✨ Funcionalidades (Features)
- Integración del módulo completo de Administración que incluye gestión de Clientes, Proveedores, Inventario, Bancos y Cajas (Ingresos, Egresos y Transferencias).
- Implementación de reportes financieros bajo normativa VEN-NIF y libros oficiales requeridos por el SENIAT.
- Nuevo reporte de Mayor Analítico independiente con soporte para consultas de gran volumen mediante prepared_report y filtros de Cuenta Contable para optimizar el rendimiento de PDF.
- Reestructuración de los Estados de Resultados y Situación Financiera a formato vertical de 3 columnas y diseño horizontal (landscape) con indentación jerárquica.
- Implementación del módulo tributario con reportes de IVA Forma 30, Prorrata y gestión de retenciones (IVA, ISLR, Municipales).
- Rediseño de la plantilla de impresión oficial de 7 columnas del SENIAT con exportación directa a PDF y Excel para la declaración de IVA.
- Incorporación de montos equivalentes en divisas (USD/Bs) en tarjetas y tablas de resumen del Dashboard Gerencial.
- Reorganización integral de los espacios de trabajo (Workspaces) para Contabilidad, Tributos y Administración, optimizando la jerarquía de navegación y acceso a reportes.
- Implementación de descripción automática en reportes y restauración de la cuadrícula estándar para el registro de asientos contables.

### 🐛 Correcciones (Fixes)
- Corrección de errores de desconexión en la base de datos al procesar impresiones PDF y mejora en la seguridad de los filtros en plantillas.
- Resolución de crashes de compilación en microtemplate.js y fallos silenciosos en el frontend del Mayor Analítico.
- Ajuste de compatibilidad del JavaScript de plantillas al estándar ES5 para asegurar el correcto funcionamiento con wkhtmltopdf.
- Robustecimiento del proceso de exportación a PDF mediante el saneamiento de filtros vacíos para evitar TypeErrors.
- Corrección del orden de argumentos SQL en funciones de balances jerárquicos y solución a errores RPC en el módulo tributario.
- Ajustes de sintaxis en consultas de facturación y corrección de enlaces rotos en los accesos directos de la barra lateral.
- Normalización de nombres de archivos y carpetas para evitar conflictos con caracteres especiales y tildes en el sistema de archivos.
- Protección de la función de traducción global para evitar sobreescritura de cadenas en reportes de Prorrata IVA.

---

## [v1.7.2] - 2026-06-04

### 🐛 Correcciones (Fixes)
- Se corrigió la advertencia de retenciones faltantes y se resolvió el error de duplicación de registros en la vista de lista (b0b6daa).

---

## [v1.7.1] - 2026-06-03

### ✨ Funcionalidades (Features)
- Refactorización del módulo de tipo de cambio para integrar la lógica de conversión de moneda mediante el evento on_change, permitiendo una actualización reactiva de los valores.

---

## [v1.7.0] - 2026-06-03

### ✨ Funcionalidades (Features)
- Implementación de un sistema de caché para la función `get_exchange_rate` basado en fecha y moneda, que incluye lógica de invalidación para optimizar el rendimiento. b53b894
- Normalización de fechas en las claves de caché para garantizar la consistencia y correcta recuperación de los datos almacenados. e9359ed

---

## [v1.6.1] - 2026-06-02

### 🐛 Correcciones (Fixes)
- Se integró una lista blanca (whitelist) para los DocTypes de sucursales en la subconsulta `_get_gl_entries` del dashboard, asegurando que los registros contables se filtren y muestren correctamente. a80fe27

---

## [v1.6.0] - 2026-06-02

### ✨ Funcionalidades (Features)
- Implementación del nuevo DocType **Dashboard Gerencial**, que integra un resumen financiero personalizado y 13 tarjetas de métricas clave para la toma de decisiones. [0a23e0b]
- Optimización crítica de rendimiento en la carga de datos del dashboard mediante el uso de subconsultas SQL, evitando desbordamientos en cláusulas IN al filtrar vouchers por sucursal. [7f3c65d]
- Mejora de eficiencia en la capa de datos eliminando consultas N+1 a través de agrupamiento en memoria y optimización de procesos de renderizado. [54b141e]
- Adición de una fila virtual "Sin Sucursal" en las tablas de resumen, garantizando que la sumatoria de las tablas coincida exactamente con los valores de las tarjetas informativas. [ad84414]
- Refactorización integral del backend: traducción de todas las variables internas, claves JSON y argumentos de funciones al estándar de la industria (Inglés). [6a48b42]
- Actualización de estilos en tablas de sucursales para asegurar compatibilidad visual con el tema Dark Mode Premium. [2f788a2]

### 🐛 Correcciones (Fixes)
- Ajuste en la precisión de los cálculos de gastos mensuales y anuales, así como en la consolidación de disponibilidad de USD en bancos y caja. [c9c91ad]
- Implementación de saneamiento (sanitization) en el renderizado de nombres de sucursales para prevenir vulnerabilidades de Cross-Site Scripting (XSS). [54b141e]
- Resolución de excepción `AttributeError` en consultas de la tabla de gastos mediante la implementación correcta de `as_dict=True` en las peticiones SQL. [f4d5632]
- Corrección en el binding de manejadores de eventos en scripts de formulario, asegurando que los triggers reconozcan nombres con espacios exactos. [e9fa08a]

---

## [v1.5.0] - 2026-05-29

### ✨ Funcionalidades (Features)
- Implementación de nuevas métricas y tarjetas de indicadores en el tablero (dashboard) para el perfil de gerencia, enfocadas en la visualización del estatus financiero. 9d7bded

### 🐛 Correcciones (Fixes)
- Optimización de consultas en el backend para las tarjetas numéricas mediante la integración de mecanismos de caché y filtros estrictos por `root_type` para mejorar el rendimiento. cacef1d

---

## [v1.4.0] - 2026-05-29

### ✨ Funcionalidades (Features)
- Implementación de totales generales en el reporte de balance de comprobación (c51bdd7).

### 🐛 Correcciones (Fixes)
- Corrección de errores en la generación y formato de impresión para reportes PDF (c51bdd7).

---

## [v1.3.1] - 2026-05-26

### 🐛 Correcciones (Fixes)
- **Permisos:** Se restauró la visibilidad estricta de VE Branch fuera de la jerarquía del árbol para asegurar el control de acceso correcto. b6ce7ce

---

## [v1.3.0] - 2026-05-26

### ✨ Funcionalidades (Features)
- Implementación de la lógica para retornar la lista de sucursales permitidas asociadas al usuario. [2ec1e6a]

---

## [v1.2.0] - 2026-05-26

### ✨ Funcionalidades (Features)
- **Reporte de Balance de Comprobación VEF**: Creación e implementación del nuevo reporte `trial_balance_vef`.
- **Tarjetas Gerenciales**: Implementación de tarjetas de visualización para montos de gestión y limpieza de componentes numéricos.
- **Optimización de Reportes**: Mejora en el rendimiento y optimización del balance de comprobación en bolívares (VEF).

---

## [v1.1.3] - 2026-05-25

### 🐛 Correcciones (Fixes)
- Se habilitó la capacidad de asignar usuarios a múltiples sucursales de manera simultánea dentro del módulo de sucursales (`ve_branch`) [8420314].

---

## [v1.1.2] - 2026-05-25

### 🐛 Correcciones (Fixes)
- **Gestión de sucursales:** Se habilitó la posibilidad de asignar usuarios a múltiples sucursales de forma simultánea, corrigiendo la limitación previa en el módulo de sucursales. [b09508e]

---

## [v1.1.1] - 2026-05-25

### 🐛 Correcciones (Fixes)
- Se refactorizó el sistema de permisos para eliminar la inspección frágil del stack en `user_permissions_patch` y `permissions`, mejorando la estabilidad y robustez del código. [0fb9714]

---

## [v1.1.0] - 2026-05-20

### ✨ Funcionalidades (Features)
- Implementación de un sistema de validación, herencia y propagación de roles en el módulo `ve_branch`.
- Consolidación de la intercepción de permisos para VE Branch junto con la aplicación de tipado estricto para mejorar la seguridad y mantenibilidad del código.
- Refuerzo de seguridad en el Workspace de Facturación Digital, restringiendo el acceso exclusivamente a roles administrativos del área de contabilidad.

---

## [v1.0.31] - 2026-05-14

### 🐛 Correcciones (Fixes)
- **Cálculo de ISLR:** Se corrigió un error en la lógica de cálculo que omitía la conversión del sustraendo a la moneda base antes de realizar la resta, garantizando la precisión de los montos resultantes. [52744da]

---

## [v1.0.30] - 2026-05-14

### 🐛 Correcciones (Fixes)
- Se aplicaron diversas correcciones técnicas en el módulo del **libro de venta** para mejorar la integridad y precisión de los registros (8a8fd8e).

---

## [v1.0.29] - 2026-05-14

### 🐛 Correcciones (Fixes)
- Se implementó el saneamiento de datos maestros de clientes y la lógica de reconciliación entre el Libro Mayor (GL) y el Libro de Ventas [f5d198d].

---

## [v1.0.28] - 2026-05-14

### ✨ Funcionalidades (Features)
* Implementación de protección HKA en el proceso de cancelación de pagos y renombre de componentes ISLR para mayor consistencia.
* Integración de notificaciones automáticas vía Telegram en el pipeline de CI para alertar sobre fallos en la ejecución de pruebas.

### 🐛 Correcciones (Fixes)
* Ajustes en la lógica de `payment_entry` siguiendo revisiones de código, incluyendo el uso de `ignore_permissions=True` y `get_link_to_form()`.
* Mejora en la confiabilidad del CI mediante la configuración de `pipefail` para asegurar la correcta propagación de códigos de error durante los tests.
* Corrección en el descubrimiento de pruebas unitarias (`test_hka`, `test_islr_mixin`) y actualización de mocks para validaciones de ISLR.
* Inclusión de 8 nuevos casos de prueba específicos para la validación de la lógica de protección HKA.

---

## [v1.0.27] - 2026-05-12

### 🐛 Correcciones (Fixes)
- Se renombró el método `_build_islr_tax_row` en el flujo de compras para evitar conflictos técnicos por sobreescritura de métodos, asegurando la integridad del cálculo de retenciones ISLR. [d971627]

---

## [v1.0.26] - 2026-05-12

### 🐛 Correcciones (Fixes)
- **Seguridad:** Se eliminó el uso de f-strings en consultas SQL para prevenir vulnerabilidades de inyección, asegurando el manejo correcto de parámetros en la base de datos. 457db6b
- **Logging:** Optimización del rastreo de errores en el módulo TFHKA mediante la implementación de `frappe.get_traceback()`, mejorando la capacidad de depuración técnica. 457db6b

---

## [v1.0.25] - 2026-05-12

### 🐛 Correcciones (Fixes)
- Se corrigió el flujo de integración continua al incluir ERPNext como una dependencia obligatoria para la instalación. [c3b46d4]

---

## [v1.0.24] - 2026-05-12

### 🐛 Correcciones (Fixes)
- Se fijó la versión del framework Frappe a `version-15` en la configuración de CI para garantizar la compatibilidad con Python 3.12 y asegurar la estabilidad de los despliegues. (a82771a)

---

## [v1.0.23] - 2026-05-12

### ✨ Funcionalidades (Features)
- Se incorporó una nueva suite de pruebas unitarias dedicada a la validación de los cálculos fiscales para Venezuela (VE), mejorando la confiabilidad de la lógica tributaria.

### 🐛 Correcciones (Fixes)
- Corrección en el pipeline de Integración Continua (CI) mediante el ajuste en la instalación de `mariadb-client` y la actualización de las dependencias del workflow (57c2250).

---

## [v1.0.22] - 2026-05-11

### ✨ Funcionalidades (Features)
- Mejora de la experiencia de usuario (UX) en los reportes financieros mediante la supresión de la generación automática de `prepared_report`. [fd42024](https://github.com/example/repo/commit/fd42024)

### 🐛 Correcciones (Fixes)
- Implementación de `frappe.get_traceback()` en la función `reset_all_prepared_reports` para garantizar un registro de errores (logging) completo y detallado durante la ejecución. [2dc3e1d](https://github.com/example/repo/commit/2dc3e1d)

---

## [v1.0.21] - 2026-05-11

### ✨ Funcionalidades (Features)
- **Integración de Sucursales:** Soporte para VE Branch en Notas de Crédito, Notas de Débito y filtros específicos dentro del Libro de Compras.
- **Gestión de Notas de Débito (ND):** Soporte integral para ND en comprobantes de IVA/ISLR, incluyendo bloqueo de cancelación y optimización en el reporte de compras.
- **Integración ISLR con TFHKA:** Implementación completa para la emisión, anulación y previsualización de comprobantes de retención ISLR mediante TFHKA.
- **Centralización de ISLR:** Unificación de la lógica de retención ISLR directamente en la Factura de Compra con soporte para esquemas multi-concepto.
- **Cumplimiento Fiscal SENIAT:** Implementación del formato fiscal oficial para el Libro de Compras, incluyendo validaciones de fechas y generación de archivos TXT/XML.
- **Estabilización de Notas de Crédito (NC):** Mejora del ciclo de vida de NC de compras mediante el uso de reconciliación nativa y corrección en los asientos contables (GL) de retenciones.
- **Mejoras en Retención de IVA:** Incorporación de validaciones para evitar duplicados e indicadores específicos para protocolos HKA.
- **Suite de Pruebas:** Adición de tests unitarios para garantizar la integridad de los cálculos de retenciones IVA e ISLR.

### 🐛 Correcciones (Fixes)
- **Cálculo de Impuestos:** Corrección en el manejo de IVA con alícuotas múltiples y atomización de correlativos para evitar conflictos.
- **Validación SENIAT:** Ajuste en los generadores de archivos XML y TXT para asegurar la validación exitosa en el portal del SENIAT.
- **Reportes Fiscales:** Corrección en la integración de Notas de Crédito de compras dentro del Libro de Compras y los archivos de exportación ISLR.
- **Robustez de Datos:** Implementación de fallbacks defensivos en las descripciones de retención de ISLR cuando el número de factura no está presente.
- **Sincronización de Comprobantes:** Alineación técnica entre los vouchers de retención de ISLR e IVA para mantener consistencia en los datos fiscales.

---

## [v1.0.20] - 2026-05-08

### ✨ Funcionalidades (Features)
- Actualización de la lógica interna en las funciones encargadas de la carga de comprobantes de retención.

### 🐛 Correcciones (Fixes)
- **Seguridad:** Se corrigió una vulnerabilidad crítica en los endpoints de retención que permitía el bypass de permisos de administrador y se reforzó la validación de acceso. 7307bd4
- Mejora en la validación del período fiscal y depuración de código en los endpoints de retención para asegurar la integridad de los datos. ca1c4ea

---

## [v1.0.19] - 2026-05-08

### 🐛 Correcciones (Fixes)
- Se implementó la validación del número de documento en los módulos de clientes y proveedores para garantizar la integridad de la información (3152f04).

---

## [v1.0.18] - 2026-05-07

### ✨ Funcionalidades (Features)
- Se implementó la asignación automática del centro de costos desde la sucursal (VE Branch) al momento de enviar documentos. [da3c295]

---


## [v1.0.17] - 2026-04-29

### 🐛 Correcciones (Fixes)

- **Compras:** Se corrigió un error que generaba asientos contables (GL) desbalanceados al procesar retenciones de IVA. 5979ff0
- **Libro de Ventas:** Se actualizaron los totales para incluir Notas de Crédito y se integró el impuesto IGTF al formato de reporte del SENIAT. 0adfad2
- **Contabilidad:** Ajuste en los algoritmos de cálculo de retenciones y mejora en la lógica de balanceo para asientos contables en el módulo de compras. 0a66bf2

---

## [v1.0.16] - 2026-04-28

### ✨ Funcionalidades (Features)
- Se habilitó la capacidad para que el rol de Administrator pueda forzar el envío a HKA, omitiendo las validaciones de tasa del BCV. [37f02b6]

### 🐛 Correcciones (Fixes)
- Corrección de error de lógica por doble negación en el cálculo de totales acumulados de retenciones dentro de `set_cumulative_total`. [3c67a51]
- Se resolvió un problema de doble contabilización de retenciones de IVA en los asientos contables (GL Entries) del módulo de compras. [5bd83d6]

---

## [v1.0.15] - 2026-04-27

### 🐛 Correcciones (Fixes)
- Se ajustó la configuración inicial de la entidad **Company** para establecer valores por defecto vacíos y se desactivó la funcionalidad de **inventario perpetuo**. [12e32a1]

---

## [v1.0.14] - 2026-04-27

### ✨ Funcionalidades (Features)
- Refactorización y optimización del módulo `audit_orphan_accounts` para mejorar la calidad del código y la eficiencia de las auditorías. 80e30e0

### 🐛 Correcciones (Fixes)
- Resolución de problemas de integridad de datos: corrección de 15 referencias huérfanas en cuentas detectadas tras la migración del plan 2026. 3436f6f

---

## [v1.0.13] - 2026-04-27

### 🐛 Correcciones (Fixes)
- **Reporte de IVA:** Se corrigió la inclusión de Notas de Crédito en los totales del resumen, asegurando que los montos con signo negativo se procesen correctamente. (39ce93d)
- **Indicadores Fiscales:** Actualización de la etiqueta "Pendiente" a "Por Emitir" y ajuste visual para forzar el color naranja en facturas que no cuentan con emisión fiscal. (e4be327)
- **Lógica de Facturación:** Refactorización y centralización de la lógica de indicadores fiscales dentro de `sales_billing_indicators.js` para mejorar la consistencia del sistema. (ebcd55b)
- **Impuestos y Retenciones:** Se implementó una validación para prevenir retenciones de IVA en transacciones sin IVA y se corrigió un error que provocaba una doble conversión en el cálculo del IGTF. (34272a6)

---

## [v1.0.12] - 2026-04-24

### ✨ Funcionalidades (Features)
- Se implementó la capacidad de exportación a Excel para el Reporte de IVA (b788a99).
- Mejoras en la alineación fiscal y procesos de limpieza en las exportaciones relacionadas con la localización de Venezuela l10n_ve (6e4a4ae).

### 🐛 Correcciones (Fixes)
- Implementación de validaciones defensivas y manejo robusto de excepciones en los reportes de IVA y retenciones para asegurar la integridad del sistema ante datos inesperados (6edb571).

---

## [v1.0.11] - 2026-04-20

### 🐛 Correcciones (Fixes)
- Se restauró la función `_get_common_joins()` y se corrigió un error de sintaxis (coma faltante) en la definición de columnas dentro del módulo de libro de ventas (sales_book). [5e57b44]

---

## [v1.0.10] - 2026-04-20

### ✨ Funcionalidades (Features)
- **Integración de Notas de Débito:** Se ha incorporado completamente la Nota de Débito en el flujo fiscal, el Libro de Ventas y el flujo de pagos (063e305, a53d2bf).
- **Indicadores de Estado:** Implementación de indicadores compuestos {Fiscal} - {Pago} en la lista de Facturas de Venta y nuevos indicadores de estado "Anulado" para Notas de Crédito y Débito (1cb29a3, 9b6c874).
- **Cálculos Fiscales en Bs:** Adición de campos para visualizar el "Total Base + IVA (Bs)" en Facturas de Venta, Notas de Crédito y Notas de Débito (4b65a46, e30eb17).
- **Gestión de IGTF:** Incorporación del campo `is_igtf_applicable` en el Doctype Modo de Pago, con soporte para importación/exportación a nivel de sucursal (20385b3).
- **Validaciones de Cancelación:** Se añadió un bloqueo que impide la cancelación de Facturas de Venta si existen notas asociadas activas (9b6c874).

### 🐛 Correcciones (Fixes)
- **Estabilización de Documentos:** Se unificó la lógica de cancelación duplicada en Notas de Débito que impedía actualizar el estatus del documento padre y se corrigió la paridad de funciones entre NC y ND (5fae454, 428b300).
- **Optimización de Libro de Ventas:** Ahora se utilizan los valores de base imponible almacenados directamente en la factura para evitar inconsistencias por recalculos (9ff4ade).
- **Lógica Fiscal:** Eliminación del recálculo redundante de IVA en USD dentro del generador de payload y expansión de las validaciones de datos previas al envío fiscal (8123597).
- **Ajustes Contables y Montos:** Corrección del cálculo de montos pendientes (outstanding) en Notas de Crédito y solución a errores en las entradas de diario (GL Entry) relacionadas con retenciones (c785df3, 9b6c874).
- **Interfaz de Usuario:** Ajustes en la visibilidad de campos de IGTF y corrección en la visualización forzada de la columna de cliente en el listado de facturas (f668808, 33c80f2).

---

## [v1.0.9] - 2026-04-18

### ✨ Funcionalidades (Features)
- **Migración del Plan de Cuentas 2026:** Implementación de la nueva estructura contable con soporte para la consolidación (merge) de asientos contables (GL Entries). [fdd1a2c]

### 🐛 Correcciones (Fixes)
- **Libro de Ventas:** Se corrigió la doble conversión del IGTF, el manejo de documentos anulados del lado del cliente y la lógica condicional para el IVA retenido. [cd87b68]
- **Compatibilidad SQL:** Optimización de consultas para soportar el modo `ONLY_FULL_GROUP_BY` mediante el uso de agregaciones `MAX()` y estandarización de precisión decimal en el constructor de carga (payload builder). [04205e3]
- **Corte Fiscal:** Ajuste en la integración de datos legacy y nuevos esquemas mediante `UNION ALL`, mejorando el tratamiento de documentos marcados como anulados (void handling). [d0e78b0]
- **Validación Fiscal:** Mejora en la validación de montos para impresoras fiscales HKA y aplicación de reglas de unicidad para el número de factura (`bill_no`) basado en la serie. [ce9166e]

---

## [v1.0.8] - 2026-04-17

### ✨ Funcionalidades (Features)
- **l10n_ve**: Implementación de la migración del plan de cuentas 2026, incluyendo la funcionalidad de consolidación (merge) de asientos contables (GL Entries). (d7013f6)

### 🐛 Correcciones (Fixes)
- **sales_book**: Optimización en la generación del libro de ventas al utilizar los campos `base_*` almacenados directamente en la factura, eliminando la necesidad de realizar recalculaciones. (6ded34f)
- **sales_book**: Ajuste en el manejo de montos utilizando `base_tax_amount` y corrección de la lógica para asegurar que los montos se anulen correctamente en facturas marcadas como "void". (8a6dd23)

---

## [v1.0.7] - 2026-04-17

### ✨ Funcionalidades (Features)

* Mejora en el proceso de importación de extractos bancarios. 2b69f0a

### 🐛 Correcciones (Fixes)

* **Localización Fiscal (VE):** Ajuste integral en la metodología de recálculo de impuestos base en moneda nacional (VEF) y corrección de lógica en cálculos multi-tasa y retenciones. 15bc3c5, 3670185
* **Contabilidad:** Resolución de desbalances contables en retenciones de IVA y corrección del asiento faltante al proveedor en facturas de compra. 1985d3a, 563944c
* **Ventas:** Optimización de la validación de anticipos en Sales Invoice mediante el uso de grand_total base para mitigar errores por redondeo de decimales. 1985d3a
* **Controladores de Impuestos:** Eliminación de cálculos redundantes de vat_base para optimizar el procesamiento de transacciones. 563e605
* **Pagos:** Implementación de verificación de existencia de igtf_rate en la entrada de pagos para asegurar la integridad de los datos antes de actualizar facturas. edc0b16

---

## [v1.0.6] - 2026-04-16

### ✨ Funcionalidades (Features)
- Implementación de la anulación de Facturas de Venta a través del proveedor HKA utilizando un esquema de cancelación atómica. [6b7fc66]
- Mejora en la consistencia de los procesos de anulación para Notas de Crédito (NC) y facturas de reemplazo dentro del sistema. [d90d1e5]

### 🐛 Correcciones (Fixes)
- Integración de la función `to_currency` y lógica de cortocircuito para el manejo preciso de la tasa de cambio en facturas de reemplazo (módulo HKA). [724a309]
- Corrección de errores en la interfaz de usuario relacionados con el botón "Guardar" y ajuste en la agrupación del botón de reemplazo. [62d5254]

---

## [v1.0.5] - 2026-04-15

### ✨ Funcionalidades (Features)
- Implementación de una vista previa fiscal reutilizable diseñada para integrarse en Facturas de Venta (SI) y Notas de Crédito (NC). 082a97a
- Incorporación de vista previa inline para facturas fiscales HKA dentro del módulo de Sales Invoice, optimizando el flujo de revisión. 996cd39

---

## [v1.0.4] - 2026-04-15

### 🐛 Correcciones (Fixes)
- **l10n_ve**: Actualización del plan de cuentas BLACK con los datos definitivos validados por el equipo contable. [3083e9d]

---

## [v1.0.3] - 2026-04-13

### ✨ Funcionalidades (Features)
- Se añadió la columna Serie Fiscal al reporte del libro de ventas. 71d00f4

### 🐛 Correcciones (Fixes)
- Implementación de validación para evitar errores de división por cero en el cálculo de montos. 2515ce8
- Ajuste en la lógica del libro de ventas para recalcular el Total Incluido IVA a partir de los componentes fiscales. 71d00f4

---

## [v1.0.2] - 2026-04-13

### 🐛 Correcciones (Fixes)
- Se corrigió un error de recursión infinita que se presentaba al intentar registrar pagos desde el dashboard ISP. c792eee
- Optimización de la vista de lista en Sales Invoice mediante la eliminación de filtros redundantes y la configuración de columnas para mejorar la usabilidad. b197455
- Aplicación de mejoras técnicas y ajustes de estabilidad en parches tras revisión de código. f475da9

---

## [v1.0.1] - 2026-04-12

### ✨ Funcionalidades (Features)
- **Circuit Breaker y Resiliencia**: Implementación de patrón Circuit Breaker y un nuevo sistema de deduplicación para optimizar la gestión de errores. ccceaea
- **Optimización de Rendimiento**: Mejora en la velocidad de deduplicación de logs mediante el uso de campos indexados. 90252d8
- **Refactorización de Arquitectura**: Modularización del sistema de limpieza en 7 estrategias independientes y reestructuración integral del programador (scheduler). 6d5dc80, ccceaea

---

## [v1.0.0] - 2026-04-12

### 🐛 Correcciones (Fixes)

- Se corrigió el cálculo del **Total Incl. IVA** para asegurar la precisión en los reportes fiscales. [53be5cc]
- Modernización y actualización estructural del **Libro de Ventas**. [53be5cc]

---

## [v1.0.0-beta.3] - 2026-04-09

### ✨ Funcionalidades (Features)

- **Integración de Notas de Crédito (NC):** Se incorporó la gestión y soporte de notas de crédito dentro del módulo de libro de ventas (`sales_book`). [b15b2c5]
- **Filtros Fiscales:** Implementación de nuevos criterios de filtrado fiscal para mejorar la precisión de los reportes. [b15b2c5]
- **Optimizaciones de rendimiento:** Se aplicaron mejoras en la lógica del proceso de `sales_book` para optimizar el tiempo de respuesta. [b15b2c5]

---

## [v1.0.0-beta.2] - 2026-04-09

### 🐛 Correcciones (Fixes)

- Se ajustó el generador de carga útil (`payload_builder`) para procesar y dividir múltiples correos electrónicos dentro del arreglo de correos destinado a la integración con HKA. [2d1b3a4]

---

## [v1.0.0-beta.1] - 2026-04-08 (Lanzamiento Inicial Consolidado)

Esta versión recopila y estructura todo el trabajo histórico realizado en la localización venezolana (`l10n_ve`) desde la inicialización del proyecto en agosto de 2025 hasta la implementación del proceso de Changelog Automático.

### Added (Novedades)

- **Integración TFHKA (The Factory HKA):** Integración completa para facturación digital, notas de débito, crédito y numeración secuencial on-demand. Soporte de modo "Third Party". Inyección de RIF y manejo de estatus fiscal.
- **Sistema de Sucursales Múltiples (VE Branch):** Estructura NestedSet para manejo jerárquico de sucursales. Asignación obligatoria de transacciones (Sales, Purchase, Payment Entry, Delivery Note) a sucursales y herencia de permisos entre documentos.
- **Tasas de Cambio Oficiales:** Obtención automática de tasas BCV (Banco Central de Venezuela) y SENIAT. Inyección en los procesos de cálculo fiscal y asientos contables en multimoneda (VEF/USD).
- **Control de Metodos de Pago:** Configuración de modos de pago y predeterminados vinculados directamente por sucursal, con asignación automática en los Payment Entries y conciliación Bancamiga/BDV.
- **Libros Oficiales (Reporting):** Generación consolidada y exportable a TXT, CSV y Excel del Libro de Compras y Libro de Ventas adaptado a las providencias legales venezolanas. Filtros optimizados de facturas por fecha.
- **Comprobantes de Retención (IVA e ISLR):** Generación automática en PDF, trazabilidad nativa en el sistema de facturación y asignación de números de control seriales por operación. Opción de firma automatizada. Configuración individual o global desde cliente/proveedor.
- **Impuestos IGTF y Municipales:** Cálculos automáticos (1:1 y exentos) integrados directamente a facturas de venta y cobros. Incorporación del formulario Declaración de Impuestos Municipales y su validación contable.
- **Formatos CONATEL:** Implementación completa del sistema de declaración de impuestos CONATEL, filtrado jerárquico por sucursal y registro de totales por tipo de tráfico y actividad.
- **Adecuaciones al Core Contable de ERPNext:** Modificación/Inyección (Monkey Patching) de datos nativos para mostrar Identificadores (RIF, Cédula), Número de Control y Saldos consolidados VEF en "Balance Sheet", "Trial Balance", "Customer Ledger" y "Accounts Receivable".
- **Plantillas Fiscales:** Nuevos campos custom de "Tipo de Contribuyente" (Especial, Ordinario, Formal), Actividad Económica, Tipo de Documento, y representaciones dinámicas en Address e Invoice.
- **Sincronización Extractos Bancarios:** Optimización de lógica de parseo, saltándose referencias spam, lecturas HTML directas con validación unificada, soportando el importador en crudo.

### Refactored (Refactorizaciones Estructurales)

- Desacoplamiento de las lógicas front-end sobre los cálculos JS hacia validaciones contables unificadas de asientos backend.
- Reemplazo de métodos vulnerables a race-conditions (como `setTimeout` en sales) por promesas `frappe.after_ajax` para garantizar sincronía tras integraciones HKA.
- Refactor del `TaxesMixin` para el manejo de limpieza de las retenciones huérfanas en facturas de venta suspendidas temporalmente o anuladas (evita retenciones fantasmas en anulados).

### Fixed (Correcciones Notables)

- Problemas con el timezone y fechas fiscales. Se garantizó que la "fecha fiscal" se utilice para tasar en el BCV al momento preciso del pase a la imprenta digital.
- Solución al temido "solapamiento" de retenciones IVA e ISLR en facturas donde la moneda base y secundaria generaban redondeos inexactos en IGTF o anticipos.
- Manejo impecable de decimales flotantes al enviar JSON a The Factory para evadir errores de formato en montos grandes.
- Resolución de conflictos de validación en la tabla "Address" (múltiples teléfonos/correos formateados erróneamente en VEF).
- Corrección del autoarrendamiento del número de Control (`reference_no`) condicionado obligatoriamente ahora sólo si es diferente de "Cash".
