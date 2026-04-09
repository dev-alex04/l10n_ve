# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
