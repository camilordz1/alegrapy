# Webhooks

`client.webhooks` administra suscripciones en `/webhooks/subscriptions` y `parse_webhook` convierte el cuerpo recibido en un `WebhookEvent` tipado. La aplicación es dueña del endpoint HTTP y de la cola de procesamiento.

## Administrar suscripciones

- Cada suscripción escucha **un solo evento** (`WebhookEventType`: `new-invoice`, `edit-invoice`, `delete-invoice`, `new-bill`, `edit-bill`, `delete-bill`, `new-client`, `edit-client`, `delete-client`, `new-item`, `edit-item`, `delete-item`).
- Máximo **10 suscripciones por evento** y por empresa; no se permiten combinaciones repetidas de evento y URL.
- Alegra exige la `url` **sin esquema** (`https://` se recorta automáticamente por comodidad; `http://` se rechaza), en dominio público sobre puerto 443 y con un máximo de 1024 bytes.
- Al crear (`create`) o actualizar (`update`), Alegra envía un `POST {}` de prueba a `https://<url>` y exige un `2xx` en menos de 5 segundos; si falla, la operación es rechazada.

```python
from alegrapy import AlegraClient, WebhookEventType

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

sub = client.webhooks.create(
    WebhookEventType.NEW_INVOICE,
    "mi-dominio.com/webhooks/alegra/<token-secreto>",
)
todas = client.webhooks.list()
```

### Reactivar una suscripción suspendida

Alegra suspende una suscripción (`status == "SUSPENDED"`) tras 5 eventos distintos fallidos durante al menos 1 hora, y **no reenvía** los eventos perdidos mientras estuvo suspendida. Para reactivarla y reiniciar el contador de fallos, llama a `update` (incluso con la misma URL):

```python
client.webhooks.update(sub["id"], sub["url"])
```

## Seguridad y manejo de entregas

!!! warning "No hay firma criptográfica"
    Alegra **no envía firma, secreto ni cabecera personalizada** en las entregas: cualquiera en internet podría hacer `POST` a tu URL si la conoce.

Sigue estas cuatro reglas en tu receptor:

1. **Token secreto en la ruta de la URL**: genera un token aleatorio largo en la URL registrada y compáralo en tiempo constante (`hmac.compare_digest`) antes de procesar el cuerpo.
2. **Nunca confíes ciegamente en el payload**: usa `event.fetch(client)` para releer el recurso desde la API de Alegra (en eventos `delete-*` devuelve `None`; en `bill` lanza `NotImplementedError` hasta que exista ese recurso).
3. **Deduplica por `(event.type, event.resource_id)`**: Alegra puede repetir entregas o enviarlas fuera de orden.
4. **Responde `2xx` rápido (< 10 s)** y encola el trabajo en segundo plano.

### Ejemplo agnóstico de framework

```python
import hmac
from alegrapy import AlegraClient, AlegraNotFoundError, AlegraWebhookError, parse_webhook

def manejar_webhook(token_recibido: str, token_esperado: str, raw_body: bytes, client: AlegraClient):
    if not hmac.compare_digest(token_recibido, token_esperado):
        return 403

    try:
        event = parse_webhook(raw_body)
    except AlegraWebhookError:
        return 400

    try:
        recurso = event.fetch(client)
    except AlegraNotFoundError:
        recurso = None

    procesar_en_segundo_plano(event.type.value, event.resource_id, recurso)
    return 200
```
