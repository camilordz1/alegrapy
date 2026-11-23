import json
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import AlegraClient, NumberTemplates, RetryPolicy


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestNumberTemplates(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_cached_property_and_public_export(self):
        self.assertIsInstance(self.client.number_templates, NumberTemplates)
        self.assertIs(self.client.number_templates, self.client.number_templates)
        self.assertIn("NumberTemplates", alegrapy.__all__)
        self.assertIs(alegrapy.NumberTemplates, NumberTemplates)

    def test_list_sends_only_start_limit_and_document_type(self):
        expected = [{"id": "1", "name": "DIAN", "isDefault": True, "status": "active"}]
        with patch.object(
            self.client.session, "request", return_value=_mock_response(expected)
        ) as mock_req:
            result = self.client.number_templates.list(document_type="invoice")

        self.assertEqual(result, expected)
        self.assertEqual(mock_req.call_count, 1)
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["method"].lower(), "get")
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/number-templates")
        self.assertEqual(kw["params"], {"start": 0, "limit": 30, "documentType": "invoice"})
        self.assertNotIn("order_field", kw["params"])
        self.assertNotIn("order_direction", kw["params"])

    def test_list_accepts_all_documented_document_types(self):
        doc_types = (
            "invoice",
            "estimate",
            "transactionIn",
            "transactionOut",
            "creditNote",
            "debitNote",
            "incomeDebitNote",
        )
        for doc_type in doc_types:
            with self.subTest(document_type=doc_type):
                with patch.object(
                    self.client.session, "request", return_value=_mock_response([])
                ) as mock_req:
                    self.client.number_templates.list(document_type=doc_type)
                self.assertEqual(mock_req.call_args.kwargs["params"]["documentType"], doc_type)

    def test_list_validates_document_type_start_and_limit_before_request(self):
        with patch.object(self.client.session, "request") as mock_req:
            with self.assertRaises(TypeError):
                self.client.number_templates.list()  # missing required document_type

            for bad_kwargs in (
                {"document_type": "unknown"},
                {"document_type": ""},
                {"document_type": 123},
                {"document_type": "invoice", "start": -1},
                {"document_type": "invoice", "start": True},
                {"document_type": "invoice", "limit": 0},
                {"document_type": "invoice", "limit": 31},
                {"document_type": "invoice", "limit": True},
            ):
                with self.subTest(**bad_kwargs):
                    with self.assertRaises(ValueError):
                        self.client.number_templates.list(**bad_kwargs)
            mock_req.assert_not_called()

    def test_list_rejects_kwargs_that_override_validated_params(self):
        for key in ("documentType", "start", "limit"):
            with self.subTest(key=key):
                with patch.object(self.client.session, "request") as mock_req:
                    with self.assertRaises(ValueError):
                        self.client.number_templates.list(document_type="invoice", **{key: "x"})
                    mock_req.assert_not_called()

    def test_iter_all_paginates_and_stops(self):
        page1 = [{"id": str(i)} for i in range(30)]
        page2 = [{"id": "30"}]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(page1), _mock_response(page2)],
        ) as mock_req:
            items = list(self.client.number_templates.iter_all(document_type="creditNote"))

        self.assertEqual(len(items), 31)
        self.assertEqual(mock_req.call_count, 2)
        self.assertEqual(
            mock_req.call_args_list[0].kwargs["params"],
            {"start": 0, "limit": 30, "documentType": "creditNote"},
        )
        self.assertEqual(
            mock_req.call_args_list[1].kwargs["params"],
            {"start": 30, "limit": 30, "documentType": "creditNote"},
        )

    def test_iter_all_validates_eagerly_before_request(self):
        with patch.object(self.client.session, "request") as mock_req:
            with self.assertRaises(ValueError):
                self.client.number_templates.iter_all(document_type="invalid")
            with self.assertRaises(ValueError):
                self.client.number_templates.iter_all(document_type="invoice", limit=10)
            mock_req.assert_not_called()

    def test_default_picks_active_default_skips_inactive_and_returns_none(self):
        page = [
            {"id": "1", "isDefault": True, "status": "inactive"},
            {"id": "2", "isDefault": False, "status": "active"},
            {"id": "3", "isDefault": True, "status": "active"},
        ]
        with patch.object(
            self.client.session, "request", return_value=_mock_response(page)
        ) as mock_req:
            chosen = self.client.number_templates.default()

        self.assertEqual(chosen, page[2])
        self.assertEqual(mock_req.call_args.kwargs["params"]["documentType"], "invoice")

        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response([{"id": "1", "isDefault": True, "status": "inactive"}]),
        ):
            self.assertIsNone(self.client.number_templates.default("invoice"))

        with patch.object(self.client.session, "request") as mock_req:
            for call_fn in (
                lambda: self.client.number_templates.list(document_type="invoice", order_field="id"),
                lambda: self.client.number_templates.list(document_type="invoice", order_direction="ASC"),
                lambda: self.client.number_templates.iter_all(document_type="invoice", order_field="id"),
            ):
                with self.assertRaises(ValueError):
                    call_fn()
            mock_req.assert_not_called()

    def test_read_update_delete_and_id_validation(self):
        delete_body = {
            "code": 200,
            "message": "La numeración de facturación fue eliminada correctamente",
        }
        with patch.object(
            self.client.session,
            "request",
            side_effect=[
                _mock_response({"id": "5"}),
                _mock_response({"id": "5", "name": "Updated"}),
                _mock_response(delete_body),
            ],
        ) as mock_req:
            read_res = self.client.number_templates.read(5)
            upd_res = self.client.number_templates.update(5, {"name": "Updated"})
            del_res = self.client.number_templates.delete(5)

        self.assertEqual(read_res, {"id": "5"})
        self.assertEqual(upd_res, {"id": "5", "name": "Updated"})
        self.assertEqual(del_res, delete_body)
        self.assertEqual(
            [c.kwargs["url"] for c in mock_req.call_args_list],
            [
                "https://api.alegra.com/api/v1/number-templates/5",
                "https://api.alegra.com/api/v1/number-templates/5",
                "https://api.alegra.com/api/v1/number-templates/5",
            ],
        )

        with patch.object(self.client.session, "request") as mock_req:
            for call_fn in (
                lambda: self.client.number_templates.read("1/../x"),
                lambda: self.client.number_templates.update("1/../x", {}),
                lambda: self.client.number_templates.delete("1/../x"),
            ):
                with self.assertRaises(ValueError):
                    call_fn()
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
