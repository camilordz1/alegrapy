# Manejo de errores

## `AlegraAPIError`

Toda falla de la API o del transporte HTTP se reporta con `AlegraAPIError` o una de sus
subclases. El tipo base conserva estos atributos:

| Atributo | Descripción |
|---|---|
| `str(e)` | Mensaje de error. Si la respuesta es JSON con un campo `message`, se usa ese texto; si no, el cuerpo de la respuesta o `API error (Status N)`. |
| `status_code` | Código HTTP devuelto por la API, o `None` si no hubo respuesta. |
| `response_body` | Texto crudo de la respuesta, o `None` si no hubo respuesta. |
| `retry_after` | Segundos sugeridos por la cabecera `Retry-After`, o `None` si no está o no se puede interpretar. Nunca es negativo. |
| `request_not_sent` | `True` solo cuando es seguro que la petición no llegó a Alegra (timeout de conexión, conexión rechazada o DNS fallido). En cualquier otro error vale `False`. |

Se considera error cualquier respuesta que no sea 2xx.

## Jerarquía de excepciones

| Excepción | Se lanza cuando |
|---|---|
| `AlegraAuthError` | La API responde 401 o 403 (credenciales inválidas o sin permiso). |
| `AlegraNotFoundError` | La API responde 404 (el recurso no existe). |
| `AlegraValidationError` | La API responde 400 o 422 (datos rechazados). |
| `AlegraRateLimitError` | La API responde 429 (límite de peticiones alcanzado). |
| `AlegraServerError` | La API responde cualquier 5xx (falla del lado de Alegra). |
| `AlegraConnectionError` | La petición no llegó a Alegra: `requests.ConnectionError` o `requests.ConnectTimeout`. |
| `AlegraTimeoutError` | La petición pudo llegar, pero no hubo respuesta a tiempo: `requests.ReadTimeout` u otro `requests.Timeout`. |
| `AlegraAPIError` | Cualquier otro código no 2xx (405, 409, …) o cualquier otro fallo inesperado. |

Todas las subclases heredan de `AlegraAPIError`, así que un `except AlegraAPIError` sigue
capturando cualquier error de la librería.

!!! note
    `ConnectTimeout` se reporta como `AlegraConnectionError`, no como timeout: la conexión no
    llegó a establecerse, por lo que la petición no se envió. `AlegraTimeoutError` es ambiguo y
    no debes reintentar un `POST` no idempotente a ciegas.

## Separar "no existe" de "Alegra está caído"

```python
from alegra import (
    AlegraClient,
    AlegraNotFoundError,
    AlegraServerError,
    AlegraRateLimitError,
)

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

try:
    factura = client.invoices.read(123)
except AlegraNotFoundError:
    print("La factura no existe en Alegra")
except AlegraServerError as e:
    print(f"Alegra está fallando ({e.status_code}); reintenta más tarde")
except AlegraRateLimitError as e:
    print(f"Límite de peticiones alcanzado; espera {e.retry_after} s")
```

`retry_after` acepta tanto delta-seconds (`Retry-After: 30`) como fechas HTTP
(`Retry-After: Wed, 21 Oct 2015 07:28:00 GMT`); si la fecha ya pasó, vale `0.0`.

## Errores de transporte

Si la petición falla antes de obtener respuesta (sin conexión, DNS, timeout, etc.), se lanza
`AlegraConnectionError` o `AlegraTimeoutError` con `status_code=None`. La excepción original de
`requests` queda encadenada en `__cause__`:

```python
from alegra import AlegraConnectionError, AlegraTimeoutError

try:
    client.invoices.list()
except AlegraConnectionError as e:
    print("No se pudo conectar:", type(e.__cause__).__name__)
except AlegraTimeoutError as e:
    print("Sin respuesta a tiempo:", type(e.__cause__).__name__)
```

`AlegraConnectionError` no garantiza que la petición no se haya enviado: la conexión pudo cortarse
después de que Alegra procesara un `POST`. Pregunta siempre por `request_not_sent` antes de
reintentar una creación:

```python
except AlegraConnectionError as e:
    if e.request_not_sent:
        # Seguro: la petición no salió del cliente
        reintentar_creacion()
    else:
        # Pudo haberse creado: consulta el recurso antes de repetir
        registrar_para_revision()
```

El mensaje solo incluye el nombre de la clase del error (por ejemplo
`HTTP request failed (ConnectTimeout)`), nunca la URL ni los parámetros, que podrían contener
datos sensibles.

Si la política de [reintentos](reintentos.md) está activa, la excepción que recibes es la de la
**última tentativa**, con su clase, atributos y `__cause__` intactos. Los reintentos nunca
envuelven un `POST` ambiguo ni cambian el tipo de error.

!!! warning
    Un timeout en un `POST` es ambiguo: el registro pudo haberse creado. No repitas la creación
    a menos que `e.request_not_sent` sea `True`. Consulta [Seguridad](seguridad.md) antes de
    reintentar.

## Errores de programación

Solo los fallos de red de `requests` se envuelven en excepciones de AlegraPy. Cualquier otro
error de Python se propaga sin cambios, para no ocultar el bug real. Por ejemplo, un payload con
un `Decimal` o un `datetime` que no se puede serializar a JSON lanza `TypeError` tal cual:

```python
from decimal import Decimal
from alegra import AlegraAPIError

try:
    client.invoices.create({"total": Decimal("100.00")})
except TypeError as e:
    # No es un error de Alegra: el payload no se pudo serializar
    print("Payload inválido:", e)
except AlegraAPIError as e:
    print("Alegra respondió con un error:", e)
```

## `ValueError`

Se lanza `ValueError` antes de enviar cualquier petición cuando:

- El ID de un recurso no es válido (véase [Seguridad](seguridad.md#validacion-de-ids)).
- La URL base no es `https://` (salvo `http://` para `localhost`, `127.0.0.1` o `::1`), no tiene host, o incluye credenciales.

```python
try:
    client.contacts.read("../users")
except ValueError as e:
    print("ID inválido:", e)
```

## `FileNotFoundError`

`add_attachment` lanza `FileNotFoundError` si el archivo local no existe.

## Ejemplo completo

```python
from alegra import (
    AlegraAPIError,
    AlegraAuthError,
    AlegraNotFoundError,
    AlegraServerError,
)

try:
    client.contacts.add_attachment(10032, "factura.pdf")
except AlegraAuthError:
    print("Revisa tus credenciales")
except AlegraNotFoundError:
    print("El contacto no existe")
except AlegraServerError:
    print("Alegra está fallando; reintenta más tarde")
except AlegraAPIError as e:
    print(f"Error de Alegra ({e.status_code}): {e}")
except FileNotFoundError:
    print("El archivo no existe")
except ValueError as e:
    print("Parámetro inválido:", e)
```
