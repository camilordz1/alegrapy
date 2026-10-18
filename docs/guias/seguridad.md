# Seguridad

AlegraPy aplica varias protecciones por defecto. Esta página explica qué hace la librería y qué te corresponde a ti.

## Solo HTTPS

La URL base (`AlegraClient(url=...)`) debe usar `https://`. Solo se permite `http://` para `localhost`, `127.0.0.1` y `::1`, pensado para pruebas locales. Se lanza `ValueError` cuando:

- el esquema no es `https` (o `http` en un host de loopback),
- la URL no tiene host,
- la URL incluye credenciales incrustadas (`usuario:clave@host`).

Los mensajes de error no incluyen la URL completa, porque podría contener secretos. La URL por defecto es `https://api.alegra.com/api/v1/`.

```python
AlegraClient(url="http://api.ejemplo.com/")      # ValueError
AlegraClient(url="http://localhost:8000/api/")   # permitido (pruebas locales)
```

La URL también se valida en cada petición, incluso cuando proviene de la configuración global `session.url`; si no es válida no se envía nada.

## Validación de IDs

Antes de colocar un ID en la ruta de la petición se valida. Un ID válido es:

- un entero no negativo (incluidos los enteros de numpy; `bool` queda excluido), o
- una cadena con letras, dígitos, `_` y `-`.

Cualquier otro valor (por ejemplo `"1/2"`, `"a.b"` o `"x?y=1"`) lanza `ValueError`, para que un ID no pueda alterar la ruta ni la consulta.

```python
client.contacts.read(10032)      # correcto
client.contacts.read("abc-123")  # correcto
client.contacts.read("../users") # ValueError
```

## Timeout

Cada petición tiene un timeout por defecto de **30 segundos**. Puedes cambiarlo por cliente:

```python
client = AlegraClient(user="...", token="...", timeout=10)
client.timeout = 15   # también se puede modificar después
```

En modo legacy se configura globalmente con `session.timeout = 10`. Un cliente sin timeout propio usa el de `session`.

## Reintentos en `POST`

!!! warning "Un timeout en un POST es ambiguo"
    Si una operación que crea registros (por ejemplo una factura o un pago) expira, Alegra pudo haberla procesado aunque el cliente lance un error. **No reintentes a ciegas**: consulta primero si el registro existe (por ejemplo, con `list` y un filtro adecuado) para no duplicarlo.

## Credenciales por par

Un cliente nunca mezcla su `user` con el `token` global. Si define `user` o `token`, se usa solo su propio par y una mitad faltante implica que no se envía autenticación. Las credenciales globales de `session` solo se usan cuando el cliente no define ninguna. Además, las credenciales se agregan en cada petición y no se guardan en la `requests.Session` compartida. Ver [Autenticación](autenticacion.md#resolucion-de-credenciales-por-par).

## Logs

La librería usa un logger llamado `alegra`. Registra:

- **INFO**: método, ruta y código de estado de las peticiones exitosas.
- **WARNING**: método, ruta y código de estado de las respuestas con error.
- **ERROR**: método, ruta y el nombre de la clase de la excepción cuando la petición falla.

La ruta se registra sin host y **sin parámetros de consulta**. Nunca se registran tokens, encabezados ni cuerpos de petición o respuesta. El mensaje de la API puede contener datos de usuario, por lo que permanece solo en la excepción: `AlegraAPIError` conserva `status_code` y `response_body` para que tu aplicación los inspeccione.

Para ver los logs:

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("alegra").setLevel(logging.INFO)
```

Sin configuración, Python solo muestra por `stderr` los mensajes WARNING y superiores.

## Manejo de credenciales

- Guarda el usuario y el token en variables de entorno o en un archivo `.env`.
- Agrega `.env` a tu `.gitignore` y nunca subas credenciales al repositorio.
- Si un token se expone, genera uno nuevo desde **Configuración > API - Integraciones** en Alegra.
- Evita imprimir el token o el resultado de `get_auth_header()` en logs o trazas.
