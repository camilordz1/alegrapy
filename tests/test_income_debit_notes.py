import json
import pathlib
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import AlegraClient, AlegraValidationError, IncomeDebitNotes, RetryPolicy


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestIncomeDebitNotes(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_cached_property_and_public_export(self):
        self.assertIsInstance(self.client.income_debit_notes, IncomeDebitNotes)
        self.assertIs(self.client.income_debit_notes, self.client.income_debit_notes)
        self.assertIn("IncomeDebitNotes", alegrapy.__all__)
        self.assertIs(alegrapy.IncomeDebitNotes, IncomeDebitNotes)

    def test_list_sends_start_limit_and_filters_without_order_fields(self):
        expected = [{"id": 1, "status": "open"}]
        with patch.object(
            self.client.session, "request", return_value=_mock_response(expected)
        ) as mock_req:
            res = self.client.income_debit_notes.list(
                status="open",
                emission_status="STAMPED_AND_ACCEPTED",
                date="2026-11-22",
            )

        self.assertEqual(res, expected)
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["method"].lower(), "get")
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/income-debit-notes")
        self.assertEqual(
            kw["params"],
            {
                "start": 0,
                "limit": 30,
                "status": "open",
                "emission_status": "STAMPED_AND_ACCEPTED",
                "date": "2026-11-22",
            },
        )
        self.assertNotIn("order_field", kw["params"])
        self.assertNotIn("order_direction", kw["params"])

    def test_list_validates_filters_and_pagination_before_request(self):
        with patch.object(self.client.session, "request") as mock_req:
            for bad_kwargs in (
                {"status": "bad"},
                {"emission_status": "UNKNOWN"},
                {"date": "22/11/2026"},
                {"dueDate": "2026-13-01"},
                {"start": -1},
                {"limit": 0},
                {"limit": 31},
                {"limit": True},
            ):
                with self.subTest(**bad_kwargs):
                    with self.assertRaises(ValueError):
                        self.client.income_debit_notes.list(**bad_kwargs)
            mock_req.assert_not_called()

    def test_iter_all_paginates_and_stops(self):
        page1 = [{"id": i} for i in range(30)]
        page2 = [{"id": 30}]
        with patch.object(
            self.client.session,
            "request",
            side_effect=[_mock_response(page1), _mock_response(page2)],
        ) as mock_req:
            items = list(self.client.income_debit_notes.iter_all(status="draft"))

        self.assertEqual(len(items), 31)
        self.assertEqual(mock_req.call_count, 2)
        self.assertEqual(
            mock_req.call_args_list[0].kwargs["params"],
            {"start": 0, "limit": 30, "status": "draft"},
        )
        self.assertEqual(
            mock_req.call_args_list[1].kwargs["params"],
            {"start": 30, "limit": 30, "status": "draft"},
        )

    def test_void_posts_without_body_validates_id_and_surfaces_400(self):
        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response({"code": 200, "message": "Fue anulada correctamente"}),
        ) as mock_req:
            res = self.client.income_debit_notes.void(5)

        self.assertEqual(res["code"], 200)
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["method"].lower(), "post")
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/income-debit-notes/5/void")
        self.assertIsNone(kw.get("json"))

        with patch.object(self.client.session, "request") as mock_req:
            with self.assertRaises(ValueError):
                self.client.income_debit_notes.void("1/../x")
            mock_req.assert_not_called()

        err_payload = {"code": 43043, "message": "La nota débito no se puede anular"}
        with patch.object(
            self.client.session, "request", return_value=_mock_response(err_payload, status=400)
        ):
            with self.assertRaises(AlegraValidationError):
                self.client.income_debit_notes.void(5)

    def test_read_update_delete(self):
        del_body = {"code": 200, "message": "La nota de débito fue eliminada exitosamente"}
        with patch.object(
            self.client.session,
            "request",
            side_effect=[
                _mock_response({"id": 7}),
                _mock_response({"id": 7, "reason": "ajuste"}),
                _mock_response(del_body),
            ],
        ) as mock_req:
            r = self.client.income_debit_notes.read(7)
            u = self.client.income_debit_notes.update(7, {"reason": "ajuste"})
            d = self.client.income_debit_notes.delete(7)

        self.assertEqual(r, {"id": 7})
        self.assertEqual(u, {"id": 7, "reason": "ajuste"})
        self.assertEqual(d, del_body)
        self.assertEqual(
            [c.kwargs["url"] for c in mock_req.call_args_list],
            [
                "https://api.alegra.com/api/v1/income-debit-notes/7",
                "https://api.alegra.com/api/v1/income-debit-notes/7",
                "https://api.alegra.com/api/v1/income-debit-notes/7",
            ],
        )

        with patch.object(self.client.session, "request") as mock_req:
            for call_fn in (
                lambda: self.client.income_debit_notes.list(order_field="id"),
                lambda: self.client.income_debit_notes.list(order_direction="ASC"),
                lambda: self.client.income_debit_notes.iter_all(order_field="id"),
            ):
                with self.assertRaises(ValueError):
                    call_fn()
            mock_req.assert_not_called()

    def test_probe_script_guard_and_payload_builder(self):
        import importlib.util

        script_path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "probe_debit_note_marker.py"
        spec = importlib.util.spec_from_file_location("probe_debit_note_marker", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with patch("requests.request") as mock_req, patch("requests.Session.request") as mock_sess:
            with self.assertRaises(SystemExit) as ctx:
                module.main(["--client-id", "1", "--item-id", "2", "--invoice-id", "3"])
            self.assertNotEqual(ctx.exception.code, 0)
            mock_req.assert_not_called()
            mock_sess.assert_not_called()

        payload = module.build_probe_payload(
            client_id="126",
            item_id="10",
            invoice_id="555",
            note_type="VALUE_CHANGE",
            payment_form="CASH",
            marker="alegrapy:dedup:probe-abc",
        )
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["observations"], "alegrapy:dedup:probe-abc")
        self.assertNotIn("stamp", payload)

    def test_probe_script_count_verdicts_and_cleanup_on_failure(self):
        import importlib.util
        import os

        script_path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "probe_debit_note_marker.py"
        spec = importlib.util.spec_from_file_location("probe_debit_note_marker", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        parser = module._build_parser()
        parsed = parser.parse_args(["--yes-call-live-api", "--client-id", "1", "--item-id", "2", "--invoice-id", "3"])
        self.assertEqual(parsed.count, 2)

        for bad_count in ("0", "6"):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--yes-call-live-api", "--client-id", "1", "--item-id", "2", "--invoice-id", "3", "--count", bad_count])

        self.assertEqual(module.pagination_verdict([{"id": 1}], [{"id": 2}]), "PASS")
        self.assertEqual(module.pagination_verdict([{"id": 1}], []), "INCONCLUSIVE")
        self.assertEqual(module.pagination_verdict([], []), "INCONCLUSIVE")
        self.assertEqual(module.pagination_verdict([{"id": 1}], [{"id": 1}]), "FAIL")
        self.assertEqual(module.pagination_verdict([{"id": 1}, {"id": 2}], [{"id": 3}]), "FAIL")

        fake_client = MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.income_debit_notes.create.side_effect = [{"id": 101}, {"id": 102}]
        fake_client.income_debit_notes.read.side_effect = RuntimeError("boom midway")
        with patch.dict(os.environ, {"ALEGRA_USER": "u", "ALEGRA_TOKEN": "t"}):
            with patch.object(module, "AlegraClient", return_value=fake_client):
                with self.assertRaises(RuntimeError):
                    module.main([
                        "--yes-call-live-api",
                        "--client-id", "1",
                        "--item-id", "2",
                        "--invoice-id", "3",
                        "--count", "2",
                        "--delete",
                    ])
        self.assertEqual(
            [c.args[0] for c in fake_client.income_debit_notes.delete.call_args_list],
            [101, 102],
        )


if __name__ == "__main__":
    unittest.main()
