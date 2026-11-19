# Reintentos automáticos

AlegraPy reintenta solo las fallas transitorias, con espera exponencial y jitter, para que cada
aplicación no tenga que escribir sus propios bucles de reintento. La política por defecto hace
**2 reintentos** (3 intentos en total).

## Qué se reintenta

| Petición | Se reintenta cuando |
|---|---|
| `GET`, `PUT`, `DELETE`, `HEAD`, `OPTIONS` | Error de conexión, timeout, o un estado incluido en `retry_statuses` (por defecto `429`, `502`, `503`, `504`). |
| `POST`, `PATCH` y cualquier otro método | Solo `429`, o un error de conexión que demuestre que la petición **no se envió** (`ConnectTimeout`, DNS fallido, conexión rechazada). |
| Cualquier petición con `files` | Nunca: el flujo del archivo se consume en el primer intento. |

No se reintentan por defecto:

- `500`: en Alegra suele significar que el payload fue rechazado, no una falla temporal.
- `400`, `401`, `403`, `404`, `409`, `422` y demás estados fuera de `retry_statuses`.
- Errores de TLS/SSL, proxy o URL inválida.
- Errores de programación (por ejemplo, un payload que no se puede serializar a JSON).

## Por qué `POST` es especial

Un timeout o un `5xx` en un `POST` es ambiguo: la factura o el pago **pudo haberse creado** en
Alegra aunque el cliente no recibiera la respuesta. Reintentar a ciegas puede emitir una factura
DIAN duplicada.

Por eso un `POST` solo se repite cuando es seguro que nada llegó al servidor, o cuando Alegra
explícitamente pidió esperar (`429`).

`AlegraConnectionError` también es ambiguo: la conexión pudo cortarse después de que Alegra
procesara la petición. Usa `err.request_not_sent` para saber si es seguro repetir:

```python
except AlegraConnectionError as e:
    if e.request_not_sent:
        crear_de_nuevo()
    else:
        consultar_antes_de_crear()
```

!!! danger
    Nunca reintentes a mano un `POST` de facturas o pagos tras un `AlegraTimeoutError` o un
    `AlegraServerError`. Consulta el recurso antes de volver a crearlo.

## DELETE y el 404 en un reintento

- `DELETE` es idempotente, pero un reintento puede recibir `404` porque el primer intento ya borró
  el registro antes de fallar (por ejemplo, un timeout después de que Alegra procesó el borrado).

- `404` en el **primer** intento: se lanza `AlegraNotFoundError`, como siempre.
- `404` en un **reintento**: se considera éxito (`{}` más un `WARNING`) **solo si** el intento
  anterior pudo haber sido procesado por Alegra: `AlegraTimeoutError`, `AlegraConnectionError`
  con `request_not_sent == False`, o un `AlegraServerError` (5xx).
- Si el fallo anterior fue un `429` o una petición que no se envió (`request_not_sent == True`),
  el `404` es un “no existe” real y se lanza `AlegraNotFoundError`.
- `404` en un `GET`, `PUT` o `POST` reintentado sigue lanzando `AlegraNotFoundError`.

El estado `429` se controla con `retry_statuses` para todos los métodos: si lo quitas de la
política, ningún método reintenta un `429`.

## Cuánto se espera

1. Si la respuesta trae `Retry-After`, se respeta (incluido `0`).
2. En un `429` sin `Retry-After`, se usa `X-Rate-Limit-Reset` (segundos restantes de la ventana).
3. Si no hay indicación del servidor, se usa *full jitter*:
   `random.uniform(0, min(backoff_max, backoff_factor * 2 ** intento))`, con el intento empezando
   en 0.
4. Si el servidor pide una espera mayor que `max_retry_after` (60 s por defecto), no se reintenta:
   se lanza el error de inmediato.

Cada reintento deja un `WARNING` con el método, la ruta, el intento (`n/max`) y la espera; nunca
incluye cuerpos de respuesta, query strings ni credenciales.

## Configurar o desactivar

```python
from alegra import AlegraClient, RetryPolicy

client = AlegraClient(
    user="tu_usuario@dominio.com",
    token="tu_token_api",
    retry=RetryPolicy(max_retries=5, backoff_factor=1.0, backoff_max=20.0),
)

# Desactivar los reintentos por completo
client.retry = RetryPolicy(max_retries=0)
```

En el modo legacy, el cliente global usa `session.retry`:

```python
from alegra import RetryPolicy, session

session.retry = RetryPolicy(max_retries=0)
```

Si se agotan los reintentos, se lanza el error de la última tentativa, con su clase, atributos y
`__cause__` intactos.

## Ejemplo: sincronización por tenant

```python
from alegra import AlegraClient, RetryPolicy, AlegraNotFoundError, AlegraServerError

client = AlegraClient(
    user=tenant.alegra_user,
    token=tenant.alegra_token,
    timeout=15,
    retry=RetryPolicy(max_retries=3, backoff_factor=0.5),
)

try:
    factura = client.invoices.read(invoice_id)
except AlegraNotFoundError:
    marcar_como_eliminada(invoice_id)
except AlegraServerError as e:
    # Ya se agotaron los reintentos: Alegra sigue fallando
    registrar_para_reintento_posterior(invoice_id, e.status_code)
```
