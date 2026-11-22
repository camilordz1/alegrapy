# AlegraPy

[![Tests](https://github.com/camilordz1/alegrapy/actions/workflows/tests.yml/badge.svg)](https://github.com/camilordz1/alegrapy/actions/workflows/tests.yml)

Cliente de Python para la API de [Alegra](https://www.alegra.com/) (facturación y contabilidad).
Permite trabajar con varias empresas a la vez, maneja errores y reintentos de forma segura y
evita facturas duplicadas por reintentos ciegos.

> **Proyecto no oficial.** AlegraPy es una librería comunitaria, sin relación con Alegra.
> La referencia oficial de la API está en <https://developer.alegra.com/>.

**Documentación completa:** <https://camilordz1.github.io/alegrapy/>

## Inicio rápido

1. Instala el paquete desde PyPI (se importa como `alegrapy`):

   ```bash
   pip install AlegraPy
   ```

   Hasta la 1.0 se recomienda fijar la serie: `pip install "AlegraPy>=0.4,<0.5"`.

2. Obtén tus credenciales en Alegra: **Configuración → API - Integraciones con otros sistemas**
   (correo y token).

3. Crea un cliente y consulta:

   ```python
   import os
   from alegrapy import AlegraClient

   with AlegraClient(user=os.environ["ALEGRA_USER"], token=os.environ["ALEGRA_TOKEN"]) as client:
       contacto = client.contacts.read(126)
       print(contacto["name"])
   ```

Probado en Python 3.10, 3.11, 3.12 y 3.13.

## Qué incluye

| Necesidad | Cómo se resuelve | Guía |
|---|---|---|
| Varias empresas en el mismo proceso | Un `AlegraClient` por empresa; se puede compartir entre hilos sin mezclar credenciales | [Concurrencia](https://camilordz1.github.io/alegrapy/guias/concurrencia/) |
| Distinguir el tipo de error | Excepciones tipadas: `AlegraNotFoundError`, `AlegraAuthError`, `AlegraRateLimitError`, `AlegraServerError`, `AlegraTimeoutError`... Todas heredan de `AlegraAPIError` | [Errores](https://camilordz1.github.io/alegrapy/guias/errores/) |
| Fallas transitorias | Reintentos automáticos con backoff y `Retry-After`; un `POST` solo se reintenta si la petición seguro no salió | [Reintentos](https://camilordz1.github.io/alegrapy/guias/reintentos/) |
| Recorrer todos los registros | `iter_all()` pagina sola, sin cargar todo en memoria | [Paginación](https://camilordz1.github.io/alegrapy/guias/paginacion/) |
| Buscar por NIT o SKU | `contacts.find_by_identification()` e `items.find_by_reference()` con coincidencia exacta | [Búsquedas](https://camilordz1.github.io/alegrapy/guias/busquedas/) |
| Emisión electrónica (DIAN) | `invoices.stamp()`, `stamp_status()` y `wait_until_stamped()` con estados tipados | [Emisión DIAN](https://camilordz1.github.io/alegrapy/guias/emision-dian/) |
| Conexiones seguras | HTTPS obligatorio, IDs validados y logs sin cuerpos ni tokens | [Seguridad](https://camilordz1.github.io/alegrapy/guias/seguridad/) |

## Ejemplos

Los ejemplos siguientes usan un cliente abierto. Créalo sin `with` (y llama a `client.close()`
al terminar) o escribe el código dentro del bloque `with` del inicio rápido:

```python
import os
from alegrapy import AlegraClient

client = AlegraClient(user=os.environ["ALEGRA_USER"], token=os.environ["ALEGRA_TOKEN"])
```

Recorrer todo el inventario activo:

```python
for item in client.items.iter_all(status="active"):
    print(item["id"], item["name"])
```

Buscar un cliente por identificación (devuelve una lista: puede haber duplicados):

```python
contactos = client.contacts.find_by_identification("900.559.088")
```

Manejar errores por tipo:

```python
from alegrapy import AlegraNotFoundError, AlegraServerError

try:
    factura = client.invoices.read(11742)
except AlegraNotFoundError:
    factura = None
except AlegraServerError:
    ...  # Alegra no está disponible: reintenta más tarde
```

## Antes de crear facturas o pagos

Un timeout o una conexión cortada al crear un registro es **ambiguo**: la factura pudo crearse
en Alegra aunque recibas un error. El SDK nunca reintenta ese caso por su cuenta. Antes de volver
a crear, revisa `err.request_not_sent`:

```python
from alegrapy import AlegraAPIError

try:
    client.invoices.create(datos)
except AlegraAPIError as err:
    if err.request_not_sent:
        ...  # seguro: la petición nunca llegó a Alegra, puedes reintentar
    else:
        ...  # márcala como "pendiente de verificar"; no la crees otra vez a ciegas
```

Para facturas y pagos, `client.invoices.create_once(datos, dedup_key=...)` y
`client.payments.create_once(datos, dedup_key=...)` automatizan esa verificación y ofrecen una
cuarentena serializable; ver
[Facturas sin duplicados](docs/guias/facturas-sin-duplicados.md).

## Recursos disponibles

| Recurso | Propiedad | Operaciones extra |
|---|---|---|
| Facturas de venta | `client.invoices` | `void`, `open`, `send_email`, `annul`, `stamp`, `stamp_status`, `wait_until_stamped`, `get_pdf`, `download_pdf`, `get_xml`, `download_xml` |
| Notas crédito | `client.credit_notes` | `annul` en `client.invoices` |
| Contactos | `client.contacts` | `find_by_identification`, `add_attachment` |
| Productos / ítems | `client.items` | `find_by_reference`, `add_attachment` |
| Pagos | `client.payments` | `create_once`, `reconcile`, `void`, `open` |
| Cotizaciones | `client.estimates` | `void`, `open`, `send_email` |
| Órdenes de compra | `client.purchase_orders` | `send_email`, `add_comment` |
| Cuentas bancarias | `client.bank_accounts` | `transfer` |
| Impuestos, monedas, retenciones | `client.taxes`, `client.currencies`, `client.retentions` | — |
| Usuarios | `client.users` | `self_info` |

Todos tienen `list`, `read`, `create`, `update`, `delete` e `iter_all`. El detalle está en la
[guía de recursos](https://camilordz1.github.io/alegrapy/guias/recursos/).

## Modo legacy

El estilo antiguo con la sesión global (`from alegrapy import session`) sigue disponible, pero
comparte credenciales en todo el proceso: no lo uses con varias empresas. Ver
[Migración desde el modo legacy](https://camilordz1.github.io/alegrapy/guias/migracion-legacy/).

## Desarrollo

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q

pip install -r requirements-docs.txt
mkdocs serve
```

## Versiones y cambios

Consulta [CHANGELOG.md](CHANGELOG.md) y la guía de [Versiones y cambios](docs/guias/versiones.md) (política de Semantic Versioning y qué esperar antes de `1.0.0`). Se recomienda fijar `AlegraPy>=0.1,<0.2`.

## Licencia

MIT. Ver [LICENSE.txt](LICENSE.txt).
