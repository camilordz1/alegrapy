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
from alegra import AlegraClient

print(AlegraClient)
```

!!! note "Versión de Python"
    El archivo `setup.py` del paquete no declara una versión mínima de Python. Los clasificadores del paquete indican Python 3.

## Instalación desde el código fuente

Si clonaste el repositorio, puedes instalar el paquete de forma local:

```bash
pip install .
```

## Siguiente paso

Configura tus credenciales en [Autenticación](autenticacion.md).
