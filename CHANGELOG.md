# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
