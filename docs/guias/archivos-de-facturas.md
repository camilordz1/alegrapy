# Archivos de facturas (PDF y XML)

Descarga el PDF o el XML timbrado de una factura en una sola llamada:

```python
pdf = client.invoices.get_pdf(11742)                    # bytes
client.invoices.download_pdf(11742, "FE5943.pdf")        # escribe de forma atómica
xml = client.invoices.get_xml(11742)                    # bytes (XML timbrado)
client.invoices.download_xml(11742, "FE5943.xml", overwrite=True)
```

`download_*` devuelve un `pathlib.Path` y escribe primero en un archivo temporal de la misma
carpeta, hace `fsync` y luego `os.replace`: nunca queda un archivo a medias.

## La descarga nunca lleva credenciales

El flujo tiene dos pasos:

1. **Autenticado**: se pide la URL del archivo con
   `GET /invoices/{id}?fields=pdf` (o `xml`) a través del cliente normal; aquí aplican los
   reintentos y los errores tipados.
2. **Anónimo**: se descarga la URL con una petición nueva que **no** envía `Authorization`, ni las
   cookies del cliente, ni sus cabeceras. Nunca se usa `client.session` para el archivo.

La URL firmada es en sí misma un secreto portador: el SDK nunca la escribe en logs; solo registra
el host del archivo. No se mantiene una lista blanca de hosts (Alegra puede mover sus CDN): la
frontera de confianza es que la URL venga de la respuesta autenticada de la API y sea `https`.
Una redirección a `http://` se rechaza.

## Las URLs caducan

Las URLs firmadas observadas duran unas **10 horas**. Guárdalas solo si las necesitas en ese
plazo; lo normal es guardar el archivo, no la URL. Si una URL caduca, el SDK pide una nueva a
Alegra una sola vez y reintenta la descarga; si vuelve a fallar, lanza el error tipado
correspondiente (`AlegraAuthError` para 403, `AlegraNotFoundError` para 404).

## Borradores y facturas sin timbrar

- Una factura en **borrador** no tiene PDF: Alegra no genera la URL. El SDK lanza
  `AlegraFileNotAvailableError`.
- El XML solo existe una vez **timbrada** la factura. Si aún no lo está, espera a que Alegra la
  procese (por ejemplo, con `POST /invoices/stamp`) y vuelve a pedir el archivo.

## Seguridad y límites

- El contenido se valida: el PDF debe empezar por `%PDF-` y el XML por `<?xml` (se admite BOM
  UTF-8). Cualquier otra cosa lanza `AlegraAPIError("unexpected file content")` sin incluir los
  bytes en el mensaje.
- `max_bytes` (25 MB por defecto) limita el tamaño; si se supera, se lanza `AlegraAPIError`.
- El timeout de la descarga es el del cliente (`client.timeout`).
- `download_*` comprueba el destino **antes** de hacer cualquier petición: si el archivo existe y
  `overwrite=False`, lanza `FileExistsError`; si la carpeta padre no existe, `FileNotFoundError`.
- No hay estado compartido: las descargas cumplen el contrato de
  [Concurrencia](concurrencia.md).

## Errores

| Situación | Excepción |
|---|---|
| Sin PDF/XML (borrador, sin timbrar) | `AlegraFileNotAvailableError` |
| URL no `https`, con credenciales o redirección a `http` | `AlegraAPIError` |
| 403/404 del host de archivos (tras refrescar una vez) | `AlegraAuthError` / `AlegraNotFoundError` |
| Contenido inesperado o tamaño excedido | `AlegraAPIError` |
| Fallo de red | `AlegraConnectionError` / `AlegraTimeoutError` |
| Archivo existente / carpeta inexistente | `FileExistsError` / `FileNotFoundError` |
