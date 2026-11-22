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
- la fecha de hoy según el reloj del servidor, o la que pases con `date=` (un `date` o el texto
  `"AAAA-MM-DD"`). Pásala explícita si tu servidor corre en otra zona horaria (por ejemplo, UTC):
  cerca de la medianoche podría enviar el día siguiente al de tu operación,
  `client.invoices.annul(11742, "motivo", date="2026-11-19")`;
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
from alegrapy import CreditNoteOperationType

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
from alegrapy import AlegraAlreadyAnnulledError

try:
    nota = client.invoices.annul(11742, "motivo")
except AlegraAlreadyAnnulledError as err:
    registrar_para_revision(err.invoice_id)
```

Si la factura aparece anulada **después de un POST ambiguo de esta misma llamada**, lo más probable
es que ese POST haya creado la nota. En ese caso no se lanza `AlegraAlreadyAnnulledError` sino
`AlegraUnverifiedCreateError` (con `dedup_key` y el payload, listo para la cuarentena), cuya
causa (`err.__cause__`) es el `AlegraAlreadyAnnulledError`.

Una factura cerrada porque fue **pagada** (`balance` o `totalPaid` mayores que cero) no está
anulada: sigue siendo un error de precondición (solo se anulan facturas abiertas).

La búsqueda envía `client_id` y, cuando la nota tiene fecha (`date`), usa primero el filtro `date` del servidor (hasta `lookup_pages * 30` notas de ese día) antes de recurrir al barrido sin filtro de fecha. Ten en cuenta que con `date` cada búsqueda puede hacer hasta dos pasadas (día filtrado y luego ventana sin fecha), por lo que la ventana de verificación emite aproximadamente el doble de peticiones `GET` (Alegra limita a 150 peticiones por minuto). En cuentas muy activas puedes ampliar la ventana:

```python
client.invoices.annul(11742, "motivo", lookup_pages=5)  # hasta 150 notas
```

## Idempotencia: la misma factura produce la misma nota

La clave por defecto es `annul:<id>` y se guarda como marca en `observations`. Antes de crear, el
SDK busca esa marca en las notas más recientes (las últimas 60, sin filtro de estado). Si ya
existe, la devuelve y **no hace POST**. Si el POST falla de forma ambigua, verifica durante
`verify_window` segundos (30 por defecto) y, si no aparece, reintenta una vez como máximo. Si sigue
sin poder confirmarlo, lanza `AlegraUnverifiedCreateError` con `resource="credit-notes"`.

La búsqueda envía `client_id` como filtro al servidor (y cuando hay fecha, filtra primero por `date`) y vuelve a comprobar la marca y el `client.id` del lado del cliente.

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
from alegrapy import AlegraStampError

try:
    nota = client.invoices.annul(11742, "motivo")
except AlegraStampError as err:
    guardar_nota_abierta(err.document)   # ya existe: no la crees otra vez
    reintentar_timbrado(err.document["id"])
```

Si el `400` no tiene esa forma (por ejemplo, un error de validación que repite la factura o el
cliente), se lanza el error tipado normal (`AlegraValidationError`).

Volver a llamar `annul()` para esa factura **no** da la anulación por terminada: la búsqueda
encuentra la nota con la marca, ve que no está timbrada y vuelve a lanzar `AlegraStampError` con
esa nota en `err.document`. Solo una nota timbrada y aceptada (`STAMPED_AND_ACCEPTED...`) se
devuelve como éxito. Con `stamp=False` esta comprobación no aplica.

## `void` sigue existiendo

`client.invoices.void(id, cause=None)` se mantiene para documentos **no electrónicos**; ahora envía
`{"cause": cause}` cuando se la pasas. Para facturas electrónicas colombianas usa `annul()`.

## Recurso `credit_notes`

`client.credit_notes` expone las operaciones estándar (`list`, `read`, `create`, `update`,
`delete`, `iter_all`) sobre `credit-notes`, por si necesitas notas parciales o consultar las
existentes. El alias legacy es `credit_notes`.
