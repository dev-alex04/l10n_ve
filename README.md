# 🇻🇪 l10n_ve - Localización Venezolana para ERPNext

La aplicación **l10n_ve** es una robusta solución desarrollada sobre el **Frappe Framework**, diseñada para adaptar **ERPNext** y cumplir estrictamente con el marco legal, tributario y fiscal de Venezuela. 

Esta aplicación intercepta el flujo estándar de ERPNext para inyectar cálculos de impuestos (IVA, ISLR, IGTF, Municipales, CONATEL), generar comprobantes de retención legales, estructurar libros fiscales y gestionar integraciones con Impresoras Fiscales (ej. The Factory HKA).

---

## 🏗 Arquitectura y Flujos Fiscales

La arquitectura de `l10n_ve` se basa en la interceptación del ciclo de vida de los documentos contables nativos (`Sales Invoice`, `Purchase Invoice`, `Payment Entry`) mediante *overrides (monkey patching)* para aplicar la normativa legal antes y después de asentar los registros en el Libro Mayor (`General Ledger`).

### Diagrama de Flujo: Facturación y Retenciones

```mermaid
graph TD
    subgraph Ciclo de Facturación (Ventas/Compras)
        INV[Invoice / Factura] --> |Calcula Totales| T[Taxes and Totals Controller]
        T --> |Aplica| IGTF[Impuesto IGTF 3%]
        T --> |Determina| TFHKA{Facturación Electrónica TFHKA?}
        TFHKA -- Sí --> API[API TFHKA Client]
        API --> |Devuelve Nro Control| INV
        TFHKA -- No --> L[Serie Lógica/Manual]
    end

    subgraph Ciclo de Pago y Retenciones
        PE[Payment Entry] --> |Detecta Agente Retención| WH{Requiere Retención?}
        WH -- ISLR --> ISLR[ISLR Withholding Voucher]
        WH -- IVA --> IVA[VAT Withholding Voucher]
        ISLR -.-> |Asiento Contable| GL[General Ledger]
        IVA -.-> |Asiento Contable| GL
    end

    subgraph Libros Fiscales Obligatorios
        INV --> SB[Libro de Ventas / Compras]
        ISLR --> SB
        IVA --> SB
    end
```

---

## ⚙️ Características y Funcionalidades

### 1. Gestión Integral de Impuestos y Retenciones
*   **Retenciones de IVA:** Generación automática de *Comprobantes de Retención de IVA* (`VAT Withholding Voucher`) tanto para clientes como para proveedores. Configurable al 75% o 100% legal, generando sus asientos contables paralelos.
*   **Retenciones de ISLR:** Control de comprobantes vinculados a cuentas de compras (`ISLR Withholding Voucher`). Configuración atada a un **Tabulador de ISLR** (`Tabulator ISLR Aliquots`) que almacena la matriz legal del SENIAT (Códigos de retención, Sustraendos y porcentajes P. Natural/P. Jurídica).
*   **Unidad Tributaria (U.T.):** Doctype nativo (`Tax Unit`) para trazar históricamente la U.T. utilizada en cálculos de sustraendos y patentes.

### 2. Informes Legales y Fiscales
*   **Libro de Ventas y Compras:** Reportes oficiales adaptados a las providencias legales del SENIAT. Extraen datos estructurados (Fecha, RIF, Nombre, Nro Control, Factura, Exentas, Imponible, IVA y Monto Retenido), exportables vía Excel avanzados.
*   **Cruces de Retención:** Vistas para facilitar auditorías (`vat_withholding`, `islr_withholding`), agrupando las declaraciones emitidas periódicamente.
*   **Gestión IGTF:** Panel detallado de los cobros en moneda extranjera y liquidación de percepciones (`igtf_received`).

