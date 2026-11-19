# Anulación y notas crédito

Una factura electrónica **no se anula** con `void`: se cancela emitiendo una nota crédito. El SDK
construye esa nota a partir de la factura y evita crear dos notas para la misma factura.

```python
nota = client.invoices.annul(11742, "Anulación solicitada por el cliente")
```

## Anulación total vs. nota parcial

- `annul()` crea una nota **total** de anulación: tipo `VOID_ELECTRONIC_INVOICE`, referencia la
  factura y usa su total.
- Para notas parciales (devoluciones, descuentos, ajustes de precio) usa directamente
  `client.credit_notes.create(...)` con el tipo y los ítems que correspondan.

## Requisitos de la factura

`annul` lee la factura antes de escribir y exige:

- `status == "open"` (recibible/abierta);
- timbre aceptado (`stamp.legalStatus` empieza por `STAMPED_AND_ACCEPTED`).

Si no se cumple, lanza `ValueError` **antes** de cualquier `POST`. El motivo (`cause`) no puede
estar vacío.

## Qué envía

La nota se arma con:

- el mismo `client.id`, `warehouse` y `costCenter` de la factura (cuando existen);
- cada ítem con `id`, `price`, `quantity`, `tax` (ids) y `reference`/`description` si están;
- `type = VOID_ELECTRONIC_INVOICE`;
- `creditNoteOperationType = REFERENCE_TO_ELECTRONIC_INVOICE` por defecto;
- `invoices = [{"id": <factura>, "amount": <total>}]`;
- la fecha de hoy;
- `stamp = {"generateStamp": True}` salvo que pases `stamp=False`;
- la marca de deduplicación en `observations` (nunca se imprime en la factura).

## Tipos y tipos de operación

| `CreditNoteType` | Valor |
|---|---|
| `PARTIALL_DEVOLUTION` | `PARTIALL_DEVOLUTION` (así lo escribe la API) |
| `VOID_ELECTRONIC_INVOICE` | `VOID_ELECTRONIC_INVOICE` (anulación total) |
| `REDUCTION_DISCOUNT_PARTIAL_TOTAL` | `REDUCTION_DISCOUNT_PARTIAL_TOTAL` |
| `PRICE_ADJUSTMENT` | `PRICE_ADJUSTMENT` |
| `OTHER` | `OTHER` |

| `CreditNoteOperationType` | Cuándo |
|---|---|
| `REFERENCE_TO_ELECTRONIC_INVOICE` | La factura aún no fue aceptada por el cliente (valor por defecto). |
| `NO_REFERENCE_TO_ELECTRONIC_INVOICE` | El cliente ya aceptó la factura ante la DIAN. |

```python
from alegra import CreditNoteOperationType

nota = client.invoices.annul(
    11742,
    "Nota crédito por aceptación del cliente",
    operation_type=CreditNoteOperationType.NO_REFERENCE_TO_ELECTRONIC_INVOICE,
)
```

También se acepta el valor como texto (`"NO_REFERENCE_TO_ELECTRONIC_INVOICE"`). El catálogo
colombiano está en la [documentación de Alegra](https://developer.alegra.com/docs/colombia); las
reglas de anulación, en el [Centro de Ayuda](https://ayuda.alegra.com/).

## Una factura ya anulada nunca se anula dos veces

Además de buscar la marca, `annul()` **vuelve a leer la factura antes de cada POST**. Si la
encuentra en estado anulado (`status="closed"`, `balance=0` y `totalPaid=0`, comparados
numéricamente), no envía nada:

- intenta devolver la nota existente con la búsqueda de la marca;
- si no la encuentra en las páginas escaneadas, lanza `AlegraAlreadyAnnulledError` con
  `invoice_id`.

```python
from alegra import AlegraAlreadyAnnulledError

try:
    nota = client.invoices.annul(11742, "motivo")
except AlegraAlreadyAnnulledError as err:
    registrar_para_revision(err.invoice_id)
```

Una factura cerrada porque fue **pagada** (`balance` o `totalPaid` mayores que cero) no está
anulada: sigue siendo un error de precondición (solo se anulan facturas abiertas).

Como la lista de notas no permite filtrar por cliente, la búsqueda recorre las notas más
recientes de toda la cuenta. En cuentas muy activas puedes ampliar la ventana:

```python
client.invoices.annul(11742, "motivo", lookup_pages=5)  # hasta 150 notas
```

## Idempotencia: la misma factura produce la misma nota

La clave por defecto es `annul:<id>` y se guarda como marca en `observations`. Antes de crear, el
SDK busca esa marca en las notas más recientes (las últimas 60, sin filtro de estado). Si ya
existe, la devuelve y **no hace POST**. Si el POST falla de forma ambigua, verifica durante
`verify_window` segundos (30 por defecto) y, si no aparece, reintenta una vez como máximo. Si sigue
sin poder confirmarlo, lanza `AlegraUnverifiedCreateError` con `resource="credit-notes"`.

El endpoint de notas no documenta un filtro por cliente, así que la búsqueda es por `id`
descendente y la marca se compara del lado del cliente (además del `client.id` de la nota cuando
está presente).

Puedes sobrescribir la clave:

```python
client.invoices.annul(11742, "motivo", dedup_key="annul-caso-42", on_unverified="raise")
```

Con `on_unverified="raise"` no se hace el segundo POST: úsalo junto con una cuarentena
(`err.to_dict()`) si necesitas cero duplicados.

## Si falla el timbrado

La API puede responder `400` **después de crear** la nota cuando el timbrado electrónico falla.
El SDK solo lo interpreta así cuando el cuerpo contiene una nota real: un objeto con `id`, con
`creditNoteOperationType` o un `type` del catálogo, y cuya lista `invoices` referencia **esta**
factura. En ese caso lanza `AlegraStampError` y la nota creada queda en `err.document`:

```python
from alegra import AlegraStampError

try:
    nota = client.invoices.annul(11742, "motivo")
except AlegraStampError as err:
    guardar_nota_abierta(err.document)   # ya existe: no la crees otra vez
    reintentar_timbrado(err.document["id"])
```

Si el `400` no tiene esa forma (por ejemplo, un error de validación que repite la factura o el
cliente), se lanza el error tipado normal (`AlegraValidationError`).

## `void` sigue existiendo

`client.invoices.void(id, cause=None)` se mantiene para documentos **no electrónicos**; ahora envía
`{"cause": cause}` cuando se la pasas. Para facturas electrónicas colombianas usa `annul()`.

## Recurso `credit_notes`

`client.credit_notes` expone las operaciones estándar (`list`, `read`, `create`, `update`,
`delete`, `iter_all`) sobre `credit-notes`, por si necesitas notas parciales o consultar las
existentes. El alias legacy es `credit_notes`.
