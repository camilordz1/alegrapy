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
client.invoices.reconcile(dedup_key, client_id, lookup_pages=2)
```

Devuelve la factura cuya línea `observations` coincide exactamente con la marca, o `None`. Busca
en las facturas más recientes del cliente (`order_field=id`, `order_direction=DESC`), sin filtro
de estado: los borradores y las facturas abiertas también cuentan, porque un borrador ya puede
consumir un número DIAN.

## Limitaciones (importantes)

- `"retry"` reduce los duplicados, no los elimina.
- Dos procesos pueden usar la misma clave a la vez y ambos fallar la búsqueda previa. Serializa
  por clave (por ejemplo, una restricción única en la base de datos o un lock por pedido).
- La búsqueda solo cubre las `lookup_pages * 30` facturas más recientes de ese cliente.
- No está verificado si Alegra envía `observations` al XML de la DIAN.
- Cuánto tarda una factura creada y perdida por timeout en aparecer en el listado no está
  documentado.
