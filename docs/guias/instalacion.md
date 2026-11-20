# Instalación

AlegraPy se publica en PyPI con el nombre `AlegraPy`. Su única dependencia es [`requests`](https://requests.readthedocs.io/), que se instala automáticamente.

```bash
pip install AlegraPy
```

Se recomienda hacerlo dentro de un entorno virtual:

```bash
python -m venv env
source env/bin/activate   # En Windows: env\Scripts\activate
pip install AlegraPy
```

Verifica la instalación:

```python
from alegrapy import AlegraClient

print(AlegraClient)
```

## Nombre del import

La distribución se llama **`AlegraPy`**, pero el paquete se importa como **`alegrapy`**:

```python
import alegrapy
```

El antiguo `import alegra` sigue funcionando como alias de compatibilidad: emite un
`FutureWarning` y se eliminará en la versión 1.0.

!!! note "Versión de Python"
    El paquete requiere Python 3.10 o superior (`requires-python` en `pyproject.toml`).

## Instalación desde el código fuente

Si clonaste el repositorio, puedes instalar el paquete de forma local:

```bash
pip install .
```

## Siguiente paso

Configura tus credenciales en [Autenticación](autenticacion.md).
