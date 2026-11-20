# Migración desde el modo legacy

AlegraPy conserva el estilo anterior (credenciales globales y clases en minúscula) por compatibilidad. Para código nuevo se recomienda `AlegraClient`.

## Nombre del import

El paquete se importa como `alegrapy`; el antiguo `alegra` sigue disponible como alias de
compatibilidad con un `FutureWarning`:

```python
from alegrapy import AlegraClient

# Sigue funcionando, pero emite un aviso y se eliminará en 1.0:
from alegra import AlegraClient
```

El **logger** conserva el nombre `"alegra"` en la serie 0.1.x, para que tu configuración de
logging siga funcionando: configura `logging.getLogger("alegra")`, no `"alegrapy"`.

Si tus tests parchean el SDK, hazlo sobre el objeto del módulo
(`importlib.import_module("alegrapy.invoices")` + `patch.object`), no con rutas en texto como
`"alegra.invoices.time"`: `alegra.invoices` es el alias legacy de la clase, no el módulo.

## Comparación

=== "Recomendado: AlegraClient"

    ```python
    from alegrapy import AlegraClient

    client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

    facturas = client.invoices.list(start=0, limit=5)
    contacto = client.contacts.read(10032)
    ```

=== "Legacy"

    ```python
    from alegrapy import session, invoices, contacts

    session.user = "tu_usuario@dominio.com"
    session.token = "tu_token_api"

    facturas = invoices().list(start=0, limit=5)
    contacto = contacts().read(10032)
    ```

Los alias en minúscula (`invoices`, `contacts`, `payments`, `items`, `estimates`, `purchase_orders`, `bank_accounts`, `taxes`, `currencies`, `retentions`, `users`, `actions`) apuntan a las clases con nombre en mayúscula (`Invoices`, `Contacts`, etc.). Cuando se instancian sin cliente, usan un cliente global (`default_client`) que lee las credenciales de `session`.

## Equivalencias

| Legacy | Recomendado |
|---|---|
| `session.user = "..."` | `AlegraClient(user="...")` |
| `session.token = "..."` | `AlegraClient(token="...")` |
| `session.timeout = 10` | `AlegraClient(timeout=10)` |
| `session.url = "..."` | `AlegraClient(url="...")` |
| `invoices().list()` | `client.invoices.list()` |
| `users().self_info()` | `client.users.self_info()` |

También puedes pasar un cliente a un recurso legacy: `Invoices(client)`.

## Por qué migrar

- **Varias cuentas a la vez**: cada `AlegraClient` tiene sus credenciales; `session` es global y compartido por todo el proceso.
- **Menos riesgo de mezclar credenciales** en aplicaciones concurrentes o con varios usuarios. Ver [Concurrencia y ciclo de vida](concurrencia.md).
- **Configuración explícita** de URL y timeout por instancia.

## Cuándo el estilo legacy aún tiene sentido

- Scripts pequeños con una sola cuenta que ya usan `session`.
- Código existente que no quieres tocar: sigue funcionando igual.

## Notas de compatibilidad

- Un cliente que define su propio `user` o `token` ignora por completo las credenciales de `session` (ver [Autenticación](autenticacion.md#resolucion-de-credenciales-por-par)).
- Las validaciones de [Seguridad](seguridad.md) (HTTPS, IDs, timeout) aplican igual en el modo legacy.
