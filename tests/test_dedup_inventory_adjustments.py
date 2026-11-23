import copy
import datetime as dt
import importlib
import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from alegrapy import (
    AlegraClient,
    AlegraLookupIncompleteError,
    AlegraUnverifiedCreateError,
    AlegraValidationError,
    RetryPolicy,
)

_CREATE_ONCE_TIME = importlib.import_module("alegrapy._create_once").time
MARKER = "alegrapy:dedup:adj-1"


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestDedupInventoryAdjustments(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    @staticmethod
    def _params(**extra):
        base = {
            "date": "2026-11-23",
            "warehouse": {"id": 3},
            "items": [{"id": "1", "type": "in", "quantity": 2, "unitCost": 1000}],
        }
        base.update(extra)
        return base

    def test_reconcile_newest_first_warehouse_recheck_and_truncated_rules(self):
        wrong_wh = {"id": "50", "observations": MARKER, "warehouse": {"id": 99}}
        no_wh = {"id": "49", "observations": MARKER}
        right_wh = {"id": "48", "observations": MARKER, "warehouse": {"id": 3}}
        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response([wrong_wh, no_wh, right_wh]),
        ) as mock_req:
            found = self.client.inventory_adjustments.reconcile(
                "adj-1", date=dt.date(2026, 11, 23), warehouse_id=3
            )
        self.assertEqual(found, right_wh)
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/inventory-adjustments")
        self.assertEqual(
            kw["params"],
            {
                "start": 0,
                "limit": 30,
                "date": "2026-11-23",
                "order_field": "id",
                "order_direction": "DESC",
                "warehouse_id": 3,
            },
        )

        # Short page -> None
        with patch.object(
            self.client.session, "request", return_value=_mock_response([])
        ):
            self.assertIsNone(
                self.client.inventory_adjustments.reconcile("adj-1", date="2026-11-23")
            )

        # Truncated without match -> AlegraLookupIncompleteError
        full_page = [{"id": str(i), "observations": None} for i in range(30)]
        with patch.object(
            self.client.session, "request", return_value=_mock_response(full_page)
        ):
            with self.assertRaises(AlegraLookupIncompleteError) as ctx:
                self.client.inventory_adjustments.reconcile(
                    "adj-1", date="2026-11-23", max_pages=1
                )
        self.assertEqual(ctx.exception.resource, "inventory-adjustments")
        self.assertEqual(ctx.exception.pages_scanned, 1)

        # Truncated WITH match -> returns the match
        full_with_match = [{"id": "99", "observations": MARKER}] + full_page[1:]
        with patch.object(
            self.client.session, "request", return_value=_mock_response(full_with_match)
        ):
            self.assertEqual(
                self.client.inventory_adjustments.reconcile(
                    "adj-1", date="2026-11-23", max_pages=1
                )["id"],
                "99",
            )

    def test_create_once_flows_and_incomplete_lookup(self):
        existing = {"id": "10", "observations": MARKER, "warehouse": {"id": 3}}
        with patch.object(
            self.client.session, "request", return_value=_mock_response([existing])
        ) as mock_req:
            self.assertEqual(
                self.client.inventory_adjustments.create_once(self._params(), "adj-1"),
                existing,
            )
        self.assertEqual(mock_req.call_count, 1)

        params = self._params(date=dt.date(2026, 11, 23))
        original = copy.deepcopy(params)
        created = {"id": "11", "observations": MARKER}
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response([]), _mock_response(created)],
        ) as mock_req:
            res = self.client.inventory_adjustments.create_once(params, "adj-1")
        self.assertEqual(res, created)
        self.assertEqual(params, original)
        post_kw = mock_req.call_args_list[1].kwargs
        self.assertEqual(post_kw["url"], "https://api.alegra.com/api/v1/inventory-adjustments")
        self.assertEqual(post_kw["json"]["date"], "2026-11-23")
        self.assertEqual(post_kw["json"]["observations"], MARKER)

        # Ambiguous timeout -> verified -> no 2nd POST
        with patch.object(
            self.client.session,
            "request",
            side_effect=[
                requests.exceptions.ReadTimeout("timeout"),
                _mock_response([existing]),
            ],
        ) as mock_req:
            with patch.object(_CREATE_ONCE_TIME, "monotonic", side_effect=[0.0, 0.0]):
                with patch.object(_CREATE_ONCE_TIME, "sleep"):
                    res = self.client.inventory_adjustments.create_once(
                        self._params(), "adj-1", precheck=False, verify_window=10
                    )
        self.assertEqual(res, existing)
        self.assertEqual(mock_req.call_count, 2)

        # on_unverified="raise" -> AlegraUnverifiedCreateError
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response({"message": "err"}, status=503), _mock_response([])],
        ):
            with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
                with patch.object(_CREATE_ONCE_TIME, "sleep"):
                    with self.assertRaises(AlegraUnverifiedCreateError) as ctx:
                        self.client.inventory_adjustments.create_once(
                            self._params(), "adj-1", precheck=False, verify_window=0, on_unverified="raise"
                        )
        self.assertEqual(ctx.exception.resource, "inventory-adjustments")
        self.assertEqual(ctx.exception.attempts, 1)

        # 4xx non-ambiguous -> raised unchanged
        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response({"message": "bad"}, status=400),
        ) as mock_req:
            with self.assertRaises(AlegraValidationError):
                self.client.inventory_adjustments.create_once(
                    self._params(), "adj-1", precheck=False
                )
        self.assertEqual(mock_req.call_count, 1)

        # Incomplete lookup in precheck -> zero POSTs; in verify -> AlegraUnverifiedCreateError
        full_page = [{"id": str(i), "observations": None} for i in range(30)]
        with patch.object(
            self.client.session, "request", return_value=_mock_response(full_page)
        ) as mock_req:
            with self.assertRaises(AlegraLookupIncompleteError):
                self.client.inventory_adjustments.create_once(
                    self._params(), "adj-1", max_pages=1
                )
        self.assertEqual(mock_req.call_count, 1)

        with patch.object(
            self.client.session,
            "request",
            side_effect=[requests.exceptions.ReadTimeout("t"), _mock_response(full_page)],
        ) as mock_req:
            with patch.object(_CREATE_ONCE_TIME, "monotonic", return_value=0.0):
                with patch.object(_CREATE_ONCE_TIME, "sleep"):
                    with self.assertRaises(AlegraUnverifiedCreateError) as ctx:
                        self.client.inventory_adjustments.create_once(
                            self._params(), "adj-1", precheck=False, max_pages=1, verify_window=10
                        )
        self.assertIsInstance(ctx.exception.__cause__, AlegraLookupIncompleteError)
        self.assertEqual(mock_req.call_count, 2)


if __name__ == "__main__":
    unittest.main()
