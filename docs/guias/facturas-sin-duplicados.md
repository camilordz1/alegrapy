# Facturas sin duplicados

Crear una factura es una operación **no idempotente**. Si el `POST` falla de forma ambigua
(timeout, `5xx`, conexión cortada después de enviar), Alegra pudo haberla creado aunque tú
recibas un error. Reintentar sin más puede emitir una **factura DIAN duplicada**.

`create_once` resuelve ese caso con una clave de deduplicación:

```python
from alegrapy import AlegraClient

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

factura = client.invoices.create_once(datos, dedup_key=f"order-{order.id}")
```

## Cómo funciona

1. Añade una marca `alegrapy:dedup:<clave>` a `observations` (una línea propia; el campo admite
   hasta 500 caracteres).
2. Antes de crear, busca esa marca en las facturas del cliente. Si ya existe, devuelve esa
   factura y **no envía ningún POST**.
3. Si el POST falla de forma ambigua, busca la factura durante `verify_window` segundos
   (por defecto 30).
4. Si no la encuentra y `on_unverified="retry"` (por defecto), hace **un** POST más con la misma
   marca y vuelve a verificar. Nunca hace más de 2 POST.
5. Si sigue sin poder verificarla, lanza `AlegraUnverifiedCreateError`, que puedes guardar en una
   cola de cuarentena.

Tres resultados posibles:

| Resultado | Significado |
|---|---|
| Devuelve una factura con `id` ya existente | La clave ya se había usado; no se creó nada nuevo. |
| Devuelve una factura recién creada | El POST funcionó (a la primera o en el reintento verificado). |
| Lanza `AlegraUnverifiedCreateError` | No se pudo confirmar; **no vuelvas a crear a ciegas**. |

## Saber si se creó o ya existía

Por defecto `create_once` devuelve solo el registro. Si tu aplicación necesita distinguir una
creación nueva de un registro que ya existía (por ejemplo, para registrar «creada» frente a
«sin cambios»), pasa `with_outcome=True`:

```python
from alegrapy import AlegraClient, CreateOnceOutcome

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

factura, resultado = client.invoices.create_once(
    datos,
    dedup_key=f"order-{order.id}",
    with_outcome=True,
)

if resultado == CreateOnceOutcome.EXISTING:
    registrar("sin cambios", factura["id"])
elif resultado == CreateOnceOutcome.CREATED:
    registrar("creada", factura["id"])
else:
    # CreateOnceOutcome.RECOVERED: el registro existe, pero tras un POST ambiguo
    registrar("confirmada tras reintento", factura["id"])
```

`with_outcome=True` devuelve un `CreateOnceResult(record, outcome)` desempaquetable, donde
`outcome` es un `CreateOnceOutcome` (compatible con `str`, de modo que `resultado == "existing"`
funciona igual). Está disponible en los cuatro `create_once` del SDK (`invoices`, `payments`,
`income_debit_notes` e `inventory_adjustments`).

| Valor (`CreateOnceOutcome`) | Qué ocurrió | Qué reportar habitualmente |
|---|---|---|
| `CREATED` (`"created"`) | Un `POST` hecho por esta llamada respondió con éxito. Con `on_unverified="retry"` tras un primer `POST` sin verificar, el primer intento también pudo haber creado un documento. | Creada / aplicada. |
| `EXISTING` (`"existing"`) | Se encontró el documento antes de enviar ningún `POST` en esta llamada (precheck). | Sin cambios (ya existía). |
| `RECOVERED` (`"recovered"`) | Se encontró el documento durante la verificación posterior a un fallo ambiguo de `POST`. | Confirmada; **no asumas que fue nueva ni previa**. |

!!! note "Matiz sobre `recovered`"
    Cuando `outcome` es `CreateOnceOutcome.RECOVERED`, el SDK confirma que el documento existe en
    Alegra, pero no puede distinguir si lo creó el `POST` ambiguo de esta llamada o una llamada
    anterior que aún no aparecía en el listado. Si ocurre una excepción (`AlegraAPIError`,
    `AlegraUnverifiedCreateError`, etc.), se lanza igual en ambos modos sin devolver `outcome`.

## Elegir `on_unverified`

- `"retry"` (por defecto): reduce los duplicados sin intervención, pero **no los elimina**. Si
  Alegra tarda más que `verify_window` en mostrar la factura, el segundo POST puede duplicarla.
