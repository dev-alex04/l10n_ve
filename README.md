# Localización Venezolana para ERPNext (l10n_ve)

Esta aplicación adapta ERPNext para cumplir con los requisitos contables, fiscales y legales de Venezuela. Proporciona las funcionalidades necesarias para que las empresas que operan en Venezuela puedan gestionar sus procesos administrativos de acuerdo con la normativa local.

## Características Principales

### 1. Gestión de Impuestos y Retenciones

-   **Retenciones de IVA:**
    -   Creación y gestión de **Comprobantes de Retención de IVA** tanto para clientes como para proveedores.
    -   Configuración de porcentajes de retención de IVA según la normativa del SENIAT.
    -   Formatos de impresión para los comprobantes de retención.
-   **Retenciones de ISLR (Impuesto Sobre la Renta):**
    -   Generación automática de **Comprobantes de Retención de ISLR** en facturas de compra.
    -   **Tabulador de ISLR** para configurar los conceptos de retención, porcentajes y bases aplicables a personas naturales y jurídicas.
-   **Gestión de Unidad Tributaria (U.T.):**
    -   DocType para registrar el valor histórico de la Unidad Tributaria, utilizado en cálculos fiscales.

### 2. Informes Legales y Fiscales

-   **Libro de Ventas:** Reporte que genera el libro de ventas en el formato requerido por el SENIAT, detallando las transacciones, impuestos y datos del cliente.
-   **Libro de Compras:** Reporte que genera el libro de compras siguiendo la estructura exigida por la normativa fiscal venezolana.
-   Exportación de reportes a formatos como Excel para su posterior declaración.

### 3. Plan de Cuentas Localizado

-   Incluye un **Plan de Cuentas estándar para Venezuela**, que puede ser instalado durante la configuración inicial de la empresa.
-   Estructura contable adaptada a las prácticas y requerimientos locales.

### 4. Adaptaciones Regionales

-   **Direcciones y Geografía:**
    -   DocTypes para gestionar la división político-territorial de Venezuela: **Estados, Ciudades, Municipios y Parroquias**.
    -   Plantilla de dirección adaptada al formato venezolano.
-   **Información de Entidades (Clientes, Proveedores, Empresa):**
    -   Campos personalizados para registrar información fiscal como el **RIF (Registro de Información Fiscal)** y la denominación fiscal.
    -   Clasificación del tipo de contribuyente (Ordinario, Especial).

### 5. Gestión de Múltiples Monedas

-   **Tasa de Cambio Automatizada:** Tarea programada (`cron job`) que consulta y registra automáticamente la tasa de cambio del BCV (Banco Central de Venezuela) para operaciones en moneda extranjera.
-   Modificaciones en transacciones de compra y venta para reflejar correctamente los montos en la moneda local (Bolívares) y en divisas.

### 6. Modificaciones a DocTypes Estándar

La aplicación extiende y personaliza los siguientes DocTypes de ERPNext para incorporar la lógica de negocio venezolana:

-   **Factura de Venta y Factura de Compra:** Lógica para el cálculo automático de retenciones de IVA e ISLR.
-   **Cliente y Proveedor:** Campos para información fiscal y configuración de retenciones.
-   **Empresa:** Configuración de datos fiscales de la compañía.
-   **Ítem:** Adaptaciones para la gestión de impuestos por producto.
-   **Entrada de Pago:** Mejoras en la gestión de pagos en múltiples monedas.

## Instalación

1.  Asegúrate de tener `frappe-bench` instalado.
2.  Descarga la aplicación en el directorio `apps` de tu bench:
    ```bash
    git clone [URL_DEL_REPOSITORIO] apps/l10n_ve
    ```
3.  Instala la aplicación en tu sitio:
    ```bash
g   bench --site [nombre_del_sitio] install-app l10n_ve
    ```
4.  Ejecuta las migraciones para aplicar los cambios en la base de datos:
    ```bash
    bench --site [nombre_del_sitio] migrate
    ```

## Uso

Una vez instalada, la aplicación se integrará con los módulos de Contabilidad, Compras y Ventas de ERPNext. Se recomienda realizar las siguientes configuraciones iniciales:

1.  **Configurar la Compañía:** Ve a `Configuración > Compañía` y completa los datos fiscales de tu empresa en la pestaña "Localización Venezolana".
2.  **Configurar Clientes y Proveedores:** En cada cliente y proveedor, especifica su RIF y el tipo de contribuyente.
3.  **Configurar el Tabulador de ISLR:** Ve a `Contabilidad > Impuestos > Tabulador ISLR` y configura los conceptos de retención que apliquen a tu negocio.
