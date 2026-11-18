# AlegraPy

[![Tests](https://github.com/camilordz1/alegrapy_pkg/actions/workflows/tests.yml/badge.svg)](https://github.com/camilordz1/alegrapy_pkg/actions/workflows/tests.yml)

Este paquete nos permite consumir la API de la plataforma de facturación [Alegra](https://www.alegra.com/) de forma sencilla mediante Python 🐍.

📚 **Documentación**: <https://camilordz1.github.io/alegrapy_pkg/>. Para verla en local: `pip install -r requirements-docs.txt && mkdocs serve`.

## Características

- **Modular y Extensible**: Soporta múltiples recursos de la API de Alegra.
- **Cliente Orientado a Objetos (`AlegraClient`)**: Permite instanciar múltiples clientes con diferentes credenciales simultáneamente.
- **Carga Perezosa (Lazy loading)**: Los recursos solo se importan e instancian cuando se acceden por primera vez.
- **Operaciones Avanzadas**: Anulación de documentos, reabrir documentos, envío por correo electrónico, agregar comentarios y transferencias bancarias.
- **Carga de Archivos Adjuntos**: Soporte integrado para adjuntar archivos (`multipart/form-data`) a cualquier recurso que lo admita.

---

## Instalación y Configuración

### 1. Obtener credenciales de acceso
Sigue estos pasos para obtener tus credenciales desde tu cuenta de Alegra:
- Ingresa a la aplicación de [Alegra](https://app.alegra.com/).
- Dirígete a **Configuración** (esquina superior derecha) y selecciona **API - Integraciones**.
- Copia tu **Correo electrónico** de acceso y genera/copia tu **Token**.

### 2. Instalación
Para instalar el paquete de forma local en tu entorno virtual:
```bash
pip install .
```

---

## Uso Recomendado (`AlegraClient`)

El uso del objeto `AlegraClient` es la forma recomendada para interactuar con la API:

```python
from alegra import AlegraClient

# Inicializar cliente con tus credenciales
client = AlegraClient(
    user="tu_usuario@dominio.com", 
    token="tu_token_api"
)

# 1. Listar Clientes/Contactos (con paginación por defecto: start=0, limit=30)
contactos = client.contacts.list()

# 2. Consultar un Contacto específico
contacto = client.contacts.read(10032)
print("Contacto:", contacto.get("name"))

# 3. Adjuntar un archivo local a un contacto o factura
client.contacts.add_attachment(id=10032, file_path="ruta/al/archivo.pdf")
```

---

## Recursos Disponibles y Métodos Especiales

| Recurso | Propiedad del Cliente | Acciones Especiales |
|---|---|---|
| **Facturas de Venta** | `client.invoices` | `.void(id)`, `.open(id)`, `.send_email(id, emails, ...)` |
| **Contactos** | `client.contacts` | `.add_attachment(id, file_path)` |
| **Productos/Ítems** | `client.items` | `.add_attachment(id, file_path)` |
| **Pagos/Ingresos** | `client.payments` | `.void(id)`, `.open(id)` |
| **Cotizaciones** | `client.estimates` | `.void(id)`, `.open(id)`, `.send_email(id, emails, ...)` |
| **Órdenes de Compra** | `client.purchase_orders` | `.void(id)`, `.send_email(id, emails, ...), .add_comment(id, comment_text)` |
| **Cuentas Bancarias** | `client.bank_accounts` | `.transfer(from_id, to_id, amount, date, description)` |
| **Impuestos** | `client.taxes` | CRUD estándar (`list`, `read`, `create`, `update`, `delete`) |
| **Monedas/Divisas** | `client.currencies` | CRUD estándar |
| **Retenciones** | `client.retentions` | CRUD estándar |
| **Usuarios** | `client.users` | `.self_info()` (Consultar usuario autenticado) |

### Ejemplo: Registrar una Transferencia Bancaria
```python
client.bank_accounts.transfer(
    from_id=1,           # Cuenta origen
    to_id=2,             # Cuenta destino
    amount=50000.0,      # Monto
    date="2026-06-21",   # Fecha (AAAA-MM-DD)
    description="Transferencia de fondos"
)
```

### Ejemplo: Anular y Enviar Cotización por Correo
```python
# Anular cotización
client.estimates.void(123)

# Enviar cotización a un cliente
client.estimates.send_email(
    id=123,
    emails=["cliente@dominio.com"],
    subject="Tu cotización actualizada",
    message="Hola, adjuntamos la cotización de los servicios solicitados."
)
```

---

## Compatibilidad Heredada (Legacy Mode)

Se mantiene la compatibilidad con el estilo de configuración global y los wrappers de funciones heredados:

```python
from alegra import session, invoices, contacts

# Configuración global de la sesión
session.user = "tu_usuario@dominio.com"
session.token = "tu_token_api"

# Instanciación heredada
invoice_helper = invoices()
invoice_list = invoice_helper.list(start=0, limit=5)
```

---

## Seguridad

- **HTTPS obligatorio**: la URL base debe usar `https://`. Solo se permite `http://` para `localhost`, `127.0.0.1` y `::1` (pruebas locales). Las URLs con credenciales incrustadas (`usuario:clave@host`) se rechazan con `ValueError`.
- **Validación de IDs**: los IDs deben ser enteros no negativos (incluidos los enteros de numpy) o cadenas con letras, dígitos, `_` y `-`. Cualquier otro valor lanza `ValueError` antes de enviar la petición.
- **Timeout**: cada petición tiene un timeout por defecto de 30 segundos. Se configura con `AlegraClient(timeout=...)` o, en modo heredado, con `session.timeout`.
- **Cuidado con los reintentos en `POST`**: un timeout en una operación que crea registros (por ejemplo, una factura o un pago) es ambiguo, ya que el registro pudo haberse creado en Alegra aunque el cliente lance un error. No reintentes a ciegas; consulta primero si el registro existe.
- **Credenciales por par**: un cliente nunca mezcla su `user` con el `token` global. Si el cliente define `user` o `token`, se usa solo su propio par (una mitad faltante implica que no se envía autenticación); las credenciales globales de `session` se usan solo cuando el cliente no define ninguna.
- **Logs seguros**: los logs registran únicamente el método, la ruta (sin parámetros de consulta) y el código de estado. Nunca incluyen cuerpos de respuesta ni tokens. `AlegraAPIError` conserva `status_code` y `response_body` para que tu aplicación pueda inspeccionarlos.
- **Manejo de credenciales**: guarda tu usuario y token en variables de entorno o en un archivo `.env`, y nunca los subas al repositorio.

```python
import os
from alegra import AlegraClient

client = AlegraClient(
    user=os.environ["ALEGRA_USER"],
    token=os.environ["ALEGRA_TOKEN"],
    timeout=10,
)
```

---

## Referencias Oficiales
- **Documentación de la API de Alegra**: https://developer.alegra.com/

## Licencia
Este proyecto está bajo la Licencia **MIT**.
