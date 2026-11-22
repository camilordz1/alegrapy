# Versiones y cambios

AlegraPy sigue [Semantic Versioning](https://semver.org/lang/es/) (`MAJOR.MINOR.PATCH`).

## Reglas de versionado

- **Durante la serie `0.y.z`**:
  - Un cambio de versión **MINOR** (`0.1` -> `0.2`) **puede** incluir cambios incompatibles (*breaking changes*), siempre documentados en la sección **Breaking changes** del [CHANGELOG](https://github.com/camilordz1/alegrapy/blob/master/CHANGELOG.md).
  - Un cambio **PATCH** (`0.1.0` -> `0.1.1`) contiene únicamente correcciones, sin cambios incompatibles.
- **A partir de `1.0.0`**:
  - Los cambios incompatibles solo se introducirán en versiones **MAJOR**.
  - Toda funcionalidad obsoleta se anunciará al menos una versión **MINOR** antes de su eliminación mediante un `FutureWarning` o `DeprecationWarning`.

## Fijar la versión en tu proyecto

Mientras la librería esté en `0.y.z`, fija el rango menor para evitar actualizaciones inesperadas entre versiones `MINOR`:

```text
AlegraPy>=0.5,<0.6
```

## Cambios planeados para 1.0.0

Las siguientes piezas de compatibilidad se mantienen en `0.1.x` y se eliminarán en `1.0.0`:

- El alias de importación `alegra` (emite `FutureWarning`; usa `import alegrapy`).
- La sesión global `session` y los recursos a nivel de módulo (usa `AlegraClient`).
- El nombre actual del logger `"alegra"` (pasará a `"alegrapy"`).

## Historial de cambios

Consulta el detalle de cada versión en [CHANGELOG.md](https://github.com/camilordz1/alegrapy/blob/master/CHANGELOG.md).

Para mantenedores, el proceso de publicación está documentado en [RELEASING.md](https://github.com/camilordz1/alegrapy/blob/master/RELEASING.md).
