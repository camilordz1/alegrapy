# Compras y documentos de proveedor

AlegraPy incluye `client.bills` para facturas de proveedor (`/bills`) y `client.debit_notes` para notas débito de proveedor (`/debit-notes`).

## Facturas de proveedor (`client.bills`)

### Listar y ordenar

`GET /bills` admite ordenamiento únicamente por `date`, `name` o `dueDate` (no por `id`):

```python
facturas = client.bills.list(
    status="open",
    type="supportDocument",  # bill | supportDocument | all
    order_field="dueDate",
    order_direction="DESC",
)
```

### Cerrar una factura de proveedor

`close(id, date, category, observations=None)` cancela el saldo pendiente generando un asiento contable (`date` debe ser posterior a la fecha de creación de la factura):

```python
client.bills.close(105, date="2026-11-22", category={"id": 5060}, observations="Ajuste por cierre")
```

### Comentarios y adjuntos

```python
resp = client.bills.add_comment(105, ["Revisada", "Aprobada para pago"])
# Devuelve {"code": 201, "message": <factura>} sin modificar

adjunto = client.bills.add_attachment(105, "soporte.pdf")
client.bills.delete_attachment(adjunto["id"])
```

## Notas débito de proveedor (`client.debit_notes`)

`client.debit_notes` corresponde a notas débito **de proveedor** (`/debit-notes`); para notas débito de **cliente**, usa `client.income_debit_notes`.

```python
notas = client.debit_notes.list(client_id=126, date="2026-11-22")
```

`/debit-notes` no documenta ordenamiento (`order_field` y `order_direction` lanzan `ValueError`). Ten en cuenta que eliminar una nota débito falla en Alegra si la factura asociada ya fue conciliada.
