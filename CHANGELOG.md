# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
