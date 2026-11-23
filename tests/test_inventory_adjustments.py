import copy
import datetime as dt
import importlib.util
import json
import math
import os
import pathlib
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import (
    AlegraClient,
    InventoryAdjustmentNumerations,
    InventoryAdjustments,
    RetryPolicy,
)

UUID_ITEM_ID = "01959152-fe97-7a6e-a2d5-c0c63e82f80a"
ULID_NUM_ID = "01HVVJWB1SJJNCG1W4KM7JSZ3A"


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestInventoryAdjustments(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    @staticmethod
    def _valid_create(**extra):
        base = {
            "date": "2026-11-23",
            "items": [{"id": UUID_ITEM_ID, "type": "in", "quantity": 2, "unitCost": 1500}],
        }
        base.update(extra)
        return base

    def test_cached_properties_and_exports(self):
        self.assertIsInstance(self.client.inventory_adjustments, InventoryAdjustments)
        self.assertIs(self.client.inventory_adjustments, self.client.inventory_adjustments)
        self.assertIsInstance(
            self.client.inventory_adjustments.numerations, InventoryAdjustmentNumerations
        )
        self.assertIs(
            self.client.inventory_adjustments.numerations,
            self.client.inventory_adjustments.numerations,
        )
        for name in ("InventoryAdjustments", "InventoryAdjustmentNumerations"):
            self.assertIn(name, alegrapy.__all__)
            self.assertTrue(hasattr(alegrapy, name))

    def test_list_ordering_filters_and_iter_all(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([{"id": "1"}])
        ) as mock_req:
            self.client.inventory_adjustments.list()
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/inventory-adjustments")
        self.assertEqual(kw["params"], {"start": 0, "limit": 30})

        with patch.object(
            self.client.session, "request", return_value=_mock_response([])
        ) as mock_req:
            self.client.inventory_adjustments.list(
                order_field="warehouse_name",
                order_direction="DESC",
                date=dt.date(2026, 11, 23),
                warehouse_id=3,
            )
        self.assertEqual(
            mock_req.call_args.kwargs["params"],
            {
                "start": 0,
                "limit": 30,
                "order_field": "warehouse_name",
                "order_direction": "DESC",
                "date": "2026-11-23",
                "warehouse_id": 3,
            },
        )

        with patch.object(self.client.session, "request") as mock_req:
            for bad in (
                {"order_field": "total"},
                {"order_direction": "UP"},
                {"date": "23/11/2026"},
                {"limit": 0},
                {"limit": 31},
            ):
                with self.subTest(**bad):
                    with self.assertRaises(ValueError):
                        self.client.inventory_adjustments.list(**bad)
            mock_req.assert_not_called()

        page1 = [{"id": str(i)} for i in range(30)]
        page2 = [{"id": "30"}]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(page1), _mock_response(page2)],
        ) as mock_req:
            items = list(self.client.inventory_adjustments.iter_all(warehouse_id=3))
        self.assertEqual(len(items), 31)
        self.assertEqual(mock_req.call_count, 2)

    def test_create_update_validation_and_delete(self):
        date_obj = dt.date(2026, 11, 23)
        params = self._valid_create(date=date_obj)
        original = copy.deepcopy(params)
        with patch.object(
            self.client.session, "request", return_value=_mock_response({"id": "99"})
        ) as mock_req:
            res = self.client.inventory_adjustments.create(params)
        self.assertEqual(res["id"], "99")
        self.assertEqual(params, original)
        self.assertEqual(mock_req.call_args.kwargs["json"]["date"], "2026-11-23")

        with patch.object(self.client.session, "request") as mock_req:
            bad_creates = [
                {"items": [{"id": 1, "type": "in", "quantity": 1, "unitCost": 10}]},
                self._valid_create(date="23/11/2026"),
                {"date": "2026-11-23", "items": []},
                {"date": "2026-11-23", "items": [{"id": 1, "type": "bad", "quantity": 1, "unitCost": 10}]},
                {"date": "2026-11-23", "items": [{"id": 1, "type": "in", "quantity": 0, "unitCost": 10}]},
                {"date": "2026-11-23", "items": [{"id": 1, "type": "in", "quantity": True, "unitCost": 10}]},
                {"date": "2026-11-23", "items": [{"id": 1, "type": "in", "quantity": math.nan, "unitCost": 10}]},
                {"date": "2026-11-23", "items": [{"id": 1, "type": "out", "quantity": 1, "unitCost": -1}]},
                {"date": "2026-11-23", "items": [{"id": 1, "type": "out", "quantity": 1, "unitCost": False}]},
            ]
            for bad in bad_creates:
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        self.client.inventory_adjustments.create(bad)
            with self.assertRaises(ValueError):
                self.client.inventory_adjustments.update("99", {"items": []})
            mock_req.assert_not_called()

        del_body = {"code": 200, "message": "El ajuste de inventario fue eliminado correctamente"}
        with patch.object(
            self.client.session, "request", return_value=_mock_response(del_body)
        ) as mock_req:
            self.assertEqual(self.client.inventory_adjustments.delete("99"), del_body)
        self.assertEqual(
            mock_req.call_args.kwargs["url"],
            "https://api.alegra.com/api/v1/inventory-adjustments/99",
        )

    def test_numerations_subresource(self):
        nums = self.client.inventory_adjustments.numerations
        with patch.object(
            self.client.session, "request", return_value=_mock_response([{"id": ULID_NUM_ID}])
        ) as mock_req:
            nums.list(status="active")
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/inventory-adjustments/numerations")
        self.assertEqual(kw["params"], {"start": 0, "limit": 20, "status": "active"})

        with patch.object(
            self.client.session, "request", return_value=_mock_response({"id": ULID_NUM_ID})
        ) as mock_req:
            nums.read(ULID_NUM_ID)
        self.assertEqual(
            mock_req.call_args.kwargs["url"],
            f"https://api.alegra.com/api/v1/inventory-adjustments/numerations/{ULID_NUM_ID}",
        )

        with patch.object(self.client.session, "request") as mock_req:
            for call_fn in (
                lambda: nums.list(order_field="id"),
                lambda: nums.list(limit=31),
                lambda: nums.create({"name": "Only name"}),
            ):
                with self.assertRaises(ValueError):
                    call_fn()
            mock_req.assert_not_called()

    def test_probe_stock_helpers_refuse_unknown_warehouse_and_report_real_delta(self):
        script_path = (
            pathlib.Path(__file__).resolve().parents[1] / "scripts" / "probe_inventory_adjustment.py"
        )
        spec = importlib.util.spec_from_file_location("probe_inventory_adjustment", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        item = {"inventory": {"availableQuantity": 10,
                              "warehouses": [{"id": "1", "availableQuantity": "7"}]}}
        self.assertEqual(module._extract_stock(item, None), 10.0)
        self.assertEqual(module._extract_stock(item, "1"), 7.0)
        # An unknown warehouse must not silently fall back to the item total
        with self.assertRaises(ValueError):
            module._extract_stock(item, "99")

        # The compensating suggestion uses the measured difference, not --quantity
        self.assertEqual(module.compensation_hint(initial=10.0, current=12.0),
                         ("out", 2.0))
        self.assertEqual(module.compensation_hint(initial=10.0, current=9.0),
                         ("in", 1.0))
        self.assertIsNone(module.compensation_hint(initial=10.0, current=10.0))

        # The unknown warehouse is detected before anything is created
        fake_client = MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.items.read.return_value = {"inventory": {"availableQuantity": 1, "unitCost": 5,
                                                             "warehouses": []}}
        with patch.dict("os.environ", {"ALEGRA_USER": "u", "ALEGRA_TOKEN": "t"}), \
                patch.object(module, "AlegraClient", return_value=fake_client):
            code = module.main(["--yes-call-live-api", "--delete", "--item-id", "3565",
                                "--warehouse-id", "99"])
        self.assertEqual(code, 2)
        fake_client.inventory_adjustments.create_once.assert_not_called()

    def test_probe_script_guards_payload_and_cleanup(self):
        script_path = (
            pathlib.Path(__file__).resolve().parents[1] / "scripts" / "probe_inventory_adjustment.py"
        )
        spec = importlib.util.spec_from_file_location("probe_inventory_adjustment", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with patch("requests.request") as mock_req, patch("requests.Session.request") as mock_sess:
            for argv in (
                ["--item-id", "1", "--delete"],
                ["--yes-call-live-api", "--item-id", "1"],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(argv)
                self.assertNotEqual(ctx.exception.code, 0)
            mock_req.assert_not_called()
            mock_sess.assert_not_called()

        payload = module.build_adjustment_payload(
            item_id=UUID_ITEM_ID, quantity=2, unit_cost=1500.0, warehouse_id="3"
        )
        self.assertEqual(payload["items"], [{
            "id": UUID_ITEM_ID, "type": "in", "quantity": 2, "unitCost": 1500.0
        }])
        self.assertEqual(payload["warehouse"], {"id": "3"})

        fake_client = MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.items.read.return_value = {
            "id": UUID_ITEM_ID,
            "inventory": {"unitCost": "1500", "availableQuantity": 5},
        }
        fake_client.inventory_adjustments.create_once.return_value = {"id": "adj-1"}
        fake_client.inventory_adjustments.read.side_effect = RuntimeError("boom midway")
        with patch.dict(os.environ, {"ALEGRA_USER": "u", "ALEGRA_TOKEN": "t"}):
            with patch.object(module, "AlegraClient", return_value=fake_client):
                with self.assertRaises(RuntimeError):
                    module.main(["--yes-call-live-api", "--item-id", UUID_ITEM_ID, "--delete"])
        fake_client.inventory_adjustments.delete.assert_called_once_with("adj-1")


if __name__ == "__main__":
    unittest.main()
