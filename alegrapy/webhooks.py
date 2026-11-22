from dataclasses import dataclass
import enum
import json
import numbers
import re
from typing import Any, Dict, List, Optional, Union

from alegrapy.actions import validate_id

_SCHEME_PREFIX = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*://')
_MAX_URL_BYTES = 1024


class AlegraWebhookError(ValueError):
    """Raised when an incoming Alegra webhook payload is malformed or unsupported."""


class WebhookEventType(str, enum.Enum):
    """Webhook event subjects documented by Alegra."""
    NEW_INVOICE = "new-invoice"
    EDIT_INVOICE = "edit-invoice"
    DELETE_INVOICE = "delete-invoice"
    NEW_BILL = "new-bill"
    EDIT_BILL = "edit-bill"
    DELETE_BILL = "delete-bill"
    NEW_CLIENT = "new-client"
    EDIT_CLIENT = "edit-client"
    DELETE_CLIENT = "delete-client"
    NEW_ITEM = "new-item"
    EDIT_ITEM = "edit-item"
    DELETE_ITEM = "delete-item"


def _normalize_url(url: Any) -> str:
    if not isinstance(url, str):
        raise ValueError("url must be a string")
    cleaned = url.strip()
    if cleaned.lower().startswith("https://"):
        cleaned = cleaned[len("https://"):]
    elif _SCHEME_PREFIX.match(cleaned):
        raise ValueError("url must not use http:// or non-HTTPS schemes")
    if not cleaned:
        raise ValueError("url must not be empty")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError("url must not contain whitespace")
    if len(cleaned.encode("utf-8")) > _MAX_URL_BYTES:
        raise ValueError(f"url must be at most {_MAX_URL_BYTES} UTF-8 bytes")
    return cleaned


def _validate_event(event: Any) -> WebhookEventType:
    if isinstance(event, WebhookEventType):
        return event
    if isinstance(event, str):
        try:
            return WebhookEventType(event)
        except ValueError:
            pass
    allowed = ", ".join(item.value for item in WebhookEventType)
    raise ValueError(f"event must be one of: {allowed}")


@dataclass(frozen=True)
class WebhookEvent:
    """Typed representation of a parsed Alegra webhook delivery."""
    type: WebhookEventType
    resource: str
    action: str
    resource_id: str
    data: Dict[str, Any]
    raw: Dict[str, Any]

    def fetch(self, client: 'AlegraClient') -> Optional[Any]:
        """Re-read the referenced resource from Alegra before trusting the payload.

        Returns ``None`` without making a request for ``delete-*`` events.
        """
        if self.action == "delete":
            return None
        if self.resource == "invoice":
            return client.invoices.read(self.resource_id)
        if self.resource == "client":
            return client.contacts.read(self.resource_id)
        if self.resource == "item":
            return client.items.read(self.resource_id)
        if self.resource == "bill":
            return client.bills.read(self.resource_id)
        raise AlegraWebhookError(f"Unsupported webhook resource {self.resource!r}")


def parse_webhook(body: Union[bytes, str, Dict[str, Any]]) -> WebhookEvent:
    """Parse and validate an incoming Alegra webhook payload into a :class:`WebhookEvent`.

    Args:
        body (bytes, str, or dict): Raw JSON request body or already-parsed dict.

    Returns:
        WebhookEvent: Parsed, typed webhook event.

    Raises:
        AlegraWebhookError: If the payload is not valid JSON, not a JSON object,
            has an unknown/missing ``subject``, or lacks the matching resource object
            with a non-blank ``id``.
    """
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AlegraWebhookError("Webhook body is not valid UTF-8") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise AlegraWebhookError("Webhook body is not valid JSON") from exc
    elif isinstance(body, str):
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise AlegraWebhookError("Webhook body is not valid JSON") from exc
    elif isinstance(body, dict):
        payload = body
    else:
        raise AlegraWebhookError("Webhook body must be bytes, str, or dict")

    if not isinstance(payload, dict):
        raise AlegraWebhookError("Webhook payload must be a JSON object")

    subject = payload.get("subject")
    if not isinstance(subject, str):
        raise AlegraWebhookError("Webhook payload is missing a valid 'subject'")
    try:
        event_type = WebhookEventType(subject)
    except ValueError as exc:
        raise AlegraWebhookError(f"Unknown webhook subject {subject!r}") from exc

    action, resource = event_type.value.split("-", 1)
    message = payload.get("message")
    if not isinstance(message, dict):
        raise AlegraWebhookError("Webhook payload is missing a 'message' object")

    data = message.get(resource)
    if not isinstance(data, dict):
        raise AlegraWebhookError(f"Webhook message is missing the {resource!r} object")

    raw_id = data.get("id")
    if isinstance(raw_id, bool) or raw_id is None:
        raise AlegraWebhookError(f"Webhook {resource!r} object is missing 'id'")
    if isinstance(raw_id, str):
        raw_id = raw_id.strip()
    # The payload is unauthenticated: only accept ids that cannot alter a URL path
    try:
        resource_id = str(validate_id(raw_id))
    except ValueError as exc:
        raise AlegraWebhookError(f"Webhook {resource!r} object has an invalid 'id'") from exc

    return WebhookEvent(
        type=event_type,
        resource=resource,
        action=action,
        resource_id=resource_id,
        data=data,
        raw=payload,
    )


