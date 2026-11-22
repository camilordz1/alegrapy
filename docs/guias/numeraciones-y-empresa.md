# Numeraciones y empresa

Para emitir facturación electrónica (DIAN) necesitas elegir la numeración vigente de tu empresa y consultar sus datos tributarios. AlegraPy ofrece `client.number_templates` y `client.company` para ambos casos.

## Numeraciones (`client.number_templates`)

`GET /number-templates` requiere el tipo de documento (`document_type`):

```python
from alegrapy import AlegraClient

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

numeraciones = client.number_templates.list(document_type="invoice")
```

Los tipos de documento admitidos son `invoice`, `estimate`, `transactionIn`, `transactionOut`, `creditNote`, `debitNote` e `incomeDebitNote`. También puedes paginar con `iter_all(document_type=...)` o usar `read(id)`, `create(params)`, `update(id, params)` y `delete(id)`.

### Elegir la numeración para facturación electrónica

`default(document_type="invoice")` devuelve la primera numeración que tenga `isDefault` en `True` y `status == "active"`, o `None`:

```python
plantilla = client.number_templates.default("invoice")
if plantilla is not None:
    print(plantilla["id"], plantilla.get("prefix"), plantilla.get("resolutionNumber"))
```

!!! warning "Validez DIAN"
    `default()` refleja únicamente la numeración marcada como preferida y activa en Alegra; **no** valida la resolución ante la DIAN. Antes de usarla en una factura electrónica, verifica manualmente los campos:

    - `isElectronic`: que corresponda a facturación electrónica.
    - `endDate`: que la resolución no esté vencida.
    - `nextInvoiceNumber` vs `maxInvoiceNumber`: que aún queden consecutivos disponibles dentro del rango autorizado.

## Datos de la empresa (`client.company`)

`/company` es un recurso singleton (no tiene `id`, ni métodos `list`, `read`, `create` o `delete`):

```python
empresa = client.company.get()
print(empresa["name"], empresa.get("identification"))
```

Puedes pedir campos específicos con `fields` (cadena o iterable de cadenas; múltiples valores se envían separados por coma, aunque la documentación oficial enumera los valores sin especificar cómo combinarlos):

```python
datos = client.company.get(["country", "status"])
```

Para actualizar la configuración de la empresa:

```python
client.company.update({"decimalPrecision": 2})
```

## Vendedores (`sellers`)

La API REST de `api.alegra.com` no expone un endpoint `/sellers` (Alegra documenta los vendedores únicamente como herramienta MCP con autenticación OAuth Bearer, incompatible con las credenciales Basic del SDK), por lo que AlegraPy no incluye un recurso `sellers`.
