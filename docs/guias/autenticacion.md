# Autenticación

La API de Alegra usa autenticación básica con tu correo electrónico y un token. AlegraPy arma el encabezado `Authorization` por ti en cada petición.

## Obtener tus credenciales

1. Ingresa a la aplicación de [Alegra](https://app.alegra.com/).
2. Ve a **Configuración** (esquina superior derecha) y selecciona **API - Integraciones**.
3. Copia tu **correo electrónico** de acceso y genera o copia tu **token**.

## Guardar las credenciales fuera del código

No escribas el token directamente en tu código ni lo subas al repositorio. Usa variables de entorno:

```bash
export ALEGRA_USER="tu_usuario@dominio.com"
export ALEGRA_TOKEN="tu_token_api"
```

```python
import os
from alegrapy import AlegraClient

client = AlegraClient(
    user=os.environ["ALEGRA_USER"],
    token=os.environ["ALEGRA_TOKEN"],
)
```

### Usar un archivo `.env`

El script `main.py` del repositorio carga las credenciales con [`python-decouple`](https://pypi.org/project/python-decouple/), que lee un archivo `.env` o las variables de entorno. Esta librería no es una dependencia de AlegraPy; instálala aparte si quieres usarla:

```bash
pip install python-decouple
```

```ini
# .env  (agrégalo a tu .gitignore)
ALEGRA_USER=tu_usuario@dominio.com
TOKEN=tu_token_api
```

```python
from decouple import config
from alegrapy import AlegraClient

client = AlegraClient(
    user=config("ALEGRA_USER"),
    token=config("TOKEN"),
)
```

!!! note
    Los nombres de las variables (`ALEGRA_USER`, `TOKEN`, `ALEGRA_TOKEN`) son una convención de tu aplicación; AlegraPy no lee variables de entorno por su cuenta.

## Verificar las credenciales

```python
yo = client.users.self_info()
print(yo.get("email"), "-", yo.get("name"))
```

Si las credenciales son incorrectas, se lanza un [`AlegraAPIError`](errores.md).

## Varios clientes con credenciales distintas

Cada `AlegraClient` conserva sus propias credenciales, por lo que puedes trabajar con varias cuentas a la vez:

```python
cliente_a = AlegraClient(user="a@dominio.com", token="token_a")
cliente_b = AlegraClient(user="b@dominio.com", token="token_b")
```

## Resolución de credenciales por par

Las credenciales se resuelven **como un par** `(user, token)`:

- Si el cliente define `user` o `token`, se usa únicamente su propio par. Una mitad faltante implica que no se envía autenticación: el cliente nunca completa su `user` con el `token` global (ni al revés).
- Si el cliente no define ninguno, se usan las credenciales globales del objeto `session` (modo [legacy](migracion-legacy.md)).

```python
from alegrapy import AlegraClient, session

session.user = "global@dominio.com"
session.token = "token_global"

solo_user = AlegraClient(user="mio@dominio.com")
solo_user.get_auth_header()   # "" -> no se mezcla con el token global
```

Esto evita enviar por error un token de otra cuenta. Más detalles en [Seguridad](seguridad.md).
