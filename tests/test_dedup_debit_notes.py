import copy
import datetime as dt
import importlib
import json
import unittest
from unittest.mock import MagicMock, patch

import requests

import alegrapy
from alegrapy import (
    AlegraAPIError,
    AlegraClient,
    AlegraLookupIncompleteError,
    AlegraUnverifiedCreateError,
    AlegraValidationError,
    RetryPolicy,
)

_CREATE_ONCE_TIME = importlib.import_module("alegrapy._create_once").time
MARKER = "alegrapy:dedup:dn-1"


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestDedupDebitNotes(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    @staticmethod
    def _params(**extra):
        base = {
            "date": "2026-11-22",
            "dueDate": "2026-11-22",
            "type": "VALUE_CHANGE",
            "paymentMethod": "CASH",
            "paymentType": "CASH",
            "client": {"id": 126},
            "items": [{"id": 1, "quantity": 1, "price": 1000}],
        }
        base.update(extra)
        return base

    def test_lookup_incomplete_error_export_and_attributes(self):
        self.assertTrue(issubclass(AlegraLookupIncompleteError, AlegraAPIError))
        self.assertIn("AlegraLookupIncompleteError", alegrapy.__all__)
        err = AlegraLookupIncompleteError(
            "incomplete",
            resource="income-debit-notes",
            dedup_key="dn-1",
            date="2026-11-22",
            pages_scanned=10,
        )
        self.assertEqual(err.resource, "income-debit-notes")
        self.assertEqual(err.dedup_key, "dn-1")
        self.assertEqual(err.date, "2026-11-22")
        self.assertEqual(err.pages_scanned, 10)

    def test_reconcile_scans_pages_picks_highest_id_and_rechecks_client(self):
        full_page = [
            {"id": i, "observations": None, "client": {"id": 126}} for i in range(1, 30)
        ] + [{"id": 30, "observations": MARKER, "client": {"id": 999}}]
        second_page = [
            {"id": 31, "observations": MARKER},  # missing client -> skipped when client_id given
            {"id": 32, "observations": MARKER, "client": {"id": 126}},
            {"id": 35, "observations": MARKER, "client": {"id": 126}},
        ]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(full_page), _mock_response(second_page)],
        ) as mock_req:
            found = self.client.income_debit_notes.reconcile(
                "dn-1", date=dt.date(2026, 11, 22), client_id=126
            )

        self.assertEqual(found["id"], 35)
        self.assertEqual(mock_req.call_count, 2)
        for idx, call in enumerate(mock_req.call_args_list):
            kw = call.kwargs
            self.assertEqual(kw["method"].lower(), "get")
            self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/income-debit-notes")
            self.assertEqual(
                kw["params"],
                {"start": idx * 30, "limit": 30, "date": "2026-11-22"},
            )
            self.assertNotIn("order_field", kw["params"])
            self.assertNotIn("order_direction", kw["params"])
            self.assertNotIn("client_id", kw["params"])

    def test_reconcile_returns_none_on_short_page_and_raises_when_truncated(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([])
        ):
            self.assertIsNone(
                self.client.income_debit_notes.reconcile("dn-1", date="2026-11-22")
            )

        full_page = [{"id": i, "observations": None} for i in range(30)]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(full_page), _mock_response(full_page)],
        ):
            with self.assertRaises(AlegraLookupIncompleteError) as ctx:
                self.client.income_debit_notes.reconcile(
                    "dn-1", date="2026-11-22", max_pages=2
                )
        self.assertEqual(ctx.exception.resource, "income-debit-notes")
        self.assertEqual(ctx.exception.dedup_key, "dn-1")
        self.assertEqual(ctx.exception.date, "2026-11-22")
        self.assertEqual(ctx.exception.pages_scanned, 2)

    def test_reconcile_returns_a_match_even_when_the_scan_is_truncated(self):
        # Finding the marker already proves the note exists: never fail on a found note
        full_page = [{"id": i, "observations": None} for i in range(29)]
        full_page.append({"id": 29, "observations": MARKER, "client": {"id": 126}})
        with patch.object(
            self.client.session, "request", return_value=_mock_response(full_page)
        ) as mock_req:
            found = self.client.income_debit_notes.reconcile(
                "dn-1", date="2026-11-22", client_id=126, max_pages=1
            )
        self.assertEqual(found["id"], 29)
        self.assertEqual(mock_req.call_count, 1)

    def test_reconcile_validation_errors_send_no_request(self):
        with patch.object(self.client.session, "request") as mock_req:
            for call_fn in (
                lambda: self.client.income_debit_notes.reconcile("dn-1", date=None),
                lambda: self.client.income_debit_notes.reconcile("dn-1", date="22/11/2026"),
                lambda: self.client.income_debit_notes.reconcile("dn-1", date="2026-11-22", max_pages=0),
                lambda: self.client.income_debit_notes.reconcile("dn-1", date="2026-11-22", max_pages=True),
            ):
                with self.assertRaises(ValueError):
                    call_fn()
            mock_req.assert_not_called()

    def test_create_once_precheck_hit_and_post_normalizes_date(self):
        existing = {"id": 10, "observations": MARKER, "client": {"id": 126}}
        with patch.object(
            self.client.session, "request", return_value=_mock_response([existing])
        ) as mock_req:
            res = self.client.income_debit_notes.create_once(self._params(), "dn-1")
        self.assertEqual(res, existing)
        self.assertEqual(mock_req.call_count, 1)
        self.assertEqual(mock_req.call_args.kwargs["method"].lower(), "get")

        date_obj = dt.date(2026, 11, 22)
        params = self._params(date=date_obj)
        original = copy.deepcopy(params)
        created = {"id": 11, "observations": MARKER}
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response([]), _mock_response(created)],
        ) as mock_req:
            res = self.client.income_debit_notes.create_once(params, "dn-1")

        self.assertEqual(res, created)
        self.assertEqual(params, original)
        post_kw = mock_req.call_args_list[1].kwargs
        self.assertEqual(post_kw["method"].lower(), "post")
        self.assertEqual(post_kw["url"], "https://api.alegra.com/api/v1/income-debit-notes")
        self.assertEqual(post_kw["json"]["date"], "2026-11-22")
        self.assertEqual(post_kw["json"]["observations"], MARKER)

    def test_create_once_ambiguous_failures_and_non_ambiguous_4xx(self):
        created = {"id": 20, "observations": MARKER, "client": {"id": 126}}
        with patch.object(
            self.client.session,
            "request",
            side_effect=[
                requests.exceptions.ReadTimeout("timeout"),
                _mock_response([created]),
            ],
        ) as mock_req:
            with patch.object(_CREATE_ONCE_TIME, "monotonic", side_effect=[0.0, 0.0]):
                with patch.object(_CREATE_ONCE_TIME, "sleep"):
                    res = self.client.income_debit_notes.create_once(
                        self._params(), "dn-1", precheck=False, verify_window=10
                    )
        self.assertEqual(res, created)
        self.assertEqual(mock_req.call_count, 2)

        with patch.object(
            self.client.session,
            "request",
            side_effect=[
                _mock_response({"message": "err"}, status=503),
                _mock_response([]),
                _mock_response({"message": "err"}, status=503),
                _mock_response([]),
            ],
        ) as mock_req:
            with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
                with patch.object(_CREATE_ONCE_TIME, "sleep"):
                    with self.assertRaises(AlegraUnverifiedCreateError) as ctx:
                        self.client.income_debit_notes.create_once(
                            self._params(), "dn-1", precheck=False, verify_window=0
                        )
        self.assertEqual(ctx.exception.resource, "income-debit-notes")
        self.assertEqual(ctx.exception.attempts, 2)

        with patch.object(
            self.client.session,
            "request",
            side_effect=[
                _mock_response({"message": "err"}, status=503),
                _mock_response([]),
            ],
        ):
            with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
                with patch.object(_CREATE_ONCE_TIME, "sleep"):
                    with self.assertRaises(AlegraUnverifiedCreateError) as ctx:
                        self.client.income_debit_notes.create_once(
                            self._params(), "dn-1", precheck=False, verify_window=0, on_unverified="raise"
                        )
        self.assertEqual(ctx.exception.attempts, 1)

        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response({"message": "bad"}, status=400),
        ) as mock_req:
            with self.assertRaises(AlegraValidationError):
                self.client.income_debit_notes.create_once(
                    self._params(), "dn-1", precheck=False
                )
        self.assertEqual(mock_req.call_count, 1)

    def test_create_once_incomplete_lookup_in_precheck_and_verification(self):
        full_page = [{"id": i, "observations": None} for i in range(30)]
        with patch.object(
            self.client.session, "request", return_value=_mock_response(full_page)
        ) as mock_req:
            with self.assertRaises(AlegraLookupIncompleteError):
                self.client.income_debit_notes.create_once(
                    self._params(), "dn-1", max_pages=1
                )
        self.assertEqual(mock_req.call_count, 1)

        with patch.object(
            self.client.session,
            "request",
            side_effect=[
                requests.exceptions.ReadTimeout("timeout"),
                _mock_response(full_page),
            ],
        ) as mock_req:
            with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
                with patch.object(_CREATE_ONCE_TIME, "sleep"):
                    with self.assertRaises(AlegraUnverifiedCreateError) as ctx:
                        self.client.income_debit_notes.create_once(
                            self._params(), "dn-1", precheck=False, max_pages=1, verify_window=10
                        )
        self.assertIsInstance(ctx.exception.__cause__, AlegraLookupIncompleteError)
        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(mock_req.call_count, 2)

    def test_create_once_validation_errors_send_no_request(self):
        bad_params = [
            {"client": {"id": 126}},  # missing date
            self._params(date="22/11/2026"),
            {"date": "2026-11-22"},  # missing client
            self._params(observations="x" * 490),
        ]
        with patch.object(self.client.session, "request") as mock_req:
            for p in bad_params:
                with self.subTest(params=p):
                    with self.assertRaises(ValueError):
                        self.client.income_debit_notes.create_once(p, "dn-1")
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
