import copy
import importlib
import json
import unittest
from unittest.mock import patch

import requests

import alegra

# `alegra.invoices` is shadowed by the legacy Invoices alias, and Python 3.10's mock.patch
# resolves dotted strings through attributes, so patch the module's `time` directly
_INVOICES_TIME = importlib.import_module('alegra.invoices').time
from alegra import AlegraClient

MARKER = "alegrapy:dedup:order-1"


def _timeout():
    return alegra.AlegraTimeoutError("timeout")


def _server_error():
    return alegra.AlegraServerError("boom", status_code=503)


def _not_sent():
    error = alegra.AlegraConnectionError("connection failed")
    error.__cause__ = requests.exceptions.ConnectTimeout("connect timed out")
    return error


class TestCreateOnce(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="user", token="token")

    def _wire(self, posts, lookups):
        posts_iter = iter(posts)
        lookups_iter = iter(lookups)
        calls = []

        def query(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method.lower() == 'post':
                item = next(posts_iter)
            else:
                item = next(lookups_iter)
            if isinstance(item, Exception):
                raise item
            return item

        self.client.query = query
        self.calls = calls

    def _posts(self):
        return [call for call in self.calls if call[0].lower() == 'post']

    def _gets(self):
        return [call for call in self.calls if call[0].lower() == 'get']

    @staticmethod
    def _params(**extra):
        return {"client": {"id": 126}, "items": [{"id": 1, "price": 10}], **extra}

    def test_precheck_returns_existing_invoice_without_posting(self):
        invoice = {"id": 5, "observations": MARKER}
        self._wire(posts=[], lookups=[[invoice]])

        result = self.client.invoices.create_once(self._params(), "order-1")

        self.assertIs(result, invoice)
        self.assertEqual(self._posts(), [])
        params = self._gets()[0][2]['params']
        self.assertEqual(params['client_id'], 126)
        self.assertEqual(params['order_field'], 'id')
        self.assertEqual(params['order_direction'], 'DESC')
        self.assertNotIn('status', params)

    def test_post_success_builds_payload_without_mutating_params(self):
        self._wire(posts=[{"id": 9}], lookups=[])
        params = self._params(observations="keep me")
        original = copy.deepcopy(params)

        result = self.client.invoices.create_once(params, " order-1 ", precheck=False)

        self.assertEqual(result, {"id": 9})
        self.assertEqual(len(self._posts()), 1)
        data = self._posts()[0][2]['data']
        self.assertEqual(data['observations'], "keep me\n" + MARKER)
        self.assertEqual(params, original)

    def test_empty_observations_gets_only_the_marker(self):
        self._wire(posts=[{"id": 9}], lookups=[])

        self.client.invoices.create_once(self._params(observations=""), "order-1", precheck=False)

        data = self._posts()[0][2]['data']
        self.assertEqual(data['observations'], MARKER)

    def test_observations_over_500_chars_raise_before_request(self):
        self._wire(posts=[], lookups=[])

        with self.assertRaises(ValueError):
            self.client.invoices.create_once(
                self._params(observations="x" * 490), "order-1", precheck=False)

        self.assertEqual(self.calls, [])

    def test_timeout_then_verification_finds_on_second_lookup(self):
        invoice = {"id": 10, "observations": MARKER}
        self._wire(posts=[_timeout()], lookups=[[], [invoice]])

        with patch.object(_INVOICES_TIME, 'monotonic', side_effect=[0.0, 0.0]):
            with patch.object(_INVOICES_TIME, 'sleep') as mock_sleep:
                result = self.client.invoices.create_once(
                    self._params(), "order-1", precheck=False, verify_window=10)

        self.assertIs(result, invoice)
        self.assertEqual(len(self._posts()), 1)
        mock_sleep.assert_called_once_with(1.0)

    def test_503_not_found_then_second_post_succeeds(self):
        self._wire(posts=[_server_error(), {"id": 11}], lookups=[[]])

        with patch.object(_INVOICES_TIME, 'monotonic', return_value=0.0):
            with patch.object(_INVOICES_TIME, 'sleep'):
                result = self.client.invoices.create_once(
                    self._params(), "order-1", precheck=False, verify_window=0)

        self.assertEqual(result, {"id": 11})
        posts = self._posts()
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0][2]['data'], posts[1][2]['data'])
        self.assertEqual(posts[1][2]['data']['observations'], MARKER)

    def test_two_ambiguous_posts_and_no_match_raise_quarantine_error(self):
        first, second = _timeout(), _timeout()
        self._wire(posts=[first, second], lookups=[[], []])

        with patch.object(_INVOICES_TIME, 'monotonic', return_value=0.0):
            with patch.object(_INVOICES_TIME, 'sleep'):
                with self.assertRaises(alegra.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.create_once(
                        self._params(), "order-1", precheck=False, verify_window=0)

        error = ctx.exception
        self.assertEqual(error.attempts, 2)
        self.assertEqual(error.dedup_key, "order-1")
        self.assertEqual(error.client_id, 126)
        self.assertEqual(error.resource, "invoices")
        self.assertIs(error.__cause__, second)
        self.assertEqual(error.payload['observations'], MARKER)

        serialized = error.to_dict()
        self.assertEqual(set(serialized), {
            'dedup_key', 'client_id', 'resource', 'payload', 'attempts',
            'status_code', 'response_body',
        })
        encoded = json.dumps(serialized)
        self.assertNotIn("Authorization", encoded)
        self.assertNotIn("user", encoded)

    def test_on_unverified_raise_stops_after_one_post(self):
        self._wire(posts=[_timeout()], lookups=[[]])

        with patch.object(_INVOICES_TIME, 'monotonic', return_value=0.0):
            with patch.object(_INVOICES_TIME, 'sleep'):
                with self.assertRaises(alegra.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.create_once(
                        self._params(), "order-1", precheck=False,
                        verify_window=0, on_unverified="raise")

        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(len(self._posts()), 1)

    def test_resubmitting_stored_payload_keeps_one_marker(self):
        payload = self.client.invoices._payload_with_marker(self._params(), "order-1")

        for _ in range(3):
            payload = self.client.invoices._payload_with_marker(payload, "order-1")

        lines = [line.strip() for line in payload["observations"].splitlines()]
        self.assertEqual(sum(1 for line in lines if line == MARKER), 1)

    def test_payload_with_another_marker_is_rejected(self):
        self._wire(posts=[], lookups=[])

        with self.assertRaises(ValueError):
            self.client.invoices.create_once(
                self._params(observations="alegrapy:dedup:other"),
                "order-1", precheck=False)

        self.assertEqual(self.calls, [])

    def test_to_dict_is_json_safe_without_mutating_payload(self):
        from datetime import date, datetime
        from decimal import Decimal

        error = alegra.AlegraUnverifiedCreateError(
            "unverified",
            dedup_key="order-1",
            client_id=1,
            payload={
                "price": Decimal("21008.40"),
                "day": date(2026, 11, 19),
                "at": datetime(2026, 11, 19, 10, 30),
                "tags": ("a", "b"),
                "ids": {3, 1, 2},
            },
        )

        data = error.to_dict()
        json.dumps(data)

        self.assertEqual(data["payload"]["price"], "21008.40")
        self.assertEqual(data["payload"]["day"], "2026-11-19")
        self.assertEqual(data["payload"]["at"], "2026-11-19T10:30:00")
        self.assertEqual(data["payload"]["tags"], ["a", "b"])
        self.assertEqual(data["payload"]["ids"], [1, 2, 3])

        self.assertIsInstance(error.payload["price"], Decimal)
        self.assertIsInstance(error.payload["tags"], tuple)
        self.assertIsInstance(error.payload["day"], date)

    def test_lookup_failure_raises_chained_without_second_post(self):
        lookup_error = alegra.AlegraServerError("lookup", status_code=502)
        self._wire(posts=[_server_error()], lookups=[lookup_error])

        with self.assertRaises(alegra.AlegraUnverifiedCreateError) as ctx:
            self.client.invoices.create_once(
                self._params(), "order-1", precheck=False, verify_window=10)

        self.assertIs(ctx.exception.__cause__, lookup_error)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(len(self._posts()), 1)

    def test_second_ambiguous_post_then_verification_finds_it(self):
        invoice = {"id": 12, "observations": MARKER}
        self._wire(posts=[_timeout(), _timeout()], lookups=[[], [invoice]])

        with patch.object(_INVOICES_TIME, 'monotonic', return_value=0.0):
            with patch.object(_INVOICES_TIME, 'sleep'):
                result = self.client.invoices.create_once(
                    self._params(), "order-1", precheck=False, verify_window=0)

        self.assertIs(result, invoice)
        self.assertEqual(len(self._posts()), 2)

    def test_second_ambiguous_post_then_lookup_failure(self):
        lookup_error = alegra.AlegraServerError("lookup", status_code=502)
        self._wire(posts=[_timeout(), _timeout()], lookups=[[], lookup_error])

        with patch.object(_INVOICES_TIME, 'monotonic', return_value=0.0):
            with patch.object(_INVOICES_TIME, 'sleep'):
                with self.assertRaises(alegra.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.create_once(
                        self._params(), "order-1", precheck=False, verify_window=0)

        self.assertIs(ctx.exception.__cause__, lookup_error)
        self.assertEqual(ctx.exception.attempts, 2)
        self.assertEqual(len(self._posts()), 2)

    def test_end_to_end_post_cap_through_query(self):
        from unittest.mock import MagicMock

        def response(status, body):
            mock = MagicMock()
            mock.status_code = status
            mock.text = body
            mock.json.return_value = json.loads(body)
            mock.headers = {}
            return mock

        client = AlegraClient(user="user", token="token")
        responses = [
            requests.exceptions.ReadTimeout("timeout"),
            response(200, "[]"),
            response(503, '{"message": "boom"}'),
            response(200, "[]"),
        ]

        with patch('requests.Session.request', side_effect=responses) as mock_request:
            with patch.object(_INVOICES_TIME, 'monotonic', return_value=0.0):
                with patch.object(_INVOICES_TIME, 'sleep'):
                    with self.assertRaises(alegra.AlegraUnverifiedCreateError) as ctx:
                        client.invoices.create_once(
                            self._params(), "order-1", precheck=False, verify_window=0)

        posts = [
            call for call in mock_request.call_args_list
            if (call.kwargs.get('method') or call.args[0]).lower() == 'post'
        ]
        self.assertEqual(len(posts), 2)
        self.assertEqual(ctx.exception.attempts, 2)

    def test_post_validation_error_is_raised_unchanged(self):
        error = alegra.AlegraValidationError("invalid", status_code=400)
        self._wire(posts=[error], lookups=[])

        with self.assertRaises(alegra.AlegraValidationError) as ctx:
            self.client.invoices.create_once(self._params(), "order-1", precheck=False)

        self.assertIs(ctx.exception, error)
        self.assertEqual(self._gets(), [])

    def test_not_sent_connection_error_is_raised_unchanged(self):
        error = _not_sent()
        self._wire(posts=[error], lookups=[])

        with self.assertRaises(alegra.AlegraConnectionError) as ctx:
            self.client.invoices.create_once(self._params(), "order-1", precheck=False)

        self.assertIs(ctx.exception, error)
        self.assertEqual(self._gets(), [])

    def test_second_post_rejected_non_ambiguously_is_quarantined(self):
        rejection = alegra.AlegraValidationError("invalid", status_code=400)
        self._wire(posts=[_server_error(), rejection], lookups=[[]])

        with patch.object(_INVOICES_TIME, 'monotonic', return_value=0.0):
            with patch.object(_INVOICES_TIME, 'sleep'):
                with self.assertRaises(alegra.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.create_once(
                        self._params(), "order-1", precheck=False, verify_window=0)

        self.assertEqual(ctx.exception.attempts, 2)
        self.assertIs(ctx.exception.__cause__, rejection)

    def test_reconcile_matches_the_marker_as_a_whole_line(self):
        no_match = [{"id": 1, "observations": "alegrapy:dedup:order-12"}]
        self._wire(posts=[], lookups=[no_match])
        self.assertIsNone(self.client.invoices.reconcile("order-1", 126))

        with_lines = [{"id": 2, "observations": "nota\nalegrapy:dedup:order-1\nfin"}]
        self._wire(posts=[], lookups=[with_lines])
        self.assertIs(self.client.invoices.reconcile("order-1", 126), with_lines[0])

        self._wire(posts=[], lookups=[[{"id": 3, "observations": None}]])
        self.assertIsNone(self.client.invoices.reconcile("order-1", 126))

    def test_reconcile_honors_lookup_pages(self):
        full_page = [{"id": index, "observations": None} for index in range(30)]
        self._wire(posts=[], lookups=[full_page])
        self.assertIsNone(self.client.invoices.reconcile("order-1", 126, lookup_pages=1))
        self.assertEqual(len(self._gets()), 1)

        self._wire(posts=[], lookups=[full_page, []])
        self.assertIsNone(self.client.invoices.reconcile("order-1", 126, lookup_pages=2))
        self.assertEqual(len(self._gets()), 2)

    def test_verification_stops_when_window_elapses(self):
        self._wire(posts=[_timeout()], lookups=[[], []])

        with patch.object(_INVOICES_TIME, 'monotonic', side_effect=[0.0, 29.0, 40.0]):
            with patch.object(_INVOICES_TIME, 'sleep') as mock_sleep:
                with self.assertRaises(alegra.AlegraUnverifiedCreateError):
                    self.client.invoices.create_once(
                        self._params(), "order-1", precheck=False,
                        verify_window=30, on_unverified="raise")

        self.assertEqual(len(self._gets()), 2)
        mock_sleep.assert_called_once_with(1.0)

    def test_validation_errors_send_no_request(self):
        cases = [
            (self._params(), ""),
            (self._params(), "   "),
            (self._params(), "a" * 65),
            (self._params(), "bad/key"),
            (self._params(), 123),
            ({"items": []}, "order-1"),
            ({"client": {}}, "order-1"),
            ({"client": None}, "order-1"),
        ]
        for params, key in cases:
            with self.subTest(key=key, params=params):
                self._wire(posts=[], lookups=[])
                with self.assertRaises(ValueError):
                    self.client.invoices.create_once(params, key, precheck=False)
                self.assertEqual(self.calls, [])

        invalid_options = [
            {"on_unverified": "ignore"},
            {"verify_window": -1},
            {"lookup_pages": 0},
            {"lookup_pages": 1.5},
            {"lookup_pages": True},
        ]
        for options in invalid_options:
            with self.subTest(**options):
                self._wire(posts=[], lookups=[])
                with self.assertRaises(ValueError):
                    self.client.invoices.create_once(
                        self._params(), "order-1", precheck=False, **options)
                self.assertEqual(self.calls, [])

    def test_reconcile_validates_its_arguments(self):
        self._wire(posts=[], lookups=[])
        with self.assertRaises(ValueError):
            self.client.invoices.reconcile("", 126)
        with self.assertRaises(ValueError):
            self.client.invoices.reconcile("order-1", None)
        with self.assertRaises(ValueError):
            self.client.invoices.reconcile("order-1", 126, lookup_pages=0)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
