# `workspace_injection` — links de l10n_ve dentro de workspaces ajenos

## Para qué existe esta carpeta

Los workspaces **Accounting**, **Financial Reports**, **Selling** y **Buying** pertenecen a
ERPNext. l10n_ve necesita colgar cosas suyas adentro (Unidad Tributaria, Libro de Ventas,
Notas de Crédito/Débito, etc.).

**Frappe no ofrece ningún mecanismo para extender el workspace de otra app.** El `.json` de
un Workspace vive en la carpeta de su dueño, y dos apps no pueden declarar el mismo archivo.
La única vía es modificar el documento en la base después de que ERPNext lo importó. Eso es
lo que hace esta carpeta.

No busques una forma declarativa "oficial" de hacerlo: no existe. Si encontrás una, es
porque la versión de Frappe cambió, y entonces conviene migrar a ella.

## Cómo está armado

| Archivo | Qué es |
|---|---|
| `__init__.py` | El reconciliador. `apply_all()` es el punto de entrada. Su docstring documenta la gramática completa del manifiesto y los invariantes. **Leelo antes de tocar el código.** |
| `accounting.json` | Manifiesto del workspace `Accounting` |
| `financial_reports.json` | Manifiesto del workspace `Financial Reports` |
| `selling.json` | Manifiesto del workspace `Selling` |
| `buying.json` | Manifiesto del workspace `Buying` |

Está cableado en `l10n_ve/hooks.py`, en `after_migrate`:

```python
"l10n_ve.workspace_injection.apply_all",
```

Corre en **cada** `bench migrate`, y tiene que hacerlo: `sync_all()` reimporta los workspaces
desde el JSON de ERPNext (con `delete` + `insert` de todas las filas hijas) **antes** de los
hooks `after_migrate`, así que cuando ERPNext publica un JSON nuevo se pierde todo lo
inyectado y este hook lo repone en la misma corrida. Cuando no hay nada que reponer, no
guarda nada.

## Los cambios más comunes

**Agregar un link a una tarjeta que ya existe** → una línea en el array `links` de esa
tarjeta, en el manifiesto correspondiente. El orden del array es el orden en pantalla.

**Agregar un acceso directo** → una entrada en `shortcuts`.

**Renombrar algo que ya está en producción** → cambiá el `label` y poné el label viejo en
`aliases`. Sin el alias, el reconciliador no reconoce la fila existente y crea una segunda
al lado.

**Un workspace destino nuevo** → un `.json` más en esta carpeta. `load_manifests()` levanta
todos los de la carpeta; no hay que registrarlo en ningún lado.

`link_to` es sensible a mayúsculas y tiene que coincidir con el nombre real del DocType o
Report. Hay casos que parecen erratas y no lo son: `Sales book`, `purchase_book`,
`VAT report`, `IGTF received`. Verificalos contra la base antes de asumir.

## La trampa número uno al probar

**Nunca ejecutes `apply_all()` sin `frappe.flags.in_migrate = True`.**

Con `developer_mode` encendido, `Workspace.on_update()` re-exporta el workspace al `.json`
de la app dueña. Fuera de un migrate ese flag no está puesto, así que cada corrida escribe
los links venezolanos **dentro de los JSON de ERPNext**, en `apps/erpnext/`. Y eso no se
queda en tu máquina: el archivo cambia de hash, así que **los demás sites del bench lo
reimportan en su próxima migración** — incluidos los que no tienen l10n_ve instalada.

Ya pasó una vez (2026-08-02): cuatro JSON de ERPNext contaminados y cuatro de los cinco
sites del bench a punto de heredarlo.

Dentro del módulo, todo guardado va envuelto en el helper `no_file_export()`. Si agregás un
`save()` nuevo, envolvelo también.

```python
import frappe
frappe.init(site='local.domina.galanet'); frappe.connect()
frappe.flags.in_migrate = True          # <-- imprescindible
from l10n_ve.workspace_injection import apply_all
apply_all()                              # o apply_all(dry_run=True)
frappe.db.commit()
```

Al terminar, comprobá que no ensuciaste nada:

```bash
git -C /home/frappe/frappe-bench/apps/erpnext status --short   # tiene que salir vacío
```

## El invariante que no se puede debilitar

