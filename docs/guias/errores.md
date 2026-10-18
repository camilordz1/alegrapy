# Manejo de errores

## `AlegraAPIError`

Toda falla de la API o del transporte HTTP se reporta con `AlegraAPIError`. Sus atributos:

| Atributo | Descripción |
|---|---|
| `str(e)` | Mensaje de error. Si la respuesta es JSON con un campo `message`, se usa ese texto; si no, el cuerpo de la respuesta o `API error (Status N)`. |
| `status_code` | Código HTTP devuelto por la API, o `None` si no hubo respuesta. |
| `response_body` | Texto crudo de la respuesta, o `None` si no hubo respuesta. |

```python
from alegra import AlegraClient, AlegraAPIError

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

try:
    factura = client.invoices.read(123)
except AlegraAPIError as e:
    print("Mensaje:", e)
    print("Código HTTP:", e.status_code)
    print("Cuerpo:", e.response_body)
```

Se considera error cualquier respuesta que no sea 2xx.

## Errores de transporte

Si la petición falla antes de obtener respuesta (sin conexión, DNS, timeout, etc.), se lanza `AlegraAPIError` con `status_code=None`. La excepción original de `requests` queda encadenada en `__cause__`:

```python
try:
    client.invoices.list()
except AlegraAPIError as e:
    if e.status_code is None:
        print("Fallo de transporte:", type(e.__cause__).__name__)
```

El mensaje solo incluye el nombre de la clase del error (por ejemplo `HTTP request failed (ConnectTimeout)`), nunca la URL ni los parámetros, que podrían contener datos sensibles.

!!! warning
    Un timeout en un `POST` es ambiguo: el registro pudo haberse creado. Consulta [Seguridad](seguridad.md) antes de reintentar.

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
try:
    client.contacts.add_attachment(10032, "factura.pdf")
except FileNotFoundError:
    print("El archivo no existe")
except ValueError as e:
    print("Parámetro inválido:", e)
except AlegraAPIError as e:
    print(f"Alegra respondió {e.status_code}: {e}")
```
