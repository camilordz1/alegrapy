import datetime as dt
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import AlegraClient, Bills, RetryPolicy

UUID_ID = "01959152-fe97-7a6e-a2d5-c0c63e82f80a"


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestBills(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_cached_property_export_and_uuid_read(self):
        self.assertIsInstance(self.client.bills, Bills)
        self.assertIs(self.client.bills, self.client.bills)
        self.assertIn("Bills", alegrapy.__all__)
        self.assertIs(alegrapy.Bills, Bills)

        with patch.object(
            self.client.session, "request", return_value=_mock_response({"id": UUID_ID})
        ) as mock_req:
            res = self.client.bills.read(UUID_ID)
        self.assertEqual(res["id"], UUID_ID)
        self.assertEqual(
            mock_req.call_args.kwargs["url"],
            f"https://api.alegra.com/api/v1/bills/{UUID_ID}",
        )

    def test_list_and_iter_all_ordering_and_validation(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([{"id": "1"}])
        ) as mock_req:
            self.client.bills.list()
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/bills")
        self.assertEqual(kw["params"], {"start": 0, "limit": 30})

        with patch.object(
            self.client.session, "request", return_value=_mock_response([])
        ) as mock_req:
            self.client.bills.list(
                order_field="dueDate",
                order_direction="DESC",
                status="open",
                type="supportDocument",
                date=dt.date(2026, 11, 22),
            )
        self.assertEqual(
            mock_req.call_args.kwargs["params"],
            {
                "start": 0,
                "limit": 30,
                "order_field": "dueDate",
                "order_direction": "DESC",
                "status": "open",
                "type": "supportDocument",
                "date": "2026-11-22",
            },
        )

        with patch.object(self.client.session, "request") as mock_req:
            for bad in (
                {"order_field": "id"},
                {"order_direction": "UP"},
                {"status": "draft"},
                {"type": "other"},
                {"date": "22/11/2026"},
                {"limit": 0},
                {"limit": 31},
            ):
                with self.subTest(**bad):
                    with self.assertRaises(ValueError):
                        self.client.bills.list(**bad)
            mock_req.assert_not_called()

        page1 = [{"id": str(i)} for i in range(30)]
        page2 = [{"id": "30"}]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(page1), _mock_response(page2)],
        ) as mock_req:
            items = list(self.client.bills.iter_all(status="open"))
        self.assertEqual(len(items), 31)
        self.assertEqual(mock_req.call_count, 2)

    def test_close_add_comment_and_attachments(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response({"id": "5", "status": "closed"})
        ) as mock_req:
            res = self.client.bills.close(
                5, dt.date(2026, 11, 22), {"id": 99}, observations="ajuste"
            )
        self.assertEqual(res["status"], "closed")
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["method"].lower(), "post")
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/bills/5/close")
        self.assertEqual(
            kw["json"],
            {"date": "2026-11-22", "category": {"id": 99}, "observations": "ajuste"},
        )

        with patch.object(self.client.session, "request") as mock_req:
            for call_fn in (
                lambda: self.client.bills.close("1/../x", "2026-11-22", 1),
                lambda: self.client.bills.close(5, "22/11/2026", 1),
                lambda: self.client.bills.close(5, "2026-11-22", "1/../x"),
                lambda: self.client.bills.close(5, "2026-11-22", 1, observations="x" * 501),
            ):
                with self.assertRaises(ValueError):
                    call_fn()
            mock_req.assert_not_called()

        comment_resp = {"code": 201, "message": {"id": "5"}}
        with patch.object(
            self.client.session, "request", return_value=_mock_response(comment_resp)
        ) as mock_req:
            res = self.client.bills.add_comment(5, ["nota 1", "nota 2"])
        self.assertEqual(res, comment_resp)
        self.assertEqual(mock_req.call_args.kwargs["url"], "https://api.alegra.com/api/v1/bills/5/comments")
        self.assertEqual(mock_req.call_args.kwargs["json"], {"comments": ["nota 1", "nota 2"]})

        with patch.object(self.client.session, "request") as mock_req:
            for bad_comment in ("", "  ", [], ["ok", ""], 123):
                with self.assertRaises(ValueError):
                    self.client.bills.add_comment(5, bad_comment)
            mock_req.assert_not_called()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4")
            tmp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(tmp_path) and os.unlink(tmp_path))

        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response({"id": "att-1"}), _mock_response({"code": 200})],
        ) as mock_req:
            self.client.bills.add_attachment(5, tmp_path)
            self.client.bills.delete_attachment("att-1")
        self.assertEqual(
            mock_req.call_args_list[0].kwargs["url"],
            "https://api.alegra.com/api/v1/bills/5/attachment",
        )
        self.assertEqual(mock_req.call_args_list[1].kwargs["method"].lower(), "delete")
        self.assertEqual(
            mock_req.call_args_list[1].kwargs["url"],
            "https://api.alegra.com/api/v1/bills/attachment/att-1",
        )


if __name__ == "__main__":
    unittest.main()