**Sólo se borra lo que se declara.** La clave de propiedad sale del manifiesto. Todo lo
demás —de ERPNext o puesto a mano por el usuario— es intocable.

Esto no es prolijidad: el predecesor deduplicaba por `(type, link_to, label)` sin mirar bajo
qué tarjeta estaba la fila, y **le borró a ERPNext un link propio** — el `accounting.json`
original trae `Accounting Dimension` dos veces a propósito, bajo *Cost Center and Budgeting*
y bajo *Accounting Masters*, y se comió el segundo.

Corolario incómodo pero correcto: este módulo **tampoco repone** lo que no declara. Si un
link de ERPNext se perdió, se repara solo cuando `import_file` reimporte el JSON, no acá.

## Mecánica de los Workspace de Frappe que hay que respetar

Tres cosas que no son obvias y que rompen en silencio:

1. **Las tarjetas salen de recorrer la tabla `links` por `idx`**, abriendo una tarjeta nueva
   en cada fila `type='Card Break'` (`workspace.py::get_link_groups`). El campo `link_count`
   **no agrupa nada**. Por eso el Card Break tiene que quedar contiguo y *antes* de sus
   links, y los `idx` renumerados 1..N: Frappe carga las hijas con `order_by="idx asc"`
   **sin criterio de desempate**, así que dos filas con el mismo `idx` hacen la agrupación
   no determinista.
2. **Una tarjeta sin links se descarta** (`desk/desktop.py::get_links`, `if new_items:`). Un
   Card Break mal ubicado no se ve "vacío": se vuelve invisible. Así estuvo *Reportes
   Venezuela* durante meses.
3. **Un `link_count` mentiroso destruye datos.** `clean_up()` (`desk/desktop.py:603`) hace
   `del links[i : i + link_count + 1]` cuando el usuario guarda el workspace desde la UI. Si
   el valor está inflado, se lleva filas ajenas por delante.

Y hay **tres** representaciones que deben ir sincronizadas: la tabla `links`, la tabla
`shortcuts` y el campo JSON `content` (bloques `card`/`shortcut`). Ojo: el `data.links`
inline dentro de un bloque `card` **no se renderiza** — el front resuelve por label contra
`get_link_groups()`. Escribirlo sólo ensucia el JSON y dispara re-imports.

## Lo que este módulo no puede hacer

**No puede retirar lo que él mismo creó.** Si sacás una declaración del manifiesto, esa fila
deja de ser "nuestra" y sobrevive en la base para siempre. Cerrarlo pediría una lista
`retired` en el manifiesto. El código imperativo anterior tenía la misma limitación.

**La identidad de una tarjeta es su label.** Si el usuario la renombra desde la UI a algo que
no está en `aliases`, la próxima migración crea una segunda.

**No pisa las preferencias del usuario** en lo que es suyo: `col` y `place` se aplican sólo
al crear, y los campos opcionales de los accesos directos (`color`, `doc_view`,
`stats_filter`) no se normalizan. Dentro de una tarjeta propia, en cambio, el orden de los
links lo manda el manifiesto siempre — es lo que garantiza que se vea igual en todos los
sites.

## Verificar que quedó bien

Lo que hay que mirar es `plan["changed"]` y el campo `modified` del workspace. **`tabVersion`
no sirve como prueba de "no escribí"**: `version.py::get_diff` itera `new.meta.fields` y
`idx` no es campo de meta, así que un cambio de sólo-`idx` no deja fila aunque el documento
se haya guardado.

La prueba de idempotencia es: correr `apply_all()` dos veces seguidas y que la segunda dé
`plan["changed"]` vacío y `modified` sin moverse en los cuatro workspaces.

Para ver el resultado como lo ve el usuario, `get_link_groups()` es el mismo método que
alimenta la pantalla:

```python
frappe.get_doc("Workspace", "Accounting").get_link_groups()
```

## De dónde salió esto

Reemplazó ~700 líneas imperativas en `l10n_ve/setup.py` (PR l10n_ve#524), que tenían cuatro
defectos medidos: le borraba un link a ERPNext, duplicaba las Notas de Crédito/Débito de
Ventas en cada migración, agrupaba en tarjetas de forma no determinista por empates de `idx`,
y dejaba la tarjeta *Reportes Venezuela* invisible con sus reportes colgando de una tarjeta
de ERPNext.