- `"raise"`: no hace el segundo POST; lanza el error inmediatamente después de la ventana. Úsalo
  junto con una cuarentena si necesitas flujo de **cero duplicados**.

```python
factura = client.invoices.create_once(
    datos,
    dedup_key=f"order-{order.id}",
    on_unverified="raise",
    verify_window=60,
)
```

## Patrón de cuarentena

`AlegraUnverifiedCreateError.to_dict()` devuelve un diccionario serializable (sin credenciales ni
cabeceras) con `dedup_key`, `client_id`, `resource`, `payload`, `attempts`, `status_code` y
`response_body`. Guárdalo en tu tabla de cuarentena:

```python
import json
from alegrapy import AlegraUnverifiedCreateError

try:
    factura = client.invoices.create_once(datos, dedup_key=key, on_unverified="raise")
except AlegraUnverifiedCreateError as err:
    guardar_en_cuarentena(json.dumps(err.to_dict()))
```

Un worker posterior puede reconciliar sin miedo:

```python
from alegrapy import AlegraClient

client = AlegraClient(user=..., token=...)

entrada = leer_entrada_de_cuarentena()
factura = client.invoices.reconcile(entrada["dedup_key"], entrada["client_id"])

if factura is not None:
    marcar_como_creada(factura)
else:
    # Pasado el periodo de cuarentena, la precheck protege el reintento:
    # si la factura aparece mientras tanto, create_once la devuelve.
    # Reconstruye los datos desde tu sistema (el pedido original), no desde
    # entrada["payload"]: ese payload ya pasó por to_dict() (los Decimal son texto).
    datos = construir_datos_de_factura(entrada["dedup_key"])
    factura = client.invoices.create_once(
        datos, entrada["dedup_key"], precheck=True, lookup_pages=10)
    marcar_como_creada(factura)
```

Dos cuidados en el worker:

- **Reconstruye el payload desde tu fuente de datos.** `err.to_dict()["payload"]` sirve para
  registrar y diagnosticar, pero sus valores ya están convertidos a tipos JSON (`Decimal` como
  texto, tuplas como listas), así que el POST no sería idéntico al original. La marca de
  deduplicación sale de la misma `dedup_key`, por lo que no hace falta reutilizar ese payload.
- **Amplía `lookup_pages` según la antigüedad de la cuarentena.** La búsqueda revisa solo las
  `lookup_pages × 30` facturas más recientes del cliente. Si entre el error y el reintento ese
  cliente recibió más facturas, la original puede quedar fuera de la ventana y crearse un
  duplicado.

Este patrón funciona con una tabla de base de datos, Celery, RQ, un cron o cualquier otra cola:
el SDK no crea hilos, workers ni colas.

## Cómo elegir la clave

La clave debe ser **estable** (la misma operación produce siempre la misma) y **única** por
operación de negocio. Hay dos ayudantes puros, sin I/O, que generan claves válidas para
`create_once`.

### `make_dedup_key`: cuando tienes un id de negocio

```python
from alegrapy import make_dedup_key

key = make_dedup_key("order", order.id)                    # "order:1234"
key = make_dedup_key("payment", operation_id,              # "billing:payment:op-9f2"
                     namespace="billing")
```

- Partes: textos (se recortan), enteros (sin `bool`) y `Decimal`; los números se comparan
  por valor (`1` y `Decimal("1")` son iguales).
- Forma legible si todas las partes usan solo letras, dígitos, `_`, `.` o `-` y el resultado
  cabe en 64 caracteres.
- En otro caso, forma con hash: `"h:"` + 40 caracteres hexadecimales.
- Los dos puntos son el separador y están prohibidos en las partes legibles, así que
  `("a:b", "c")` y `("a", "b:c")` no colisionan.
- `namespace` se antepone como primera parte para separar integraciones distintas.

### `make_dedup_key_from`: cuando no hay id y la unicidad es por contenido

```python
from alegrapy import make_dedup_key_from

key = make_dedup_key_from(
    datos,
    ["client.id", "items[].id", "items[].quantity", "external_reference"],
)
```

- **No hay campos por defecto**: tú eliges la lista. Una ruta mal escrita no pasa en
  silencio: lanza `ValueError` con la ruta.
- Un segmento que termina en `[]` recorre cada elemento de una lista
  (`"items[].id"`, `"items[].quantity"`).
