import copy
import importlib
import json
import unittest
from unittest.mock import MagicMock, patch

import requests

import alegrapy
from alegrapy import AlegraClient, RetryPolicy

# `alegrapy.<resource>` is shadowed by legacy aliases on the package object, and
# Python 3.10's mock.patch resolves dotted strings through attributes, so patch via
# `importlib.import_module` + `patch.object` on the `_create_once` module's `time`.
_CREATE_ONCE_TIME = importlib.import_module("alegrapy._create_once").time

MARKER = "alegrapy:dedup:pay-1"


def _timeout():
    return alegrapy.AlegraTimeoutError("timeout")


def _server_error():
    return alegrapy.AlegraServerError("boom", status_code=503)


def _not_sent():
    error = alegrapy.AlegraConnectionError("connection failed")
    error.__cause__ = requests.exceptions.ConnectTimeout("connect timed out")
    return error


class TestPaymentsCreateOnce(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(
            user="user", token="token", retry=RetryPolicy(max_retries=0)
        )

    def _wire(self, posts, lookups):
        posts_iter = iter(posts)
        lookups_iter = iter(lookups)
        calls = []

        def query(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method.lower() == "post":
                item = next(posts_iter)
            else:
                item = next(lookups_iter)
            if isinstance(item, Exception):
                raise item
            return item

        self.client.query = query
        self.calls = calls

    def _posts(self):
        return [call for call in self.calls if call[0].lower() == "post"]

    def _gets(self):
        return [call for call in self.calls if call[0].lower() == "get"]

    @staticmethod
    def _params(**extra):
        base = {
            "date": "2026-11-20",
            "bankAccount": {"id": 1},
            "paymentMethod": "transfer",
            "type": "in",
            "client": {"id": 126},
            "invoices": [{"id": 500, "amount": 100}],
        }
        base.update(extra)
        return base

    @staticmethod
    def _response(status, body):
        resp = MagicMock(status_code=status, text=json.dumps(body), headers={})
        resp.json.return_value = body
        return resp

    def test_precheck_returns_existing_payment_without_posting(self):
        payment = {"id": 5, "type": "in", "client": {"id": 126}, "observations": MARKER}
        self._wire(posts=[], lookups=[[payment]])

        result = self.client.payments.create_once(self._params(), "pay-1")

        self.assertIs(result, payment)
        self.assertEqual(self._posts(), [])
        params = self._gets()[0][2]["params"]
        self.assertEqual(params["client_id"], 126)
        self.assertEqual(params["type"], "in")
        self.assertEqual(params["order_field"], "id")
        self.assertEqual(params["order_direction"], "DESC")
        self.assertNotIn("status", params)

    def test_post_success_builds_payload_without_mutating_params(self):
        self._wire(posts=[{"id": 9}], lookups=[])
        params = self._params(observations="keep me")
        original = copy.deepcopy(params)

        result = self.client.payments.create_once(params, " pay-1 ", precheck=False)

        self.assertEqual(result, {"id": 9})
        self.assertEqual(len(self._posts()), 1)
        data = self._posts()[0][2]["data"]
        self.assertEqual(data["observations"], "keep me\n" + MARKER)
        self.assertEqual(params, original)

    def test_empty_observations_gets_only_the_marker(self):
        self._wire(posts=[{"id": 9}], lookups=[])

        self.client.payments.create_once(
            self._params(observations=""), "pay-1", precheck=False
        )

        data = self._posts()[0][2]["data"]
        self.assertEqual(data["observations"], MARKER)

    def test_observations_over_500_chars_raise_before_request(self):
        self._wire(posts=[], lookups=[])

        with self.assertRaises(ValueError):
            self.client.payments.create_once(
                self._params(observations="x" * 490), "pay-1", precheck=False
            )

        self.assertEqual(self.calls, [])

    def test_resubmitting_stored_payload_keeps_one_marker(self):
        self._wire(posts=[{"id": 9}], lookups=[])
        params = self._params(observations=f"nota\n{MARKER}")

        self.client.payments.create_once(params, "pay-1", precheck=False)

        data = self._posts()[0][2]["data"]
        lines = [line.strip() for line in data["observations"].splitlines()]
        self.assertEqual(sum(1 for line in lines if line == MARKER), 1)

    def test_payload_with_another_marker_is_rejected(self):
        self._wire(posts=[], lookups=[])

        with self.assertRaises(ValueError):
            self.client.payments.create_once(
                self._params(observations="alegrapy:dedup:other"),
                "pay-1",
                precheck=False,
            )

        self.assertEqual(self.calls, [])

    def test_timeout_then_verification_finds_on_second_lookup(self):
        payment = {"id": 10, "type": "in", "client": {"id": 126}, "observations": MARKER}
        self._wire(posts=[_timeout()], lookups=[[], [payment]])

        with patch.object(_CREATE_ONCE_TIME, "monotonic", side_effect=[0.0, 0.0]):
            with patch.object(_CREATE_ONCE_TIME, "sleep") as mock_sleep:
                result = self.client.payments.create_once(
                    self._params(), "pay-1", precheck=False, verify_window=10
                )

        self.assertIs(result, payment)
        self.assertEqual(len(self._posts()), 1)
        mock_sleep.assert_called_once_with(1.0)

    def test_503_not_found_then_second_post_succeeds(self):
        self._wire(posts=[_server_error(), {"id": 11}], lookups=[[]])

        with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE_TIME, "sleep"):
                result = self.client.payments.create_once(
                    self._params(), "pay-1", precheck=False, verify_window=0
                )

        self.assertEqual(result, {"id": 11})
        posts = self._posts()
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0][2]["data"], posts[1][2]["data"])
        self.assertEqual(posts[1][2]["data"]["observations"], MARKER)

    def test_two_ambiguous_posts_and_no_match_raise_quarantine_error(self):
        first, second = _timeout(), _timeout()
        self._wire(posts=[first, second], lookups=[[], []])

        with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE_TIME, "sleep"):
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.payments.create_once(
                        self._params(), "pay-1", precheck=False, verify_window=0
                    )

        error = ctx.exception
        self.assertEqual(error.attempts, 2)
        self.assertEqual(error.dedup_key, "pay-1")
        self.assertEqual(error.client_id, 126)
        self.assertEqual(error.resource, "payments")
        self.assertIs(error.__cause__, second)
        self.assertEqual(error.payload["observations"], MARKER)

        serialized = error.to_dict()
        self.assertEqual(
            set(serialized),
            {
                "dedup_key",
                "client_id",
                "resource",
                "payload",
                "attempts",
                "status_code",
                "response_body",
            },
        )
        encoded = json.dumps(serialized)
        self.assertNotIn("Authorization", encoded)
        self.assertNotIn("user", encoded)

    def test_on_unverified_raise_stops_after_one_post(self):
        self._wire(posts=[_timeout()], lookups=[[]])

        with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE_TIME, "sleep"):
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.payments.create_once(
                        self._params(),
                        "pay-1",
                        precheck=False,
                        verify_window=0,
                        on_unverified="raise",
                    )

        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(ctx.exception.resource, "payments")
        self.assertEqual(len(self._posts()), 1)

    def test_lookup_failure_raises_chained_without_second_post(self):
        lookup_error = alegrapy.AlegraServerError("lookup", status_code=502)
        self._wire(posts=[_server_error()], lookups=[lookup_error])

        with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
            self.client.payments.create_once(
                self._params(), "pay-1", precheck=False, verify_window=10
            )

        self.assertIs(ctx.exception.__cause__, lookup_error)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(len(self._posts()), 1)

    def test_post_validation_error_is_raised_unchanged_without_lookup(self):
        error = alegrapy.AlegraValidationError("invalid", status_code=400)
        self._wire(posts=[error], lookups=[])

        with self.assertRaises(alegrapy.AlegraValidationError) as ctx:
            self.client.payments.create_once(self._params(), "pay-1", precheck=False)

        self.assertIs(ctx.exception, error)
        self.assertEqual(self._gets(), [])

    def test_not_sent_connection_error_is_raised_unchanged(self):
        error = _not_sent()
        self._wire(posts=[error], lookups=[])

        with self.assertRaises(alegrapy.AlegraConnectionError) as ctx:
            self.client.payments.create_once(self._params(), "pay-1", precheck=False)

        self.assertIs(ctx.exception, error)
        self.assertEqual(self._gets(), [])

    def test_create_without_client_omits_client_id_from_lookup(self):
        params = self._params()
        del params["client"]
        payment = {"id": 20, "type": "in", "client": None, "observations": MARKER}
        self._wire(posts=[], lookups=[[payment]])

        result = self.client.payments.create_once(params, "pay-1")

        self.assertIs(result, payment)
        self.assertEqual(self._posts(), [])
        get_params = self._gets()[0][2]["params"]
        self.assertNotIn("client_id", get_params)
        self.assertEqual(get_params["type"], "in")

    def test_create_without_client_quarantines_with_none_client_id(self):
        params = self._params()
        del params["client"]
        self._wire(posts=[_timeout()], lookups=[[]])

        with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE_TIME, "sleep"):
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.payments.create_once(
                        params,
                        "pay-1",
                        precheck=False,
                        verify_window=0,
                        on_unverified="raise",
                    )

        self.assertIsNone(ctx.exception.client_id)
        self.assertEqual(ctx.exception.resource, "payments")

    def test_create_accepts_bare_client_id(self):
        payment = {"id": 21, "type": "in", "client": 126, "observations": MARKER}
        self._wire(posts=[], lookups=[[payment]])

        result = self.client.payments.create_once(self._params(client=126), "pay-1")

        self.assertIs(result, payment)
        self.assertEqual(self._gets()[0][2]["params"]["client_id"], 126)

    def test_reconcile_client_side_rechecks_client_id_and_type(self):
        records = [
            # Wrong client (null)
            {"id": 1, "type": "in", "client": None, "observations": MARKER},
            # Wrong client (different id)
            {"id": 2, "type": "in", "client": {"id": 999}, "observations": MARKER},
            # Wrong type
            {"id": 3, "type": "out", "client": {"id": 126}, "observations": MARKER},
            # Exact match
            {"id": 5, "type": "in", "client": {"id": 126}, "observations": MARKER},
        ]
        self._wire(posts=[], lookups=[records])

        found = self.client.payments.reconcile("pay-1", client_id=126, type="in")

        self.assertIs(found, records[3])

    def test_reconcile_matches_record_without_type_field(self):
        # The server was asked to filter by type; a list record that omits ``type`` must
        # still match, otherwise an existing payment is missed and "retry" posts again
        record = {"id": 4, "client": {"id": 126}, "observations": MARKER}
        self._wire(posts=[], lookups=[[record]])

        self.assertIs(self.client.payments.reconcile("pay-1", client_id=126, type="in"), record)

    def test_reconcile_compares_client_ids_across_str_and_int(self):
        for requested, stored in (("126", 126), (126, "126"), ("126", {"id": 126})):
            with self.subTest(requested=requested, stored=stored):
                record = {"id": 6, "type": "in", "client": stored, "observations": MARKER}
                self._wire(posts=[], lookups=[[record]])
                self.assertIs(self.client.payments.reconcile("pay-1", client_id=requested), record)

    def test_reconcile_skips_null_client_when_client_id_requested(self):
        records = [{"id": 1, "type": "in", "client": None, "observations": MARKER}]
        self._wire(posts=[], lookups=[records])

        self.assertIsNone(self.client.payments.reconcile("pay-1", client_id=126))

    def test_reconcile_matches_marker_as_whole_line_and_ignores_missing_observations(self):
        self._wire(
            posts=[],
            lookups=[
                [
                    {"id": 1, "observations": "alegrapy:dedup:pay-12"},
                    {"id": 2, "observations": None},
                    {"id": 3},
                ]
            ],
        )
        self.assertIsNone(self.client.payments.reconcile("pay-1"))

        match = {"id": 4, "observations": f"nota\n{MARKER}\nfin"}
        self._wire(posts=[], lookups=[[match]])
        self.assertIs(self.client.payments.reconcile("pay-1"), match)

    def test_reconcile_honors_lookup_pages(self):
        full_page = [{"id": index, "observations": None} for index in range(30)]
        self._wire(posts=[], lookups=[full_page])
        self.assertIsNone(self.client.payments.reconcile("pay-1", lookup_pages=1))
        self.assertEqual(len(self._gets()), 1)

        self._wire(posts=[], lookups=[full_page, []])
        self.assertIsNone(self.client.payments.reconcile("pay-1", lookup_pages=2))
        self.assertEqual(len(self._gets()), 2)

    def test_validation_errors_send_no_request(self):
        cases = [
            (self._params(), ""),
            (self._params(), "   "),
            (self._params(), "a" * 65),
            (self._params(), "bad/key"),
            (self._params(), 123),
            ("not-a-dict", "pay-1"),
            (self._params(type="transfer"), "pay-1"),
            (self._params(client="bad/id"), "pay-1"),
        ]
        for params, key in cases:
            with self.subTest(key=key, params=params):
                self._wire(posts=[], lookups=[])
                with self.assertRaises(ValueError):
                    self.client.payments.create_once(params, key, precheck=False)
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
                    self.client.payments.create_once(
                        self._params(), "pay-1", precheck=False, **options
                    )
                self.assertEqual(self.calls, [])

    def test_reconcile_validates_its_arguments(self):
        self._wire(posts=[], lookups=[])
        with self.assertRaises(ValueError):
            self.client.payments.reconcile("")
        with self.assertRaises(ValueError):
            self.client.payments.reconcile("pay-1", client_id="../1")
        with self.assertRaises(ValueError):
            self.client.payments.reconcile("pay-1", type="transfer")
        with self.assertRaises(ValueError):
            self.client.payments.reconcile("pay-1", lookup_pages=0)
        self.assertEqual(self.calls, [])

    def test_create_once_posts_to_payments_url_through_real_query(self):
        created = {"id": 99, "observations": MARKER}
        with patch.object(
            self.client.session, "request", return_value=self._response(200, created)
        ) as mock_request:
            result = self.client.payments.create_once(
                self._params(observations="Pago factura"), "pay-1", precheck=False
            )

        self.assertEqual(result, created)
        mock_request.assert_called_once()
        kwargs = mock_request.call_args.kwargs
        self.assertEqual(kwargs["method"].lower(), "post")
        self.assertEqual(kwargs["url"], "https://api.alegra.com/api/v1/payments")
        self.assertEqual(
            kwargs["json"]["observations"], f"Pago factura\n{MARKER}"
        )

    def test_reconcile_gets_payments_url_with_filters_through_real_query(self):
        payment = {"id": 55, "type": "in", "client": {"id": 126}, "observations": MARKER}
        with patch.object(
            self.client.session, "request", return_value=self._response(200, [payment])
        ) as mock_request:
            result = self.client.payments.reconcile("pay-1", client_id=126, type="in")

        self.assertEqual(result, payment)
        mock_request.assert_called_once()
        kwargs = mock_request.call_args.kwargs
        self.assertEqual(kwargs["method"].lower(), "get")
        self.assertEqual(kwargs["url"], "https://api.alegra.com/api/v1/payments")
        self.assertEqual(
            kwargs["params"],
            {
                "start": 0,
                "limit": 30,
                "order_direction": "DESC",
                "order_field": "id",
                "client_id": 126,
                "type": "in",
            },
        )


if __name__ == "__main__":
    unittest.main()
