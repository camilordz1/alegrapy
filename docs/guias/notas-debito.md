# Notas débito de cliente

`client.income_debit_notes` permite crear, consultar, listar, actualizar, eliminar y anular notas débito de cliente (`/income-debit-notes`).

## Crear una nota débito

```python
from alegrapy import AlegraClient

client = AlegraClient(user="tu_usuario@dominio.com", token="tu_token_api")

nota = client.income_debit_notes.create({
    "date": "2026-11-22",
    "dueDate": "2026-11-22",
    "type": "VALUE_CHANGE",
    "paymentMethod": "CASH",
    "paymentType": "CASH",
    "client": {"id": 126},
    "invoice": {"id": 11742},
    "items": [{"id": 1, "quantity": 1, "price": 10000}],
})
```

## Listar y paginar

```python
notas = client.income_debit_notes.list(
    status="open",
    emission_status="STAMPED_AND_ACCEPTED",
    date="2026-11-22",
)

for nota in client.income_debit_notes.iter_all(status="open"):
    print(nota["id"])
```

Filtros documentados: `status` (`open`, `closed`, `draft`, `void`), `emission_status`, `date`, `dueDate`, `client_name`, `client_identification`, `prefix` y `number`.

## Anular una nota débito

```python
client.income_debit_notes.void(42)
```

## Notas débito sin duplicados

`client.income_debit_notes.create_once` y `reconcile` protegen contra duplicados usando la marca `alegrapy:dedup:<clave>` en `observations`:

```python
from alegrapy import AlegraClient, AlegraLookupIncompleteError, AlegraUnverifiedCreateError, make_dedup_key_from

key = make_dedup_key_from(datos, ["client.id", "invoice.id", "type", "items[].id", "items[].price"])

try:
    nota = client.income_debit_notes.create_once(
        datos, dedup_key=key, on_unverified="raise",
    )
except AlegraLookupIncompleteError as err:
    # Más de max_pages * 30 notas ese día antes de publicar: amplía max_pages
    raise
except AlegraUnverifiedCreateError as err:
    guardar_en_cuarentena(err.to_dict())
```

Ten en cuenta:

- **Búsqueda por día (`date`)**: `GET /income-debit-notes` devuelve los registros en orden ascendente por `id` sin ordenamiento ni filtro `client_id`, así que `reconcile(key, date=..., client_id=...)` recorre las páginas de ese día (hasta `max_pages * 30`). Si se agotan `max_pages` páginas completas sin terminar el día, lanza `AlegraLookupIncompleteError` (en precheck aborta sin hacer `POST`; durante la verificación tras un `POST` ambiguo pasa a `AlegraUnverifiedCreateError` para cuarentena).
- **Misma fecha en reintentos**: un reintento después de medianoche con otra `date` no encontrará la nota del día anterior.
- **Reutilización de IDs**: si borras borradores, Alegra puede reutilizar sus `id`; la identidad es la marca en `observations`, nunca el `id`.
