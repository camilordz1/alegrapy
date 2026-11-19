# AlegraPy

AlegraPy es una librería de Python que simplifica el consumo de la API de [Alegra](https://www.alegra.com/), la plataforma de facturación y contabilidad. Se encarga de la autenticación, la construcción de las URL, la paginación y el manejo de errores, para que puedas concentrarte en tu integración.

Para conocer los campos de cada recurso (facturas, contactos, ítems, etc.) consulta la [documentación oficial de la API de Alegra](https://developer.alegra.com/).

## Ejemplo mínimo

```python
from alegrapy import AlegraClient

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")
contacto = client.contacts.read(10032)
print(contacto.get("name"))
```

## Por dónde empezar

- [Instalación](guias/instalacion.md): instala el paquete desde PyPI.
- [Autenticación](guias/autenticacion.md): obtén tus credenciales y configúralas de forma segura.
- [Guía rápida](guias/guia-rapida.md): leer, listar, crear, actualizar y eliminar registros.
- [Recursos disponibles](guias/recursos.md): tabla de recursos y métodos especiales.
- [Manejo de errores](guias/errores.md): cómo capturar `AlegraAPIError`.
- [Seguridad](guias/seguridad.md): HTTPS, validación de IDs, timeouts y logs.
- [Migración desde el modo legacy](guias/migracion-legacy.md): del estilo global a `AlegraClient`.
- [Referencia de la API](referencia/index.md): documentación generada a partir del código.
