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

## Creación sin duplicados (`create_once`)

A diferencia de facturas y pagos, **no existe `create_once` para notas débito** todavía: la documentación REST de `/income-debit-notes` no define el campo `observations` (solo `annotation`, que se imprime en el PDF) ni filtros de `client_id` u ordenamiento en el listado. Mientras no se verifique si el marcador persiste y el listado pagina de forma estable, no es seguro automatizar reintentos de creación.
