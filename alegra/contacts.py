from typing import Any, Dict, List, Optional
from alegra.actions import Actions


def _identification_value(record: Dict[str, Any]) -> Any:
    """Read a contact's identification from either documented response shape."""
    value = record.get('identification')
    if isinstance(value, dict):
        value = value.get('number')
    if value is None:
        obj = record.get('identificationObject')
        if isinstance(obj, dict):
            value = obj.get('number')
    return value


def _normalize_identification(value: Any) -> str:
    """Normalize for comparison only: strip, then drop dots and spaces.

    The check digit (``-2``) is a separate field in Alegra, so hyphens are preserved.
    """
    return str(value).strip().replace('.', '').replace(' ', '')


class Contacts(Actions):
    """Operations related to contacts (clientes/proveedores) endpoint."""
    endpoint: str = "contacts"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def find_by_identification(self, identification: str, **filters: Any) -> List[Dict[str, Any]]:
        """Find every contact whose identification exactly matches ``identification``.

        The server is narrowed with ``identification=``, but its match mode is
        undocumented, so every page is read and only exact matches are kept.
        Comparison strips whitespace and removes dots and spaces; hyphens are preserved
        (the check digit is a separate field in Alegra). Duplicates are possible and are
        all returned.

        Args:
            identification (str): Identification to look for. Must not be blank.
            **filters: Extra query parameters forwarded to the server.

        Returns:
            List[Dict[str, Any]]: Matching contacts; empty when there is none.

        Raises:
            ValueError: If ``identification`` is blank or a forbidden pagination filter
                is passed (``start``, ``limit``, ``metadata``).
        """
        if identification is None or not str(identification).strip():
            raise ValueError("identification must not be blank")

        needle = _normalize_identification(identification)
        matches = []
        # The server gets the normalized value too, so a dotted or padded input still narrows
        for record in self.iter_all(identification=needle, **filters):
            value = _identification_value(record)
            if value is not None and _normalize_identification(value) == needle:
                matches.append(record)
        return matches


# For backward compatibility
contacts = Contacts

