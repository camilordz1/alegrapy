"""Thread-safe one-time deprecation warnings for the legacy global session API."""

import os
import sys
import threading
import warnings
from typing import Set

_LOCK = threading.Lock()
_WARNED: Set[str] = set()
_EMITTING: Set[str] = set()  # features whose warning is being delivered right now

# Frames inside these directories are library internals; the warning is attributed to
# the first frame outside them (the caller's line), whatever the internal call depth.
_INTERNAL_DIRS = tuple(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name) + os.sep
    for name in ("alegrapy", "alegra")
)


def _caller_stacklevel() -> int:
    """Return the ``warnings.warn`` stacklevel of the first frame outside the package."""
    level = 2  # stacklevel 2 is the direct caller of warn_legacy
    frame = sys._getframe(2)
    while frame is not None and frame.f_code.co_filename.startswith(_INTERNAL_DIRS):
        frame = frame.f_back
        level += 1
    return level


def warn_legacy(feature: str, message: str) -> None:
    """Emit a ``FutureWarning`` at most once per ``feature`` per process.

    The warning is attributed to the first stack frame outside ``alegrapy``, so it points
    at the application line that used the legacy API. A feature only counts as warned once
    ``warnings.warn`` returns: when a filter turns the warning into an exception, the next
    use raises again. A warning dropped by an ``ignore`` filter still counts as delivered,
    because ``warnings`` gives no way to tell it apart. While a feature's warning is being
    delivered, other uses of that feature (from a ``showwarning`` hook or another thread)
    return silently, so a hook that touches the legacy API cannot recurse. The lock is
    never held while user filters and hooks run.
    """
    with _LOCK:
        if feature in _WARNED or feature in _EMITTING:
            return
        _EMITTING.add(feature)
    try:
        warnings.warn(message, FutureWarning, stacklevel=_caller_stacklevel())
        with _LOCK:
            _WARNED.add(feature)
    finally:
        with _LOCK:
            _EMITTING.discard(feature)


def reset_legacy_warnings() -> None:
    """Clear the warned-once registry (intended for tests)."""
    with _LOCK:
        _WARNED.clear()
        _EMITTING.clear()