### 3. Contabilidad Bimonetaria
*   **Plan de Cuentas Localizado:** Carga inicial mediante plantillas (`ve_plan_de_cuentas`) adaptadas a la NIIF/VEN-NIF.
*   **Tasa de Cambio Oficial Automatizada:** Uso de un *cron job* que extrae directamente la referencial del BCV (Banco Central de Venezuela) para calcular paridad cambiaría al registrar transacciones extranjeras.

### 4. Adaptaciones Regionales
*   **Geopolítica Venezolana:** DocTypes nativos para registrar la estructura territorial oficial de **Estados, Ciudades, Municipios y Parroquias**, exigida para encabezados fiscales y comprobantes.
*   **Catálogo de Entidades:** Campos obligatorios incorporados en `Customer` y `Supplier` correspondientes a la denominación fiscal y Registro de Información Fiscal (**RIF**), además del tipo de contribuyente (Especial vs Ordinario).

### 5. Impuestos Municipales y Especiales (CONATEL)
*   **Patentes y Actividad Económica:** Orquesta declaraciones a nivel de Alcaldía a través de doctypes (`VE Municipality Tax Declaration`) asociados a tarifas pre-cargadas por jurisdicción.
*   **Fondo Especial de Telecomunicaciones:** Estructuras y liquidación integrados a facturación para tributos de CONATEL (FSU).

### 6. Facturación Electrónica e Integración HKA
*   **Servicio TFHKA:** Integración nativa asíncrona hacia The Factory HKA para obtención e inyección de series alfanuméricas legalizadas para Notas de Crédito, Notas de Débito y Facturas Electrónicas (`VE Digital Billing Series`), respaldado por un historial de transacciones seguro (`VE Digital Invoice Log`).

---

## 🛠 Sobrescrituras (Overrides) del Núcleo de ERPNext

Para inyectar estas reglas, esta app utiliza `hooks.py` y una estructura profunda de Override de Clases que altera el estándar:

| Módulo ERPNext Estándar | Comportamiento Inyectado por l10n_ve |
| :--- | :--- |
| **`Sales` / `Purchase Invoice`** | Valida series fiscales, inyecta la lógica y el cálculo IGTF, define topes para exenciones y procesa la llamada asíncrona a la API TFHKA antes de que el documento alcance el Submit. |
| **`Payment Entry`** | Modifica la recepción de divisas y detecta instantáneamente si el cruce de facturas exige originar (y vincular retroactivamente) `Vouchers` de retención (IVA/ISLR). |
| **`Customer` / `Supplier`** | Introduce validación asertiva para exigir el formato `V-XXXX` o `J-XXXX` en los RIFs, auto-asignando perfiles tributarios. |
| **`Company` / `Address`** | Sobrescribe las validaciones de dirección para obligar la subdivisión territorial requerida por los libros contables. |

---

## 💻 Instalación y Configuración

Requisitos: Servidor con **Frappe Framework** (v14 o v15) y **ERPNext** ya inicializados.

```bash
# Descargar la aplicación desde el repositorio
bench get-app https://github.com/grupo-altia/l10n_ve.git

# Instalar la aplicación en su sitio de producción
bench --site tusitio.local install-app l10n_ve

# Ejecutar las migraciones (creación de Doctypes y Custom Fields)
bench --site tusitio.local migrate
```

### Configuración Post-Instalación
Al culminar, ERPNext cargará pasivamente los *Fixtures* requeridos (Plan de Ventas, Estados de Venezuela, Tax Aliquots y Bancaturas).

Recomendaciones Iniciales:
1.  **Configurar la Compañía:** Ingresar a `Configuración > Compañía` y llenar la pestaña "Localización Venezolana" (RIF, Retenedor IVA).
2.  **Tabuladores Reales:** Revisar `Contabilidad > Impuestos > Tabulador ISLR` para validar las tarifas actualizadas con el estado macroeconómico del país.

---

## 📄 Licencia y Mantenimiento

Software propietario/privado mantenido integralmente por **Grupo Altia**. Para más información sobre distribución o alteraciones a esta rama, favor consultar el archivo `license.txt`.
