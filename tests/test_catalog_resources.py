import datetime as dt
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import (
    AlegraClient,
    ItemCategories,
    PriceLists,
    Remissions,
    RetryPolicy,
    Terms,
    Warehouses,
)

UUID_ID = "01959152-fe97-7a6e-a2d5-c0c63e82f80a"


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestCatalogResources(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_cached_properties_exports_and_uuid_reads(self):
        cases = [
            ("remissions", Remissions, "remissions"),
            ("warehouses", Warehouses, "warehouses"),
            ("price_lists", PriceLists, "price-lists"),
            ("item_categories", ItemCategories, "item-categories"),
            ("terms", Terms, "terms"),
        ]
        for attr, cls, path in cases:
            with self.subTest(resource=attr):
                instance = getattr(self.client, attr)
                self.assertIsInstance(instance, cls)
                self.assertIs(instance, getattr(self.client, attr))
                self.assertIn(cls.__name__, alegrapy.__all__)
                self.assertIs(getattr(alegrapy, cls.__name__), cls)

                with patch.object(
                    self.client.session, "request", return_value=_mock_response({"id": UUID_ID})
                ) as mock_req:
                    res = instance.read(UUID_ID)
                self.assertEqual(res["id"], UUID_ID)
                self.assertEqual(
                    mock_req.call_args.kwargs["url"],
                    f"https://api.alegra.com/api/v1/{path}/{UUID_ID}",
                )

                with patch.object(self.client.session, "request") as mock_req:
                    with self.assertRaises(ValueError):
                        instance.read("1/../x")
                    mock_req.assert_not_called()

    def test_remissions_list_iter_all_open_void_and_attachments(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([{"id": "1"}])
        ) as mock_req:
            self.client.remissions.list(
                order_field="dueDate", status="open", date=dt.date(2026, 11, 22)
            )
        self.assertEqual(
            mock_req.call_args.kwargs["params"],
            {"start": 0, "limit": 30, "order_field": "dueDate", "status": "open", "date": "2026-11-22"},
        )

        with patch.object(self.client.session, "request") as mock_req:
            for bad in ({"order_field": "total"}, {"status": "draft"}, {"date": "22/11/2026"}, {"limit": 31}):
                with self.assertRaises(ValueError):
                    self.client.remissions.list(**bad)
            mock_req.assert_not_called()

        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response({"status": "open"}), _mock_response({"status": "void"})],
        ) as mock_req:
            self.client.remissions.open(10)
            self.client.remissions.void(10)
        self.assertEqual(mock_req.call_args_list[0].kwargs["url"], "https://api.alegra.com/api/v1/remissions/10/open")
        self.assertIsNone(mock_req.call_args_list[0].kwargs.get("json"))
        self.assertEqual(mock_req.call_args_list[1].kwargs["url"], "https://api.alegra.com/api/v1/remissions/10/void")
        self.assertIsNone(mock_req.call_args_list[1].kwargs.get("json"))

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF")
            tmp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(tmp_path) and os.unlink(tmp_path))

        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response({"id": "a1"}), _mock_response({"code": 200})],
        ) as mock_req:
            self.client.remissions.add_attachment(10, tmp_path)
            self.client.remissions.delete_attachment("a1")
        self.assertEqual(mock_req.call_args_list[1].kwargs["url"], "https://api.alegra.com/api/v1/remissions/attachment/a1")

    def test_warehouses_and_item_categories(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([])
        ) as mock_req:
            self.client.warehouses.list(order_field="name", status="active", fields="editable")
        self.assertEqual(
            mock_req.call_args.kwargs["params"],
            {"start": 0, "limit": 30, "order_field": "name", "status": "active", "fields": "editable"},
        )

        with patch.object(self.client.session, "request") as mock_req:
            for bad in ({"order_field": "date"}, {"status": "closed"}, {"fields": "other"}, {"limit": 0}):
                with self.assertRaises(ValueError):
                    self.client.warehouses.list(**bad)
            mock_req.assert_not_called()

        with patch.object(
            self.client.session, "request", return_value=_mock_response([])
        ) as mock_req:
            self.client.item_categories.list(order_field="name", status="active")
        self.assertEqual(
            mock_req.call_args.kwargs["params"],
            {"start": 0, "limit": 30, "order_field": "name", "status": "active"},
        )

        with patch.object(self.client.session, "request") as mock_req:
            for bad in ({"order_field": "id"}, {"status": "deleted"}):
                with self.assertRaises(ValueError):
                    self.client.item_categories.list(**bad)
            mock_req.assert_not_called()

        with patch.object(
            self.client.session, "request", return_value=_mock_response({"code": 200})
        ) as mock_req:
            self.client.item_categories.delete_attachment("cat-att-1")
        self.assertEqual(
            mock_req.call_args.kwargs["url"],
            "https://api.alegra.com/api/v1/item-categories/attachment/cat-att-1",
        )

    def test_price_lists_validation_and_pagination(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([])
        ) as mock_req:
            self.client.price_lists.list(order_field="id", query="VIP", fields="deletable")
        self.assertEqual(
            mock_req.call_args.kwargs["params"],
            {"start": 0, "limit": 30, "order_field": "id", "query": "VIP", "fields": "deletable"},
        )

        with patch.object(self.client.session, "request") as mock_req:
            for bad in ({"order_field": "date"}, {"fields": "bad"}):
                with self.assertRaises(ValueError):
                    self.client.price_lists.list(**bad)
            with self.assertRaises(ValueError):
                self.client.price_lists.create({"name": "x", "type": "unknown"})
            with self.assertRaises(ValueError):
                self.client.price_lists.create({"name": "x", "type": "percentage"})
            with self.assertRaises(ValueError):
                self.client.price_lists.update("1", {"name": "a" * 91, "type": "amount"})
            mock_req.assert_not_called()

        page1 = [{"id": str(i)} for i in range(30)]
        page2 = [{"id": "30"}]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(page1), _mock_response(page2)],
        ) as mock_req:
            items = list(self.client.price_lists.iter_all())
        self.assertEqual(len(items), 31)
        self.assertEqual(mock_req.call_count, 2)

    def test_terms_sends_no_pagination_or_ordering_and_iter_all_single_call(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([{"id": "1"}, {"id": "2"}])
        ) as mock_req:
            res = self.client.terms.list(fields="deletable")
        self.assertEqual(len(res), 2)
        self.assertEqual(mock_req.call_args.kwargs["params"], {"fields": "deletable"})

        with patch.object(
            self.client.session, "request", return_value=_mock_response([{"id": "1"}])
        ) as mock_req:
            self.assertEqual(list(self.client.terms.iter_all()), [{"id": "1"}])
        self.assertEqual(mock_req.call_count, 1)
        self.assertEqual(mock_req.call_args.kwargs["params"], {})

        with patch.object(self.client.session, "request") as mock_req:
            for bad in ({"start": 0}, {"limit": 10}, {"order_field": "id"}, {"fields": "other"}):
                with self.assertRaises(ValueError):
                    self.client.terms.list(**bad)
            with self.assertRaises(ValueError):
                self.client.terms.iter_all(start=0)
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
