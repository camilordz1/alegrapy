# Ajustes de inventario

`client.inventory_adjustments` administra ajustes de inventario (`/inventory-adjustments`) y sus numeraciones (`client.inventory_adjustments.numerations`).

## Ajustes con entradas y salidas

Cada ajuste puede combinar líneas `"in"` (entrada) y `"out"` (salida), y todas requieren `id`, `type`, `quantity` (> 0) y `unitCost` (>= 0):

```python
from alegrapy import AlegraClient

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

ajuste = client.inventory_adjustments.create({
    "date": "2026-11-23",
    "warehouse": {"id": 3},
    "items": [
        {"id": "1", "type": "in", "quantity": 5, "unitCost": 12000},
        {"id": "2", "type": "out", "quantity": 1, "unitCost": 8500},
    ],
})
```

## Numeraciones (`client.inventory_adjustments.numerations`)

```python
nums = client.inventory_adjustments.numerations.list(status="active")
```

Los `id` de numeración pueden ser ULID (como `"01HVVJWB1SJJNCG1W4KM7JSZ3A"`). `list` usa `limit=20` por defecto (1..30) y no admite ordenamiento.

## Ajustes sin duplicados (`create_once`)

Duplicar un ajuste mueve el inventario dos veces. Usa `create_once` con una clave estable y `on_unverified="raise"` para enviar los casos ambiguos a cuarentena:

```python
from alegrapy import AlegraLookupIncompleteError, AlegraUnverifiedCreateError, make_dedup_key_from

key = make_dedup_key_from(datos, ["date", "warehouse.id", "items[].id", "items[].type", "items[].quantity"])

try:
    ajuste = client.inventory_adjustments.create_once(datos, dedup_key=key, on_unverified="raise")
except AlegraLookupIncompleteError:
    raise  # Día con más de max_pages * 30 ajustes: amplía max_pages
except AlegraUnverifiedCreateError as err:
    guardar_en_cuarentena(err.to_dict())
```

La búsqueda (`reconcile`) filtra por `date` en orden descendente de `id` (los más recientes primero) y revalida `warehouse` del lado del cliente. Si `max_pages` páginas completas se agotan sin coincidencia, lanza `AlegraLookupIncompleteError`.

## Consultar existencias y límites no documentados

El inventario actual de un ítem inventariable se lee desde `client.items.read(id)["inventory"]` (`availableQuantity`, `unitCost`, `warehouses`).

### Comportamiento observado

Una prueba en una cuenta colombiana de producción (2026-11-23, entrada de 1 unidad que luego se eliminó) mostró lo siguiente, que Alegra no documenta:

- **El stock se actualiza de forma asíncrona.** Justo después de crear el ajuste, `availableQuantity` todavía mostraba el valor anterior; el cambio apareció unos segundos después. No leas el stock inmediatamente después de un ajuste esperando ver el valor nuevo: vuelve a consultarlo con un tiempo de espera, o confía en el ajuste creado y no en la lectura del stock.
- **Eliminar un ajuste revierte el stock**, también con demora: el stock volvió al valor original y se mantuvo estable.
- **Los ids de los ajustes son UUID v7** (por ejemplo `01a2096c-843f-7634-9133-0cb01ccd66c4`), aunque el changelog de Alegra no los incluye entre los recursos con el nuevo formato. AlegraPy los acepta.
- El marcador de `create_once` en `observations` persiste, `reconcile` encuentra el ajuste y un segundo `create_once` con la misma clave no crea otro.

Es una sola prueba: el comportamiento puede variar con la carga de Alegra.

### Límites no documentados

Alegra **no documenta**: errores por salidas mayores al stock disponible, ítems no inventariables, efectos sobre costo promedio, precisión decimal ni claves de idempotencia nativas. Para verificar el comportamiento en tu cuenta antes de automatizar, usa la sonda de mantenimiento `scripts/probe_inventory_adjustment.py` (requiere `--yes-call-live-api` y `--delete`). La sonda espera a que el stock refleje cada cambio hasta `--settle-timeout` segundos (30 por defecto) antes de comparar.
