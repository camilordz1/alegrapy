# Búsquedas exactas

Dos ayudantes buscan un contacto por identificación (NIT/cédula) y un ítem por referencia
(SKU) sin que tengas que paginar a mano:

```python
contactos = client.contacts.find_by_identification("900559088")
items = client.items.find_by_reference("TP-15210")
```

Ambos devuelven una **lista** (posiblemente vacía y posiblemente con más de un resultado).
No lanzan excepción si no encuentran nada: revisa la longitud.

## Cómo buscan

1. Acotan la consulta en el servidor con el filtro documentado (`identification=` o
   `reference=`), enviando el valor ya normalizado (ver las reglas abajo). Así una entrada como
   `" 900.559.088 "` consulta `900559088`.
2. Recorren **todas** las páginas con [`iter_all`](paginacion.md). El modo de coincidencia del
   servidor no está documentado y puede ser “contiene”, así que leer solo la primera página
   perdería resultados.
3. Se quedan únicamente con las coincidencias **exactas**, comparando en el cliente.

## Reglas de comparación

| Dato | Normalización | Ejemplo |
|---|---|---|
| Identificación | Quita espacios y puntos; **conserva el guion** | `"900.559.088"` coincide con `"900559088"` |
| Referencia | Quita espacios al inicio/fin; **distingue mayúsculas** | `"TP-15210"` no coincide con `"tp-15210"` |

El dígito de verificación (DV) es un campo aparte en Alegra, por eso `"900559088-2"` **no** se
considera igual a `"900559088"`.

Los dos formatos de respuesta que aparecen en distintas cuentas se manejan de forma
transparente:

- Contacto: `identification` (texto) o `identificationObject.number`.
- Ítem: `reference` (texto) o el objeto `{"type": ..., "reference": ...}` de Costa Rica.

## Duplicados

Los duplicados existen en cuentas reales: una misma identificación puede pertenecer a varios
contactos. El ayudante devuelve todos para que decidas con tu propio criterio (por ejemplo,
preferir el más reciente o el que tenga `status="active"`):

```python
coincidencias = client.contacts.find_by_identification("222222222222")
if not coincidencias:
    crear_contacto()
elif len(coincidencias) == 1:
    usar(coincidencias[0])
else:
    elegido = max(coincidencias, key=lambda c: c.get("id", 0))
    registrar_duplicado(coincidencias, elegido)
```

No hay `find_one_by_...`: ocultar la decisión sobre duplicados sería peor que exponerla.

## Filtros y validación

Puedes añadir filtros de la API; se reenvían a la consulta:

```python
client.items.find_by_reference("TP-15210", status="active")
```

- Una identificación o referencia vacía (o solo espacios) lanza `ValueError` sin enviar
  ninguna petición.
- No puedes pasar `start`, `limit` ni `metadata`: la paginación la controla el ayudante y
  lanza `ValueError`.
- Los errores de cualquier página se propagan sin cambios (los reintentos ya ocurren dentro
  del cliente).
