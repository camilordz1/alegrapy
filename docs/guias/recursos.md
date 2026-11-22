# Recursos disponibles

Cada recurso es una propiedad de `AlegraClient`. Todos incluyen las operaciones estándar `list`, `read`, `create`, `update`, `delete`, `iter_all` y `add_attachment` (heredadas de la clase base [`Actions`](../referencia/actions.md)); la columna "Métodos extra" lista lo que se agrega a cada uno. Para recorrer colecciones completas, ver [Paginación](paginacion.md).

| Recurso | Propiedad | Endpoint | Métodos extra |
|---|---|---|---|
| Facturas de venta | `client.invoices` | `invoices` | `void(id)`, `open(id)`, `send_email(id, emails, ...)`, `annul(id, cause)`, `stamp(ids)`, `stamp_status(id)`, `wait_until_stamped(id, ...)`, `get_pdf(id)`, `download_pdf(id, path)`, `get_xml(id)`, `download_xml(id, path)` |
| Notas crédito | `client.credit_notes` | `credit-notes` | CRUD estándar; la anulación usa `client.invoices.annul` |
| Contactos (clientes y proveedores) | `client.contacts` | `contacts` | `find_by_identification(identification)` |
| Pagos / ingresos | `client.payments` | `payments` | `void(id)`, `open(id)` |
| Ítems (productos y servicios) | `client.items` | `items` | `find_by_reference(reference)` |
| Cotizaciones | `client.estimates` | `estimates` | `void(id)`, `open(id)`, `send_email(id, emails, ...)` |
| Órdenes de compra | `client.purchase_orders` | `purchase-orders` | `void(id)`, `send_email(id, emails, ...)`, `add_comment(id, comment_text)` |
| Cuentas bancarias | `client.bank_accounts` | `bank-accounts` | `transfer(from_id, to_id, amount, date, description)` |
| Impuestos | `client.taxes` | `taxes` | ninguno |
| Monedas | `client.currencies` | `currencies` | ninguno |
| Retenciones | `client.retentions` | `retentions` | ninguno |
| Usuarios | `client.users` | `users` | `self_info()` |
| Numeraciones | `client.number_templates` | `number-templates` | `list(..., document_type=...)`, `iter_all(..., document_type=...)`, `default(document_type="invoice")` |
| Empresa (singleton) | `client.company` | `company` | `get(fields=None)`, `update(params)` (sin `list`/`read`/`create`/`delete`) |

Para los campos, filtros y reglas de cada recurso, consulta la [documentación oficial de la API de Alegra](https://developer.alegra.com/).

!!! note
    Las operaciones estándar se ofrecen en todos los recursos porque comparten la misma clase base, pero que Alegra las admita para un recurso concreto depende de su API. Si una operación no está soportada, recibirás un [`AlegraAPIError`](errores.md) con el código HTTP correspondiente.

## Ejemplos de métodos extra

### Anular y reabrir

Disponible en `invoices`, `payments` y `estimates` (`purchase_orders` solo tiene `void`).

```python
client.invoices.void(123)
client.invoices.open(123)
```

### Enviar por correo

Disponible en `invoices`, `estimates` y `purchase_orders`. `emails` acepta una cadena o una lista; `send_copy_to_user` es `False` por defecto, y `subject` / `message` son opcionales.

```python
client.invoices.send_email(
    123,
    emails="cliente@dominio.com",
    send_copy_to_user=True,
    subject="Tu factura",
    message="Adjuntamos tu factura.",
)
```

### Comentar una orden de compra

```python
client.purchase_orders.add_comment(45, "Entrega confirmada para el lunes")
```

### Transferencia entre cuentas bancarias

```python
client.bank_accounts.transfer(
    from_id=1, to_id=2, amount=50000.0, date="2026-06-21",
)
```

### Usuario autenticado

```python
client.users.self_info()
```
