import json
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import (
    AlegraClient,
    AlegraValidationError,
    AlegraWebhookError,
    RetryPolicy,
    WebhookEvent,
    WebhookEventType,
    Webhooks,
    parse_webhook,
)


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestWebhooks(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_cached_property_and_exports(self):
        self.assertIsInstance(self.client.webhooks, Webhooks)
        self.assertIs(self.client.webhooks, self.client.webhooks)
        for name in ("Webhooks", "WebhookEventType", "WebhookEvent", "parse_webhook", "AlegraWebhookError"):
            with self.subTest(name=name):
                self.assertIn(name, alegrapy.__all__)
                self.assertTrue(hasattr(alegrapy, name))
        self.assertTrue(issubclass(AlegraWebhookError, ValueError))

    def test_list_get_delete_create_and_update_subscriptions(self):
        sub = {"id": 12, "event": "new-invoice", "url": "x.com/hook", "status": "ACTIVE"}
        with patch.object(
            self.client.session, "request", return_value=_mock_response({"subscriptions": [sub]})
        ) as mock_req:
            self.assertEqual(self.client.webhooks.list(), [sub])
            kw = mock_req.call_args.kwargs
            self.assertEqual(kw["method"].lower(), "get")
            self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/webhooks/subscriptions")
            self.assertIsNone(kw.get("params"))

            self.client.webhooks.list(page=2)
            self.assertEqual(mock_req.call_args.kwargs["params"], {"page": 2})

        with patch.object(
            self.client.session, "request", return_value=_mock_response(sub)
        ) as mock_req:
            self.assertEqual(self.client.webhooks.get(12), sub)
            self.assertEqual(
                mock_req.call_args.kwargs["url"],
                "https://api.alegra.com/api/v1/webhooks/subscriptions/12",
            )

        del_body = {"message": "Suscripción eliminada correctamente!"}
        with patch.object(
            self.client.session, "request", return_value=_mock_response(del_body)
        ) as mock_req:
            self.assertEqual(self.client.webhooks.delete(12), del_body)
            self.assertEqual(mock_req.call_args.kwargs["method"].lower(), "delete")

        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response({"message": "Created", "subscription": sub}, status=201),
        ) as mock_req:
            created = self.client.webhooks.create(WebhookEventType.NEW_INVOICE, "  https://x.com/hook ")
            self.assertEqual(created, sub)
            kw = mock_req.call_args.kwargs
            self.assertEqual(kw["method"].lower(), "post")
            self.assertEqual(kw["json"], {"event": "new-invoice", "url": "x.com/hook"})

        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response({"message": "Updated", "subscription": sub}),
        ) as mock_req:
            updated = self.client.webhooks.update(12, "https://x.com/hook2")
            self.assertEqual(updated, sub)
            kw = mock_req.call_args.kwargs
            self.assertEqual(kw["method"].lower(), "put")
            self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/webhooks/subscriptions/12")
            self.assertEqual(kw["json"], {"url": "x.com/hook2"})

    def test_subscriptions_validation_and_400(self):
        with patch.object(self.client.session, "request") as mock_req:
            for bad_page in (0, -1, True, "2"):
                with self.subTest(page=bad_page):
                    with self.assertRaises(ValueError):
                        self.client.webhooks.list(page=bad_page)
            for bad_event in ("new_invoice", "NEW-INVOICE", 123):
                with self.subTest(event=bad_event):
                    with self.assertRaises(ValueError):
                        self.client.webhooks.create(bad_event, "x.com/hook")
            for bad_url in ("http://x.com", "ftp://x.com", "a b.com", "", "   ", "a" * 1025, 123):
                with self.subTest(url=bad_url):
                    with self.assertRaises(ValueError):
                        self.client.webhooks.create("new-invoice", bad_url)
                    with self.assertRaises(ValueError):
                        self.client.webhooks.update(1, bad_url)
            for call_fn in (
                lambda: self.client.webhooks.get("1/../x"),
                lambda: self.client.webhooks.delete("1/../x"),
                lambda: self.client.webhooks.update("1/../x", "x.com/hook"),
            ):
                with self.assertRaises(ValueError):
                    call_fn()
            mock_req.assert_not_called()

        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response({"message": "Dominio inválido"}, status=400),
        ):
            with self.assertRaises(AlegraValidationError):
                self.client.webhooks.create("new-invoice", "localhost/hook")

    def test_parse_webhook_all_subjects_and_shapes(self):
        for evt in WebhookEventType:
            action, resource = evt.value.split("-", 1)
            body = {
                "subject": evt.value,
                "message": {
                    resource: {
                        "id": 123 if resource == "invoice" else "456",
                        "total": "2000.0000000000",
                        "name": "" if evt is WebhookEventType.DELETE_CLIENT else "Test",
                    }
                },
            }
            for raw_input in (body, json.dumps(body), json.dumps(body).encode("utf-8")):
                with self.subTest(subject=evt.value, input_type=type(raw_input).__name__):
                    parsed = parse_webhook(raw_input)
                    self.assertIsInstance(parsed, WebhookEvent)
                    self.assertEqual(parsed.type, evt)
                    self.assertEqual(parsed.action, action)
                    self.assertEqual(parsed.resource, resource)
                    self.assertEqual(parsed.resource_id, "123" if resource == "invoice" else "456")
                    self.assertEqual(parsed.data["total"], "2000.0000000000")
                    self.assertEqual(parsed.raw, body)

    def test_parse_webhook_malformed_inputs_raise_webhook_error(self):
        bad_inputs = [
            b"{not json",
            "[]",
            123,
            {},
            {"subject": "unknown-event", "message": {"invoice": {"id": "1"}}},
            {"subject": "new-invoice"},
            {"subject": "new-invoice", "message": {"client": {"id": "1"}}},
            {"subject": "new-invoice", "message": {"invoice": "bad"}},
            {"subject": "new-invoice", "message": {"invoice": {}}},
            {"subject": "new-invoice", "message": {"invoice": {"id": "  "}}},
            {"subject": "new-invoice", "message": {"invoice": {"id": True}}},
            # Webhooks are unauthenticated: ids that could alter a URL path are rejected
            {"subject": "new-invoice", "message": {"invoice": {"id": "1/../users/self"}}},
            {"subject": "new-invoice", "message": {"invoice": {"id": "1?x=2"}}},
            {"subject": "new-invoice", "message": {"invoice": {"id": -5}}},
        ]
        for bad in bad_inputs:
            with self.subTest(bad=bad):
                with self.assertRaises(AlegraWebhookError) as ctx:
                    parse_webhook(bad)
                self.assertIsInstance(ctx.exception, ValueError)

    def test_webhook_event_fetch(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response({"id": "10"})
        ) as mock_req:
            inv_evt = parse_webhook({"subject": "new-invoice", "message": {"invoice": {"id": "10"}}})
            self.assertEqual(inv_evt.fetch(self.client), {"id": "10"})
            self.assertEqual(mock_req.call_args.kwargs["url"], "https://api.alegra.com/api/v1/invoices/10")

            cli_evt = parse_webhook({"subject": "edit-client", "message": {"client": {"id": "20"}}})
            cli_evt.fetch(self.client)
            self.assertEqual(mock_req.call_args.kwargs["url"], "https://api.alegra.com/api/v1/contacts/20")

            item_evt = parse_webhook({"subject": "new-item", "message": {"item": {"id": "30"}}})
            item_evt.fetch(self.client)
            self.assertEqual(mock_req.call_args.kwargs["url"], "https://api.alegra.com/api/v1/items/30")

        with patch.object(self.client.session, "request") as mock_req:
            del_evt = parse_webhook({"subject": "delete-client", "message": {"client": {"id": "20", "name": ""}}})
            self.assertIsNone(del_evt.fetch(self.client))

            bill_evt = parse_webhook({"subject": "new-bill", "message": {"bill": {"id": "40"}}})
            with self.assertRaises(NotImplementedError):
                bill_evt.fetch(self.client)
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
