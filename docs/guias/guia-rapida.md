# Guía rápida

Todos los recursos comparten las mismas operaciones básicas. Los campos de cada recurso (qué enviar al crear o actualizar) están en la [documentación oficial de Alegra](https://developer.alegra.com/).

## Crear el cliente

```python
import os
from alegra import AlegraClient

client = AlegraClient(
    user=os.environ["ALEGRA_USER"],
    token=os.environ["ALEGRA_TOKEN"],
)
```

Los recursos se cargan de forma perezosa: `client.contacts`, `client.invoices`, etc. se importan la primera vez que los usas. Consulta la [lista completa](recursos.md).

## Leer un registro

```python
contacto = client.contacts.read(10032)
print(contacto.get("name"))
```

`read(id, **kwargs)` acepta parámetros de consulta adicionales como argumentos con nombre.

## Listar registros

`list(start=0, limit=30, **kwargs)` pagina de 0 en adelante y limita a 30 resultados por defecto (30 es el máximo según la documentación del método).

```python
# Primeros 30 contactos
contactos = client.contacts.list()

# Los siguientes 30
siguientes = client.contacts.list(start=30, limit=30)

# Filtros adicionales: cualquier kwarg se envía como parámetro de consulta
facturas = client.invoices.list(limit=5, order_direction="DESC")
```

Por defecto la lista se ordena con `order_direction="ASC"` y `order_field="id"`; puedes sobrescribirlos con kwargs. Los nombres y valores de los filtros disponibles para cada recurso están en la [documentación de Alegra](https://developer.alegra.com/).

## Crear un registro

`create(params, **kwargs)` envía `params` como cuerpo JSON (`POST`).

```python
nuevo = client.contacts.create({
    "name": "Cliente de prueba",
    "identification": "900123456",
})
print(nuevo.get("id"))
```

!!! warning
    Si una petición de creación expira (timeout), el registro pudo haberse creado. Verifica antes de reintentar. Ver [Seguridad](seguridad.md).

## Actualizar un registro

`update(id, params, **kwargs)` envía `params` como cuerpo JSON (`PUT`).

```python
client.contacts.update(10032, {"name": "Nuevo nombre"})
```

## Eliminar un registro

```python
client.contacts.delete(10032)
```

## Adjuntar un archivo

`add_attachment(id, file_path, field_name="file")` sube un archivo local con `multipart/form-data`.

```python
client.contacts.add_attachment(id=10032, file_path="ruta/al/archivo.pdf")
```

Si el archivo no existe se lanza `FileNotFoundError`.

## Acciones especiales

Algunos recursos agregan métodos propios:

```python
client.estimates.void(123)
client.estimates.send_email(
    id=123,
    emails=["cliente@dominio.com"],
    subject="Tu cotización",
    message="Adjuntamos la cotización solicitada.",
)

client.bank_accounts.transfer(
    from_id=1, to_id=2, amount=50000.0,
    date="2026-06-21", description="Transferencia de fondos",
)
```

## Manejar errores

```python
from alegra import AlegraAPIError

try:
    client.contacts.read(999999999)
except AlegraAPIError as e:
    print(e.status_code, e)
```

Más en [Errores](errores.md).
