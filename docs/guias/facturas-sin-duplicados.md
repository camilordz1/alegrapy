# Facturas sin duplicados

Crear una factura es una operación **no idempotente**. Si el `POST` falla de forma ambigua
(timeout, `5xx`, conexión cortada después de enviar), Alegra pudo haberla creado aunque tú
recibas un error. Reintentar sin más puede emitir una **factura DIAN duplicada**.

`create_once` resuelve ese caso con una clave de deduplicación:

```python
from alegra import AlegraClient

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
from alegra import AlegraUnverifiedCreateError

try:
    factura = client.invoices.create_once(datos, dedup_key=key, on_unverified="raise")
except AlegraUnverifiedCreateError as err:
    guardar_en_cuarentena(json.dumps(err.to_dict()))
```

Un worker posterior puede reconciliar sin miedo:

```python
from alegra import AlegraClient

client = AlegraClient(user=..., token=...)

entrada = leer_entrada_de_cuarentena()
factura = client.invoices.reconcile(entrada["dedup_key"], entrada["client_id"])

if factura is not None:
    marcar_como_creada(factura)
else:
    # Pasado el periodo de cuarentena, la precheck protege el reintento:
    # si la factura aparece mientras tanto, create_once la devuelve.
    factura = client.invoices.create_once(
        entrada["payload"], entrada["dedup_key"], precheck=True)
    marcar_como_creada(factura)
```

Este patrón funciona con una tabla de base de datos, Celery, RQ, un cron o cualquier otra cola:
el SDK no crea hilos, workers ni colas.

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
