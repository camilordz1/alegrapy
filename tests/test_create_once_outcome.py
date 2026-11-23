import importlib
import json
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import (
    AlegraClient,
    AlegraServerError,
    AlegraStampError,
    AlegraUnverifiedCreateError,
    AlegraValidationError,
    CreateOnceOutcome,
    CreateOnceResult,
    RetryPolicy,
)

_CREATE_ONCE = importlib.import_module("alegrapy._create_once")
KEY = "outcome-1"
MARKER = f"alegrapy:dedup:{KEY}"


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestCreateOnceOutcomeTypes(unittest.TestCase):

    def test_enum_values_and_str_comparison(self):
        self.assertEqual(
            [member.value for member in CreateOnceOutcome],
            ["created", "existing", "recovered"],
        )
        self.assertEqual(CreateOnceOutcome.CREATED, "created")
        self.assertEqual(CreateOnceOutcome.EXISTING, "existing")
        self.assertEqual(CreateOnceOutcome.RECOVERED, "recovered")
        self.assertIsInstance(CreateOnceOutcome.EXISTING, str)

    def test_result_unpacking_and_attributes(self):
        doc = {"id": "1"}
        result = CreateOnceResult(doc, CreateOnceOutcome.CREATED)
        record, outcome = result
        self.assertIs(record, doc)
        self.assertIs(outcome, CreateOnceOutcome.CREATED)
        self.assertIs(result.record, doc)
        self.assertIs(result.outcome, CreateOnceOutcome.CREATED)

    def test_public_exports(self):
        self.assertIn("CreateOnceOutcome", alegrapy.__all__)
        self.assertIn("CreateOnceResult", alegrapy.__all__)
        self.assertIs(alegrapy.CreateOnceOutcome, _CREATE_ONCE.CreateOnceOutcome)
        self.assertIs(alegrapy.CreateOnceResult, _CREATE_ONCE.CreateOnceResult)


