# Catálogos y remisiones

AlegraPy ofrece cinco recursos de catálogo y operación comercial:

- `client.remissions` (`/remissions`)
- `client.warehouses` (`/warehouses`)
- `client.price_lists` (`/price-lists`)
- `client.item_categories` (`/item-categories`)
- `client.terms` (`/terms`)

!!! note "Identificadores UUID v7"
    Alegra genera nuevos registros de bodegas, listas de precios, términos, remisiones, ítems y otros catálogos con IDs UUID v7 de 36 caracteres (por ejemplo `01959152-fe97-7a6e-a2d5-c0c63e82f80a`), mientras los registros antiguos conservan IDs cortos. Trata siempre los `id` como cadenas opacas (no los conviertas con `int()`).

## Remisiones (`client.remissions`)

Ordenamiento válido: `id`, `name`, `date`, `dueDate`. Incluye `open(id)`, `void(id)`, `add_attachment` y `delete_attachment(attachment_id)`.

```python
rem = client.remissions.create({
    "documentName": "remission",  # remission | serviceOrder
    "date": "2026-11-22",
    "dueDate": "2026-11-22",
    "client": {"id": 126},
    "items": [{"id": 1, "quantity": 1, "price": 10000}],
})
client.remissions.void(rem["id"])
client.remissions.open(rem["id"])
```

## Bodegas (`client.warehouses`)

Ordenamiento válido: `name`, `id`. Filtros: `status` (`active` | `inactive`), `name`, `fields` (`editable` | `deletable`).

## Listas de precios (`client.price_lists`)

Ordenamiento válido: `name`, `id`. Al crear o actualizar, `type` debe ser `"amount"` o `"percentage"` (con `"percentage"`, `percentage` numérico es obligatorio) y `name` admite máximo 90 caracteres.

## Categorías de ítems (`client.item_categories`)

Ordenamiento válido: únicamente `name`. Incluye `add_attachment` (máximo 2 MB) y `delete_attachment(attachment_id)`.

## Términos de pago (`client.terms`)

`GET /terms` no documenta paginación ni ordenamiento (devuelve hasta 30 términos por defecto). `list(fields=None)` no envía `start`/`limit` y `iter_all()` rinde los resultados desde una única llamada.
