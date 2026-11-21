"""Thread-safe one-time deprecation warnings for the legacy global session API."""

import threading
import warnings
from typing import Set

_LOCK = threading.Lock()
_WARNED: Set[str] = set()


def warn_legacy(feature: str, message: str, *, stacklevel: int = 2) -> None:
    """Emit a ``FutureWarning`` at most once per ``feature`` per process."""
    with _LOCK:
        if feature in _WARNED:
            return
        _WARNED.add(feature)
    warnings.warn(message, FutureWarning, stacklevel=stacklevel)


def reset_legacy_warnings() -> None:
    """Clear the warned-once registry (intended for tests)."""
    with _LOCK:
        _WARNED.clear()