- Las rutas duplicadas y una lista vacía lanzan `ValueError`.
- El orden de los elementos proyectados no importa; el orden de otras listas sí.
- `namespace` opcional (1–20 caracteres de letras, dígitos, `_`, `.`, `-`): entra en el hash y
  se antepone si cabe en 64 caracteres.

!!! warning "Elige campos realmente únicos"
    Si seleccionas solo campos que se repiten en ventas legítimas (por ejemplo, un cliente
    genérico de “consumidor final” con los mismos ítems), el SDK tratará dos ventas distintas
    como una sola y **la segunda factura no se creará**. Incluye siempre una referencia única
    de la operación (número de pedido, id de pago, referencia externa) cuando exista.

    Por la misma razón, incluir la fecha o un timestamp suele **romper** la deduplicación:
    cada payload genera una clave distinta y los reintentos vuelven a crear facturas.

### Canonicalización antes de calcular la clave

| Dato | Regla |
|---|---|
| Diccionarios | Claves ordenadas. |
| Textos | Se recortan espacios al inicio/fin. |
| Números (`int`, `float`, `Decimal`) | Se comparan por valor, sin exponente ni ceros finales (`21008.4 == 21008.40 == Decimal("21008.400")`, `-0 == 0`). |
| `bool` | Sigue siendo booleano; nunca se trata como número (`True` ≠ `1`). |
| Textos numéricos | Siguen siendo textos y nunca coinciden con un número: `"1"` ≠ `1`, `"21008.4"` ≠ `21008.4`. |
| Listas proyectadas con `[]` | Los campos de un mismo elemento se agrupan (el `id` de un ítem va con su propia `quantity`) y luego los elementos se ordenan por su JSON canónico: el orden original no importa, pero la correspondencia sí. |
| Otras listas | Conservan su orden. |
| `date` / `datetime` | `isoformat()`. |
| `None` | `null`. |

El hash incluye la selección de campos (ordenada) y el `namespace`, de modo que dos
selecciones distintas sobre el mismo payload nunca producen la misma clave.

## Requisitos y validaciones

- `dedup_key`: texto de 1 a 64 caracteres, solo letras, dígitos, `_`, `.`, `:` y `-`. Se
  normaliza quitando espacios al inicio/fin.
- El payload debe incluir el cliente: `{"client": {"id": 126}, ...}` o `{"client": 126, ...}`.
  Sin él no se puede acotar la búsqueda y se lanza `ValueError` antes de enviar nada.
- Si `observations` existentes más la marca superan 500 caracteres, se lanza `ValueError`.
- `verify_window` debe ser un número finito no negativo; `lookup_pages`, un entero ≥ 1.
- El payload original **no se modifica**: se envía una copia con la marca.

## `reconcile`

```python
client.invoices.reconcile(dedup_key, client_id, lookup_pages=2, date="2026-11-21")
```

Devuelve la factura cuya línea `observations` coincide exactamente con la marca, o `None`. Si indicas `date` (o si `params["date"]` está presente en `create_once`), el SDK consulta primero las facturas de ese día usando el filtro `date` del servidor (hasta `lookup_pages * 30` registros) y, si no la encuentra, recurre al barrido sin filtro de fecha sobre las más recientes del cliente (`order_field=id`, `order_direction=DESC`). Así se evita perder la factura en clientes con mucho volumen diario sin debilitar el comportamiento anterior. Ten en cuenta que, con `date`, cada búsqueda puede hacer hasta dos pasadas (día filtrado y luego ventana reciente), por lo que la ventana de verificación emite aproximadamente el doble de peticiones `GET` (Alegra limita a 150 peticiones por minuto). Los borradores y las facturas abiertas también cuentan, porque un borrador ya puede consumir un número DIAN.

## Medir la latencia del listado (`verify_window`)

Alegra no documenta cuánto tarda una factura recién creada en aparecer en `GET /invoices`. Para elegir un `verify_window` acorde con tu cuenta, el repositorio incluye la herramienta de mantenimiento `scripts/measure_list_latency.py`:

```bash
ALEGRA_USER=... ALEGRA_TOKEN=... python scripts/measure_list_latency.py \
  --yes-call-live-api --client-id <ID_CLIENTE> --item-id <ID_ITEM> --delete
```

La factura se crea con `paymentForm` `CASH` por defecto, que Alegra exige en Colombia; usa
`--payment-form CREDIT` si tu cuenta lo requiere.

