# Paginación

`iter_all(max_items=None, page_size=30, **filtros)` recorre **todos** los registros que
coinciden con los filtros, pidiendo una página a la vez. Sustituye los bucles manuales con
`start`/`limit`.

```python
# Todos los ítems activos
for item in client.items.iter_all(status="active"):
    procesar(item)

# Solo los primeros 100
primeros = list(client.invoices.iter_all(client_id=126, max_items=100))
```

Está disponible en todos los recursos (`client.contacts`, `client.payments`, `client.items`, …)
y también en los recursos legacy (`items().iter_all(...)`).

## Cómo pagina

- Pide páginas con `start` y `limit` mediante `list`, sin cargar todo en memoria: cada página
  se solicita cuando el consumidor la necesita.
- `page_size` va de 1 a 30 (30 es el máximo de la API). Por defecto 30.
- Se detiene cuando una página llega vacía o con menos registros de los pedidos, cuando se
  alcanza `max_items`, o si la API ignora `start` (una página completa repite el primer `id` de
  la anterior; se registra un `WARNING` y se corta).
- Si `max_items` limita lo que falta, la última petición pide
  `limit=min(page_size, restantes)`, así no trae de más.
- Si una página falla, la excepción tipada de esa página se propaga sin cambios (los reintentos
  ya ocurren dentro del cliente).

`max_items=0` no envía ninguna petición y no produce registros.

## Filtros y orden

Cualquier argumento con nombre se envía como parámetro de consulta, igual que en `list`:

```python
# Filtro + orden descendente por fecha
for factura in client.invoices.iter_all(status="open", order_direction="DESC", order_field="date"):
    ...
```

No puedes pasar `start`, `limit` ni `metadata`: el iterador controla la paginación y necesita la
forma de respuesta de lista. Si lo intentas, lanza `ValueError` antes de enviar nada.

## Advertencia: la colección puede cambiar mientras paginas

La paginación es por desplazamiento (`start`). Si se crean o eliminan registros mientras recorres
la colección, puedes saltarte alguno o recibir otro repetido.

Para trabajos de “procesar todo”, usa el orden ascendente por `id` (el valor por defecto) y no
modifiques la colección durante el recorrido:

```python
for item in client.items.iter_all():  # order_field="id", ASC por defecto
    sincronizar(item)
```

Si necesitas una foto consistente en el tiempo, filtra por fecha o por `id` y guarda el último
`id` procesado para reanudar.
