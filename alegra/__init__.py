"""Deprecated compatibility shim for the old ``alegra`` import name.

Use ``import alegrapy`` instead. This package only re-exports the real package and
registers identical submodule objects; it will be removed in 1.0.
"""
import importlib
import pkgutil
import sys
import warnings

warnings.warn(
    "The 'alegra' import name is deprecated; use 'import alegrapy'. "
    "It will be removed in 1.0.",
    DeprecationWarning,
    stacklevel=2,
)

import alegrapy as _alegrapy  # noqa: E402
from alegrapy import *  # noqa: F401,F403,E402
from alegrapy import __all__ as _ALEGRAPY_ALL  # noqa: E402

__all__ = list(_ALEGRAPY_ALL)

# Expose the same module objects under the old package name, so isinstance checks,
# monkeypatching and ``from alegra.<module> import ...`` behave identically.
for _module_info in pkgutil.iter_modules(_alegrapy.__path__):
    _short_name = _module_info.name
    if _short_name.startswith("_"):
        continue
    _module = importlib.import_module(f"alegrapy.{_short_name}")
    sys.modules[f"{__name__}.{_short_name}"] = _module

# Keep the legacy class/alias attributes (``alegra.session``, ``alegra.invoices``, ...)
# pointing at what ``alegrapy`` exposes today, not at the submodule objects.
for _name in _ALEGRAPY_ALL:
    setattr(sys.modules[__name__], _name, getattr(_alegrapy, _name))

del _module_info, _module, _short_name, _name