class Webhooks:
    """Operations related to webhook subscriptions (``/webhooks/subscriptions``)."""
    endpoint: str = "webhooks/subscriptions"

    def __init__(self, client: 'AlegraClient') -> None:
        """Initialize the resource with an explicit ``AlegraClient``."""
        self._client = client

    def list(self, page: Optional[int] = None) -> List[Dict[str, Any]]:
        """List webhook subscriptions, optionally for a 1-based ``page`` (10 per page).

        Without ``page``, Alegra returns all subscriptions. Unwraps ``subscriptions``.
        """
        params: Optional[Dict[str, Any]] = None
        if page is not None:
            if isinstance(page, bool) or not isinstance(page, numbers.Integral) or page < 1:
                raise ValueError("page must be None or an integer >= 1")
            params = {"page": int(page)}
        endpoint = f"{self._client.url}{self.endpoint}"
        resp = self._client.query('get', endpoint, params=params)
        if isinstance(resp, dict) and isinstance(resp.get("subscriptions"), list):
            return resp["subscriptions"]
        return resp  # type: ignore[return-value]

    def get(self, id: Union[int, str]) -> Any:
        """Retrieve a single webhook subscription by ID."""
        valid_id = validate_id(id)
        endpoint = f"{self._client.url}{self.endpoint}/{valid_id}"
        return self._client.query('get', endpoint)

    def create(self, event: Union[WebhookEventType, str], url: str) -> Dict[str, Any]:
        """Create a webhook subscription and return the ``subscription`` object.

        Note:
            Before creating, Alegra POSTs ``{}`` to ``https://<url>`` and requires a
            2xx response in under 5 seconds. The wrapper ``message`` from Alegra's
            response is dropped and only ``subscription`` is returned.
        """
        valid_event = _validate_event(event)
        normalized_url = _normalize_url(url)
        endpoint = f"{self._client.url}{self.endpoint}"
        resp = self._client.query(
            'post', endpoint, data={"event": valid_event.value, "url": normalized_url}
        )
        if isinstance(resp, dict) and isinstance(resp.get("subscription"), dict):
            return resp["subscription"]
        return resp  # type: ignore[return-value]

    def update(self, id: Union[int, str], url: str) -> Dict[str, Any]:
        """Update a subscription's URL and return the ``subscription`` object.

        Calling ``PUT`` (even with the same URL) also reactivates a ``SUSPENDED``
        subscription and resets its failure counter. The ``event`` cannot be changed.
        """
        valid_id = validate_id(id)
        normalized_url = _normalize_url(url)
        endpoint = f"{self._client.url}{self.endpoint}/{valid_id}"
        resp = self._client.query('put', endpoint, data={"url": normalized_url})
        if isinstance(resp, dict) and isinstance(resp.get("subscription"), dict):
            return resp["subscription"]
        return resp  # type: ignore[return-value]

    def delete(self, id: Union[int, str]) -> Any:
        """Delete a webhook subscription by ID."""
        valid_id = validate_id(id)
        endpoint = f"{self._client.url}{self.endpoint}/{valid_id}"
        return self._client.query('delete', endpoint)
