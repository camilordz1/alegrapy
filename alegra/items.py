from typing import Any, Dict, List, Optional
from alegra.actions import Actions


def _reference_value(record: Dict[str, Any]) -> Any:
    """Read an item's reference from either documented response shape."""
    value = record.get('reference')
    if isinstance(value, dict):
        value = value.get('reference')
    return value


def _normalize_reference(value: Any) -> str:
    """Normalize for comparison only: strip whitespace; case is preserved."""
    return str(value).strip()


class Items(Actions):
    """Operations related to items (productos/servicios) endpoint."""
    endpoint: str = "items"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def find_by_reference(self, reference: str, **filters: Any) -> List[Dict[str, Any]]:
        """Find every item whose reference exactly matches ``reference``.

        The server is narrowed with ``reference=``, but its match mode is undocumented,
        so every page is read and only exact matches are kept. Comparison strips
        whitespace and is case-sensitive (SKUs may differ only by case). Both a string
        reference and the Costa Rica ``{"reference": ...}`` object are accepted.
        Duplicates are possible and are all returned.

        Args:
            reference (str): Reference (SKU) to look for. Must not be blank.
            **filters: Extra query parameters forwarded to the server.

        Returns:
            List[Dict[str, Any]]: Matching items; empty when there is none.

        Raises:
            ValueError: If ``reference`` is blank or a forbidden pagination filter is
                passed (``start``, ``limit``, ``metadata``).
        """
        if reference is None or not str(reference).strip():
            raise ValueError("reference must not be blank")

        needle = _normalize_reference(reference)
        matches = []
        for record in self.iter_all(reference=reference, **filters):
            value = _reference_value(record)
            if value is not None and _normalize_reference(value) == needle:
                matches.append(record)
        return matches


# For backward compatibility
items = Items

