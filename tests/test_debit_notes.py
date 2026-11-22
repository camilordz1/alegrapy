import json
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import AlegraClient, DebitNotes, RetryPolicy

UUID_ID = "01959152-fe97-7a6e-a2d5-c0c63e82f80a"


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestDebitNotes(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_cached_property_export_and_uuid_read(self):
        self.assertIsInstance(self.client.debit_notes, DebitNotes)
        self.assertIs(self.client.debit_notes, self.client.debit_notes)
        self.assertIn("DebitNotes", alegrapy.__all__)
        self.assertIs(alegrapy.DebitNotes, DebitNotes)

        with patch.object(
            self.client.session, "request", return_value=_mock_response({"id": UUID_ID})
        ) as mock_req:
            res = self.client.debit_notes.read(UUID_ID)
        self.assertEqual(res["id"], UUID_ID)
        self.assertEqual(
            mock_req.call_args.kwargs["url"],
            f"https://api.alegra.com/api/v1/debit-notes/{UUID_ID}",
        )

    def test_list_rejects_ordering_and_iter_all_paginates(self):
        with patch.object(
            self.client.session, "request", return_value=_mock_response([{"id": "1"}])
        ) as mock_req:
            self.client.debit_notes.list(number="ND-1", date="2026-11-22")
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/debit-notes")
        self.assertEqual(kw["params"], {"start": 0, "limit": 30, "number": "ND-1", "date": "2026-11-22"})
        self.assertNotIn("order_field", kw["params"])
        self.assertNotIn("order_direction", kw["params"])

        with patch.object(self.client.session, "request") as mock_req:
            for bad in (
                {"order_field": "id"},
                {"order_field": "date"},
                {"order_direction": "ASC"},
                {"date": "22/11/2026"},
                {"limit": 0},
                {"limit": 31},
            ):
                with self.subTest(**bad):
                    with self.assertRaises(ValueError):
                        self.client.debit_notes.list(**bad)
            mock_req.assert_not_called()

        page1 = [{"id": str(i)} for i in range(30)]
        page2 = [{"id": "30"}]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(page1), _mock_response(page2)],
        ) as mock_req:
            items = list(self.client.debit_notes.iter_all(client_id=126))
        self.assertEqual(len(items), 31)
        self.assertEqual(mock_req.call_count, 2)

        with patch.object(self.client.session, "request") as mock_req:
            with self.assertRaises(ValueError):
                self.client.debit_notes.read("1/../x")
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