class TestRunCreateOnceWithOutcomeUnit(unittest.TestCase):

    def _call(self, *, post, lookup, before_post=None, precheck=True,
              on_unverified="retry", verify_window=10.0):
        return _CREATE_ONCE.run_create_once_with_outcome(
            post=post,
            lookup=lookup,
            payload={"observations": MARKER},
            dedup_key=KEY,
            client_id=126,
            resource="invoices",
            on_unverified=on_unverified,
            verify_window=verify_window,
            lookup_pages=2,
            precheck=precheck,
            before_post=before_post,
            log_path="/invoices",
        )

    def test_path_1_precheck_lookup_found_is_existing(self):
        doc = {"id": "1"}
        lookup = MagicMock(return_value=doc)
        before_post = MagicMock(return_value=None)
        post = MagicMock(return_value={"id": "should-not-post"})

        result = self._call(post=post, lookup=lookup, before_post=before_post)

        self.assertEqual(result, CreateOnceResult(doc, CreateOnceOutcome.EXISTING))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(before_post.call_count, 0)
        self.assertEqual(post.call_count, 0)

    def test_path_2_first_before_post_found_is_existing(self):
        doc = {"id": "2"}
        lookup = MagicMock(return_value=None)
        before_post = MagicMock(return_value=doc)
        post = MagicMock(return_value={"id": "should-not-post"})

        result = self._call(post=post, lookup=lookup, before_post=before_post)

        self.assertEqual(result, CreateOnceResult(doc, CreateOnceOutcome.EXISTING))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(before_post.call_count, 1)
        self.assertEqual(post.call_count, 0)

    def test_path_3_first_post_returned_is_created(self):
        doc = {"id": "3"}
        lookup = MagicMock(return_value=None)
        before_post = MagicMock(return_value=None)
        post = MagicMock(return_value=doc)

        result = self._call(post=post, lookup=lookup, before_post=before_post)

        self.assertEqual(result, CreateOnceResult(doc, CreateOnceOutcome.CREATED))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(before_post.call_count, 1)
        self.assertEqual(post.call_count, 1)

    def test_path_4_verified_after_ambiguous_first_post_is_recovered(self):
        doc = {"id": "4"}
        lookup = MagicMock(side_effect=[None, doc])
        before_post = MagicMock(return_value=None)
        post = MagicMock(side_effect=AlegraServerError("503", status_code=503))

        with patch.object(_CREATE_ONCE.time, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE.time, "sleep"):
                result = self._call(post=post, lookup=lookup, before_post=before_post)

        self.assertEqual(result, CreateOnceResult(doc, CreateOnceOutcome.RECOVERED))
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(before_post.call_count, 1)
        self.assertEqual(post.call_count, 1)

    def test_path_5_second_before_post_after_unverified_first_post_is_recovered(self):
        doc = {"id": "5"}
        lookup = MagicMock(side_effect=[None, None])
        before_post = MagicMock(side_effect=[None, doc])
        post = MagicMock(side_effect=AlegraServerError("503", status_code=503))

        with patch.object(_CREATE_ONCE.time, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE.time, "sleep"):
                result = self._call(
                    post=post, lookup=lookup, before_post=before_post, verify_window=0.0
                )

        self.assertEqual(result, CreateOnceResult(doc, CreateOnceOutcome.RECOVERED))
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(before_post.call_count, 2)
        self.assertEqual(post.call_count, 1)

    def test_path_6_second_post_returned_is_created(self):
        doc = {"id": "6"}
        lookup = MagicMock(side_effect=[None, None])
        before_post = MagicMock(side_effect=[None, None])
        post = MagicMock(side_effect=[AlegraServerError("503", status_code=503), doc])

        with patch.object(_CREATE_ONCE.time, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE.time, "sleep"):
                result = self._call(
                    post=post, lookup=lookup, before_post=before_post, verify_window=0.0
                )

        self.assertEqual(result, CreateOnceResult(doc, CreateOnceOutcome.CREATED))
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(before_post.call_count, 2)
        self.assertEqual(post.call_count, 2)

    def test_path_7_verified_after_ambiguous_second_post_is_recovered(self):
        doc = {"id": "7"}
        lookup = MagicMock(side_effect=[None, None, doc])
        before_post = MagicMock(side_effect=[None, None])
        post = MagicMock(
            side_effect=[
                AlegraServerError("503-a", status_code=503),
                AlegraServerError("503-b", status_code=503),
            ]
        )

        with patch.object(_CREATE_ONCE.time, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE.time, "sleep"):
                result = self._call(
                    post=post, lookup=lookup, before_post=before_post, verify_window=0.0
                )

        self.assertEqual(result, CreateOnceResult(doc, CreateOnceOutcome.RECOVERED))
        self.assertEqual(lookup.call_count, 3)
        self.assertEqual(before_post.call_count, 2)
        self.assertEqual(post.call_count, 2)

    def test_run_create_once_keeps_returning_bare_record(self):
        doc = {"id": "bare"}
        record = _CREATE_ONCE.run_create_once(
            post=MagicMock(return_value=doc),
            lookup=MagicMock(return_value=None),
            payload={"observations": MARKER},
            dedup_key=KEY,
            client_id=126,
            resource="credit-notes",
            log_path="/credit-notes",
        )
        self.assertEqual(record, doc)
        self.assertNotIsInstance(record, CreateOnceResult)

    def test_exceptions_propagate_unchanged_without_outcome(self):
        with self.assertRaises(AlegraValidationError):
            self._call(
                post=MagicMock(side_effect=AlegraValidationError("400", status_code=400)),
                lookup=MagicMock(return_value=None),
                precheck=False,
            )

        with self.assertRaises(AlegraStampError):
            self._call(
                post=MagicMock(side_effect=AlegraStampError("stamp", document={"id": "9"})),
                lookup=MagicMock(return_value=None),
                precheck=False,
            )

        with patch.object(_CREATE_ONCE.time, "monotonic", return_value=0.0):
            with patch.object(_CREATE_ONCE.time, "sleep"):
                with self.assertRaises(AlegraUnverifiedCreateError):
                    self._call(
                        post=MagicMock(side_effect=AlegraServerError("503", status_code=503)),
                        lookup=MagicMock(return_value=None),
                        precheck=False,
                        on_unverified="raise",
                        verify_window=0.0,
                    )


