# Concurrencia y ciclo de vida

`AlegraClient` está pensado para compartirse entre hilos. Esta página fija el contrato: qué es
seguro, qué no, y cómo cerrar clientes de forma determinista.

## Contrato de seguridad entre hilos

| Escenario | ¿Seguro? |
|---|---|
| Varios hilos envían peticiones a través de **un mismo** `AlegraClient`. | Sí. Cada petición construye su propio encabezado `Authorization` a partir del cliente por el que se envía; el pool de conexiones no guarda credenciales. |
| Varios clientes con credenciales distintas se usan **al mismo tiempo**. | Sí. Un cliente nunca toma las credenciales de otro. |
| Cambiar `user`, `token`, `url`, `timeout` o `retry` mientras otros hilos usan el cliente. | No. Configura primero y comparte después. |
| Varias cuentas (tenants) usando el `session` global o los recursos de módulo (`contacts()`, `invoices()`, …). | No. Son estado global del proceso: las credenciales se pisan entre tenants. Usa un `AlegraClient` por tenant. |
| Acceder por primera vez a `client.contacts`, `client.invoices`, `client.items`, etc. desde varios hilos. | Sí. Una primera carga concurrente puede crear dos objetos de recurso equivalentes y sin estado, ambos ligados al mismo cliente; es inofensivo. |

Cada cliente conserva **una** `requests.Session` para reutilizar conexiones. Como la API de
Alegra se autentica con un encabezado en cada petición y no necesita cookies, el cliente rechaza
todas las cookies: así el cookie jar —el único estado compartido que quedaba en el pool— no se
escribe nunca.

## Un cliente por tenant

Construye los clientes una sola vez, al arrancar, y compártelos entre los hilos de trabajo:

```python
from alegrapy import AlegraClient, RetryPolicy

_clients = {
    tenant.id: AlegraClient(
        user=tenant.alegra_user,
        token=tenant.alegra_token,
        timeout=15,
        retry=RetryPolicy(max_retries=3),
    )
    for tenant in tenants
}


def facturas_de(tenant_id):
    # Seguro: cada llamada toma el cliente de su tenant y no toca configuración
    return _clients[tenant_id].invoices.list()
```

No modifiques `client.user`, `client.token` ni `client.retry` después de repartir el cliente entre
hilos; si un tenant cambia de credenciales, crea un cliente nuevo y sustituye la entrada del
diccionario.

## Cerrar el cliente

Usa el cliente como contexto para liberar las conexiones al terminar:

```python
from alegrapy import AlegraClient

with AlegraClient(user="...", token="...") as client:
    facturas = client.invoices.list()
# close() se llamó al salir, también si el bloque lanzó una excepción
```

`close()` cierra la `requests.Session` y libera las conexiones del pool. Es idempotente y no
oculta excepciones. Después de `close()` el cliente no debe reutilizarse.

## Por qué no usar el `session` global con varios tenants

El `session` legacy guarda `user`, `token` y `url` en atributos de clase, compartidos por todo el
proceso. En una aplicación multi-tenant basta una petición concurrente para que un tenant use las
credenciales de otro. La migración a un cliente por instancia está en
[Migración desde el modo legacy](migracion-legacy.md).