Como referencia, una medición en una cuenta colombiana de producción (2026-11-22) mostró la
factura en el listado 2,9 segundos después del POST. Es una sola muestra: la latencia puede
variar con la carga de Alegra, así que el `verify_window` de 30 segundos por defecto deja margen.

!!! warning "Crea un documento real"
    Este script crea una factura real en estado `draft` en tu cuenta de Alegra para medir el tiempo hasta que aparece en `reconcile`. Usa `--delete` para eliminarla al terminar (o bórrala manualmente usando el `id` impreso).

## Limitaciones (importantes)

- `"retry"` reduce los duplicados, no los elimina.
- Dos procesos pueden usar la misma clave a la vez y ambos fallar la búsqueda previa. Serializa
  por clave (por ejemplo, una restricción única en la base de datos o un lock por pedido).
- Sin `date`, la búsqueda solo cubre las `lookup_pages * 30` facturas más recientes de ese
  cliente; con `date`, cubre hasta `lookup_pages * 30` facturas de ese día más la ventana reciente.
- No está verificado si Alegra envía `observations` al XML de la DIAN.
- Cuánto tarda una factura creada y perdida por timeout en aparecer en el listado no está
  documentado.

## Pagos sin duplicados

Para notas débito de cliente sin duplicados, consulta [Notas débito sin duplicados](notas-debito.md#notas-debito-sin-duplicados).

Registrar un pago (`client.payments`) dos veces es igual de riesgoso que duplicar una factura:
duplica el ingreso o el egreso de caja. `client.payments.create_once` y `client.payments.reconcile`
usan el mismo flujo y la misma marca en `observations` (campo que Alegra **no imprime** en el
comprobante):

```python
from alegrapy import AlegraClient, make_dedup_key_from

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

datos_pago = {
    "date": "2026-11-20",
    "bankAccount": {"id": 1},
    "paymentMethod": "transfer",
    "type": "in",
    "client": {"id": 126},
    "invoices": [{"id": 11742, "amount": 150000}],
}

key = make_dedup_key_from(
    datos_pago,
    ["type", "client.id", "invoices[].id", "invoices[].amount", "date"],
)
pago = client.payments.create_once(datos_pago, dedup_key=key)
```

### Cuarentena y reconciliación de pagos

El patrón de cuarentena es el mismo que en facturas, usando `on_unverified="raise"` y
`client.payments.reconcile`:

```python
import json
from alegrapy import AlegraUnverifiedCreateError

try:
    pago = client.payments.create_once(datos_pago, dedup_key=key, on_unverified="raise")
except AlegraUnverifiedCreateError as err:
    guardar_en_cuarentena(json.dumps(err.to_dict()))
```

Y en el worker de reconciliación:

```python
entrada = leer_entrada_de_cuarentena()
pago = client.payments.reconcile(
    entrada["dedup_key"],
    entrada["client_id"],
    type=entrada["payload"].get("type"),
    lookup_pages=5,
)

if pago is not None and pago.get("status") == "voided":
    # El pago existió y luego se anuló: decide en tu aplicación si se registra de nuevo
    # (con una dedup_key nueva) o si se cierra la entrada
    enviar_a_revision_manual(entrada, pago)
elif pago is not None:
    marcar_como_registrado(pago)
else:
    datos_pago = construir_datos_de_pago(entrada["dedup_key"])
    pago = client.payments.create_once(
        datos_pago, entrada["dedup_key"], precheck=True, lookup_pages=10
    )
    marcar_como_registrado(pago)
```

Particularidades de pagos frente a facturas:

- **`client` es opcional** (por ejemplo, pagos a categorías contables). Si no pasas `client` en el
  payload ni `client_id` en `reconcile`, la búsqueda revisa solo los `lookup_pages * 30` pagos más
  recientes de toda la empresa (filtrados por `type` si está presente). En cuentas con mucho
  movimiento, pasa `client` o aumenta `lookup_pages`.
- **Sin filtro de estado**: `reconcile` también devuelve pagos anulados (`status="voided"`) que
  lleven la marca; revisa `pago["status"]` según la lógica de tu aplicación.
- **Re-validación local**: cuando indicas `client_id` o `type`, el SDK los envía como filtros a
  Alegra y además vuelve a comprobarlos localmente (descartando registros con `client: null` o
  con otro `type`; un registro que no trae la clave `client` o `type` sí se acepta, para no perder un
  pago ya creado).