class TestPublicCreateOnceWithOutcome(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def _resource_cases(self):
        return [
            (
                "invoices",
                self.client.invoices,
                {"client": {"id": 126}, "items": [{"id": 1, "quantity": 1, "price": 100}]},
                {"id": "10", "observations": MARKER},
            ),
            (
                "payments",
                self.client.payments,
                {
                    "date": "2026-11-23",
                    "bankAccount": {"id": 1},
                    "paymentMethod": "transfer",
                    "type": "in",
                    "client": {"id": 126},
                },
                {"id": "20", "observations": MARKER, "client": {"id": 126}, "type": "in"},
            ),
            (
                "income_debit_notes",
                self.client.income_debit_notes,
                {
                    "date": "2026-11-23",
                    "client": {"id": 126},
                    "invoice": {"id": 1},
                    "type": "VALUE_CHANGE",
                    "items": [{"id": 1, "quantity": 1, "price": 100}],
                },
                {"id": "30", "observations": MARKER, "client": {"id": 126}},
            ),
            (
                "inventory_adjustments",
                self.client.inventory_adjustments,
                {
                    "date": "2026-11-23",
                    "warehouse": {"id": 3},
                    "items": [{"id": "1", "type": "in", "quantity": 2, "unitCost": 1000}],
                },
                {"id": "40", "observations": MARKER, "warehouse": {"id": 3}},
            ),
        ]

    def test_precheck_hit_returns_existing_with_zero_posts(self):
        for name, resource, params, existing in self._resource_cases():
            with self.subTest(resource=name):
                with patch.object(
                    self.client.session,
                    "request",
                    return_value=_mock_response([existing]),
                ) as mock_req:
                    result = resource.create_once(params, KEY, with_outcome=True)

                self.assertIsInstance(result, CreateOnceResult)
                record, outcome = result
                self.assertEqual(record, existing)
                self.assertIs(outcome, CreateOnceOutcome.EXISTING)
                self.assertEqual(outcome, "existing")
                self.assertEqual(mock_req.call_count, 1)
                self.assertEqual(mock_req.call_args.kwargs["method"].upper(), "GET")

    def test_miss_then_post_201_returns_created(self):
        for name, resource, params, created in self._resource_cases():
            with self.subTest(resource=name):
                with patch.object(
                    self.client.session,
                    "request",
                    side_effect=[_mock_response([]), _mock_response(created, status=201)],
                ) as mock_req:
                    result = resource.create_once(params, KEY, with_outcome=True)

                self.assertIsInstance(result, CreateOnceResult)
                record, outcome = result
                self.assertEqual(record, created)
                self.assertIs(outcome, CreateOnceOutcome.CREATED)
                self.assertEqual(outcome, "created")
                self.assertEqual(mock_req.call_count, 2)
                self.assertEqual(mock_req.call_args_list[0].kwargs["method"].upper(), "GET")
                self.assertEqual(mock_req.call_args_list[1].kwargs["method"].upper(), "POST")

    def test_ambiguous_503_then_found_returns_recovered(self):
        for name, resource, params, recovered in self._resource_cases():
            with self.subTest(resource=name):
                with patch.object(
                    self.client.session,
                    "request",
                    side_effect=[
                        _mock_response({"message": "unavailable"}, status=503),
                        _mock_response([recovered]),
                    ],
                ) as mock_req:
                    with patch.object(_CREATE_ONCE.time, "monotonic", return_value=0.0):
                        with patch.object(_CREATE_ONCE.time, "sleep"):
                            result = resource.create_once(
                                params,
                                KEY,
                                precheck=False,
                                verify_window=10.0,
                                with_outcome=True,
                            )

                self.assertIsInstance(result, CreateOnceResult)
                record, outcome = result
                self.assertEqual(record, recovered)
                self.assertIs(outcome, CreateOnceOutcome.RECOVERED)
                self.assertEqual(outcome, "recovered")
                self.assertEqual(mock_req.call_count, 2)
                self.assertEqual(mock_req.call_args_list[0].kwargs["method"].upper(), "POST")
                self.assertEqual(mock_req.call_args_list[1].kwargs["method"].upper(), "GET")

    def test_default_and_with_outcome_false_return_bare_record(self):
        for name, resource, params, existing in self._resource_cases():
            for kwargs in ({}, {"with_outcome": False}):
                with self.subTest(resource=name, kwargs=kwargs):
                    with patch.object(
                        self.client.session,
                        "request",
                        return_value=_mock_response([existing]),
                    ):
                        record = resource.create_once(params, KEY, **kwargs)

                    self.assertEqual(record, existing)
                    self.assertNotIsInstance(record, CreateOnceResult)

    def test_non_bool_with_outcome_raises_value_error_without_request(self):
        for name, resource, params, _ in self._resource_cases():
            for bad_value in ("yes", 1, 0, None):
                with self.subTest(resource=name, with_outcome=bad_value):
                    with patch.object(self.client.session, "request") as mock_req:
                        with self.assertRaises(ValueError):
                            resource.create_once(params, KEY, with_outcome=bad_value)
                    self.assertEqual(mock_req.call_count, 0)


if __name__ == "__main__":
    unittest.main()
