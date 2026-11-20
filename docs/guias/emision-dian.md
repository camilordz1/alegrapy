# Emisión electrónica (DIAN)

Las facturas electrónicas en Alegra pueden enviarse a la autoridad tributaria (DIAN) con `client.invoices.stamp()`, consultar su estado normalizado con `client.invoices.stamp_status()` y esperar un estado final con `client.invoices.wait_until_stamped()`.

## Flujo recomendado

1. **Emitir** una o varias facturas (máximo **10 IDs** por llamada, sin duplicados):

   ```python
   results = client.invoices.stamp([11742, 11743])
   for res in results:
       print(res.invoice_id, res.success, res.state, res.message)
   ```

   Incluso cuando Alegra responde HTTP `200`, algunos elementos pueden venir con `success=False`, y un HTTP `400` con resultados por factura (`data: [{id, code, message}]`) también devuelve una lista de `StampResult` en lugar de lanzar una excepción.

2. **Consultar o esperar** el estado final de una factura:

   ```python
   from alegrapy import AlegraStampTimeoutError, StampState

   try:
       st = client.invoices.wait_until_stamped(11742, timeout=60.0, interval=2.0)
   except AlegraStampTimeoutError as err:
       # El último estado observado queda disponible en err.last_status
       print("Sigue pendiente:", err.last_status.state if err.last_status else None)
   ```

## Tabla de estados (`StampState`)

| Valor crudo (`legalStatus` / `emissionStatus`) | `StampState` | `is_emitted` | `is_final` |
|---|---|---|---|
| `None` / vacío con `status == "draft"` | `DRAFT` | `False` | `False` |
| `PENDING`, `STAMPED_AND_WAITING_RESPONSE` | `PENDING` | `False` | `False` |
| `ACCEPTED`, `STAMPED_AND_ACCEPTED` | `ACCEPTED` | `True` | `True` |
| `STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS` | `ACCEPTED_WITH_OBSERVATIONS` | `True` | `True` |
| `REJECTED`, `STAMPED_AND_REJECTED` | `REJECTED` | `False` | `True` |
| Cualquier otro valor (o `None` en factura no borrador) | `UNKNOWN` | `False` | `False` |

La comparación de los valores crudos no distingue mayúsculas/minúsculas. Un valor desconocido nunca se interpreta como emitido (`is_emitted` es `False` y `legal_status_raw` conserva el texto original).

## `is_emitted` vs `is_final` y observaciones

- **`is_emitted`**: es `True` únicamente para `ACCEPTED` y `ACCEPTED_WITH_OBSERVATIONS`. Indica que la factura quedó emitida ante la DIAN.
- **`is_final`**: es `True` para `ACCEPTED`, `ACCEPTED_WITH_OBSERVATIONS` y `REJECTED`. `wait_until_stamped()` deja de consultar en cualquiera de esos tres estados y devuelve el `StampStatus` (no lanza excepción en `REJECTED`).
- **`observations`**: reúne las advertencias y errores (`stamp.warnings` y `stamp.errors`). Por ejemplo, una notificación como `FAZ09` aparece en `observations` cuando la factura fue aceptada con observaciones (`ACCEPTED_WITH_OBSERVATIONS`, `is_emitted=True`).

## Actualizar el estado de tu aplicación

```python
st = client.invoices.stamp_status(11742)
if st.is_emitted:
    # Marcar como emitida y guardar st.cufe, st.stamped_at y st.observations
    ...
elif st.state == StampState.REJECTED:
    # Corregir los errores reportados en st.observations antes de volver a emitir
    ...
else:
    # DRAFT, PENDING o UNKNOWN: aún no hay decisión final
    ...
```

## Fallas ambiguas y límites

- **Fallas ambiguas**: `stamp()` usa `POST /invoices/stamp` y nunca reintenta automáticamente tras un timeout, error de conexión después del envío o `5xx`. Si ocurre una falla ambigua, **consulta `stamp_status()` antes de reintentar** para confirmar si la DIAN ya procesó la factura.
- **Límite por llamada**: `stamp(ids)` acepta entre **1 y 10** IDs únicos; fuera de ese rango lanza `ValueError` antes de enviar la petición.
