import importlib
import json
import unittest
from unittest.mock import patch

import requests

import alegrapy
from alegrapy import (
    AlegraAPIError,
    AlegraClient,
    AlegraServerError,
    AlegraStampTimeoutError,
    AlegraTimeoutError,
    AlegraValidationError,
    StampResult,
    StampState,
    StampStatus,
)
from alegrapy.stamping import map_stamp_state

# `alegrapy.invoices` is shadowed by the legacy `Invoices` alias on the package object,
# so patch `time` on the submodule object directly.
_INVOICES_TIME = importlib.import_module("alegrapy.invoices").time


class _FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TestStampMapping(unittest.TestCase):

    def test_catalog_values_case_insensitive_and_draft_vs_open(self):
        cases = [
            (None, "draft", StampState.DRAFT),
            ("", "DRAFT", StampState.DRAFT),
            (None, "open", StampState.UNKNOWN),
            (None, None, StampState.UNKNOWN),
            ("PENDING", "draft", StampState.PENDING),
            ("pending", "open", StampState.PENDING),
            ("STAMPED_AND_WAITING_RESPONSE", "open", StampState.PENDING),
            ("stamped_and_waiting_response", "open", StampState.PENDING),
            ("ACCEPTED", "open", StampState.ACCEPTED),
            ("STAMPED_AND_ACCEPTED", "open", StampState.ACCEPTED),
            ("stamped_and_accepted", "open", StampState.ACCEPTED),
            (
                "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS",
                "open",
                StampState.ACCEPTED_WITH_OBSERVATIONS,
            ),
            ("REJECTED", "open", StampState.REJECTED),
            ("STAMPED_AND_REJECTED", "open", StampState.REJECTED),
            ("SOMETHING_NEW_FROM_DIAN", "open", StampState.UNKNOWN),
        ]
        for raw, inv_status, expected in cases:
            with self.subTest(raw=raw, inv_status=inv_status):
                self.assertEqual(
                    map_stamp_state(raw, invoice_status=inv_status),
                    expected,
                )


class TestInvoicesStamping(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="user", token="token")

    def test_live_200_shape(self):
        payload = {
            "data": [
                {
                    "success": True,
                    "emissionStatus": "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS",
                    "id": "11742",
                    "message": "La factura electrónica de venta ha sido emitida exitosamente",
                }
            ]
        }
        with patch.object(self.client, "query", return_value=payload) as mock_query:
            results = self.client.invoices.stamp([11742])

        mock_query.assert_called_once_with(
            "post", "https://api.alegra.com/api/v1/invoices/stamp", data={"ids": ["11742"]}
        )
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertIsInstance(res, StampResult)
        self.assertEqual(res.invoice_id, "11742")
        self.assertTrue(res.success)
        self.assertEqual(res.state, StampState.ACCEPTED_WITH_OBSERVATIONS)
        self.assertEqual(
            res.emission_status_raw, "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS"
        )
        self.assertIsNone(res.code)

    def test_mixed_200_and_missing_requested_id(self):
        payload = {
            "data": [
                {
                    "id": "101",
                    "success": True,
                    "emissionStatus": "STAMPED_AND_ACCEPTED",
                    "message": "Emitida",
                },
                {
                    "id": "102",
                    "success": False,
                    "emissionStatus": "STAMPED_AND_REJECTED",
                    "message": "Rechazada por DIAN",
                },
            ]
        }
        with patch.object(self.client, "query", return_value=payload):
            results = self.client.invoices.stamp([101, 102, 103])

        self.assertEqual([r.invoice_id for r in results], ["101", "102", "103"])
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].state, StampState.ACCEPTED)
        self.assertFalse(results[1].success)
        self.assertEqual(results[1].state, StampState.REJECTED)
        self.assertFalse(results[2].success)
        self.assertEqual(results[2].message, "No result returned for this invoice")
        self.assertEqual(results[2].state, StampState.UNKNOWN)

    def test_400_with_per_id_data_returns_results(self):
        body = json.dumps(
            {
                "data": [
                    {
                        "id": "11742",
                        "code": 3226,
                        "message": "La factura ya fue emitida",
                    }
                ]
            }
        )
        err = AlegraValidationError("Bad request", status_code=400, response_body=body)
        with patch.object(self.client, "query", side_effect=err):
            results = self.client.invoices.stamp([11742])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].invoice_id, "11742")
        self.assertFalse(results[0].success)
        self.assertEqual(results[0].code, 3226)
        self.assertEqual(results[0].message, "La factura ya fue emitida")
        self.assertEqual(results[0].state, StampState.UNKNOWN)

    def test_400_without_per_id_data_raises_typed_error(self):
        for body in (None, "not json", json.dumps({"message": "Invalid payload"})):
            with self.subTest(body=body):
                err = AlegraValidationError(
                    "Bad request", status_code=400, response_body=body
                )
                with patch.object(self.client, "query", side_effect=err):
                    with self.assertRaises(AlegraValidationError):
                        self.client.invoices.stamp([11742])

    def test_validation_errors_make_no_request(self):
        bad_inputs = [
            [],
            list(range(1, 12)),
            [1, "1"],
            ["../1"],
            [""],
        ]
        for ids in bad_inputs:
            with self.subTest(ids=ids):
                with patch.object(self.client, "query") as mock_query:
                    with self.assertRaises(ValueError):
                        self.client.invoices.stamp(ids)
                mock_query.assert_not_called()

    @staticmethod
    def _response(status, body):
        from unittest.mock import MagicMock
        resp = MagicMock(status_code=status, text=json.dumps(body), headers={})
        resp.json.return_value = body
        return resp

    def test_stamp_posts_to_the_absolute_stamp_url_through_real_query(self):
        body = {"data": [{"id": "11742", "success": True,
                          "emissionStatus": "STAMPED_AND_ACCEPTED"}]}
        with patch.object(self.client.session, "request",
                          return_value=self._response(200, body)) as request:
            results = self.client.invoices.stamp([11742])

        self.assertEqual(request.call_args.kwargs["url"],
                         "https://api.alegra.com/api/v1/invoices/stamp")
        self.assertEqual(request.call_args.kwargs["method"].lower(), "post")
        self.assertEqual(request.call_args.kwargs["json"], {"ids": ["11742"]})
        self.assertTrue(results[0].success)

    def test_ambiguous_failures_raise_unchanged_and_never_repost(self):
        # Through the REAL query() and the default RetryPolicy: only session.request is mocked
        client = AlegraClient(user="user", token="token")
        for label, effect in (
            ("read timeout", requests.exceptions.ReadTimeout("slow")),
            ("503", self._response(503, {"message": "upstream"})),
        ):
            with self.subTest(failure=label):
                kwargs = ({"side_effect": effect} if isinstance(effect, Exception)
                          else {"return_value": effect})
                with patch.object(client.session, "request", **kwargs) as request:
                    with self.assertRaises(alegrapy.AlegraAPIError):
                        client.invoices.stamp([11742])
                self.assertEqual(request.call_count, 1)

    def test_400_results_follow_request_order_and_fill_missing_ids(self):
        body = {"data": [{"id": "3", "code": 3226, "message": "ya emitida"},
                         {"id": "1", "code": 4013, "message": "no existe"}]}
        with patch.object(self.client.session, "request",
                          return_value=self._response(400, body)):
            results = self.client.invoices.stamp([1, 2, 3])

        self.assertEqual([r.invoice_id for r in results], ["1", "2", "3"])
        self.assertEqual([r.code for r in results], [4013, None, 3226])
        self.assertFalse(any(r.success for r in results))
        self.assertEqual(results[1].message, "No result returned for this invoice")

    def test_success_requires_a_real_true(self):
        for value in ("false", "true", 1, None):
            with self.subTest(value=value):
                body = {"data": [{"id": "1", "success": value}]}
                with patch.object(self.client.session, "request",
                                  return_value=self._response(200, body)):
                    self.assertFalse(self.client.invoices.stamp([1])[0].success)

    def test_unexpected_200_shape_is_an_api_error_after_send(self):
        with patch.object(self.client.session, "request",
                          return_value=self._response(200, {"unexpected": True})):
            with self.assertRaises(alegrapy.AlegraAPIError) as ctx:
                self.client.invoices.stamp([1])
        self.assertIn("stamp_status", str(ctx.exception))

    def test_non_ascii_digit_codes_do_not_crash_after_send(self):
        body = {"data": [{"id": "1", "code": "\u00b2", "message": "x"}]}
        with patch.object(self.client.session, "request",
                          return_value=self._response(400, body)):
            results = self.client.invoices.stamp([1])
        self.assertIsNone(results[0].code)
        body_ok = {"data": [{"id": "1", "code": "3226", "message": "ya emitida"}]}
        with patch.object(self.client.session, "request",
                          return_value=self._response(400, body_ok)):
            self.assertEqual(self.client.invoices.stamp([1])[0].code, 3226)

    def test_wait_polls_and_truncates_the_last_sleep_to_the_deadline(self):
        pending = {"id": "1", "status": "open", "stamp": {"legalStatus": "PENDING"}}
        # monotonic: deadline base 0; after poll 1 -> 0 (sleep 2), poll 2 -> 2 (sleep 2),
        # poll 3 -> 4 (remaining 1 -> sleep 1), poll 4 -> 5 (remaining 0 -> timeout)
        clock = iter([0.0, 0.0, 2.0, 4.0, 5.0])
        with patch.object(self.client, "query", return_value=pending) as query, \
                patch.object(_INVOICES_TIME, "monotonic", side_effect=lambda: next(clock)), \
                patch.object(_INVOICES_TIME, "sleep") as sleep:
            with self.assertRaises(alegrapy.AlegraStampTimeoutError) as ctx:
                self.client.invoices.wait_until_stamped(1, timeout=5, interval=2)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 2, 1])
        self.assertEqual(query.call_count, 4)
        self.assertEqual(ctx.exception.last_status.state.value, "PENDING")

    def test_blank_observations_are_dropped(self):
        from alegrapy.stamping import stamp_status_from_invoice
        invoice = {"id": "1", "status": "open",
                   "stamp": {"legalStatus": "STAMPED_AND_ACCEPTED",
                             "warnings": ["  ", "", "Regla: FAZ09", None], "errors": "   "}}
        self.assertEqual(stamp_status_from_invoice(invoice).observations, ["Regla: FAZ09"])

    def test_stamp_status_live_get_shape(self):
        invoice = {
            "id": "11742",
            "status": "open",
            "stamp": {
                "legalStatus": "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS",
                "cufe": "abc123cufe",
                "date": "2026-11-18T10:00:00",
                "warnings": ["Regla: FAZ09, Notificación: algo"],
            },
        }
        with patch.object(self.client, "query", return_value=invoice) as mock_query:
            st = self.client.invoices.stamp_status(11742)

        mock_query.assert_called_once_with(
            "get", "https://api.alegra.com/api/v1/invoices/11742", params={}
        )
        self.assertIsInstance(st, StampStatus)
        self.assertEqual(st.invoice_id, "11742")
        self.assertEqual(st.state, StampState.ACCEPTED_WITH_OBSERVATIONS)
        self.assertTrue(st.is_emitted)
        self.assertTrue(st.is_final)
        self.assertEqual(st.observations, ["Regla: FAZ09, Notificación: algo"])
        self.assertEqual(st.cufe, "abc123cufe")
        self.assertEqual(st.stamped_at, "2026-11-18T10:00:00")
        self.assertEqual(st.legal_status_raw, "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS")
        self.assertEqual(st.invoice_status, "open")
        as_dict = st.to_dict()
        self.assertEqual(as_dict["state"], "ACCEPTED_WITH_OBSERVATIONS")
        self.assertTrue(as_dict["is_emitted"])
        json.dumps(as_dict)

    def test_stamp_status_unknown_never_emitted(self):
        invoice = {
            "id": 99,
            "status": "open",
            "stamp": {"legalStatus": "WEIRD_FUTURE_STATE"},
        }
        with patch.object(self.client, "query", return_value=invoice):
            st = self.client.invoices.stamp_status(99)
        self.assertEqual(st.state, StampState.UNKNOWN)
        self.assertFalse(st.is_emitted)
        self.assertFalse(st.is_final)
        self.assertEqual(st.legal_status_raw, "WEIRD_FUTURE_STATE")

    def test_wait_until_stamped_polls_until_accepted(self):
        clock = _FakeClock()
        responses = [
            {"id": 1, "status": "open", "stamp": {"legalStatus": "PENDING"}},
            {"id": 1, "status": "open", "stamp": {"legalStatus": "STAMPED_AND_WAITING_RESPONSE"}},
            {"id": 1, "status": "open", "stamp": {"legalStatus": "STAMPED_AND_ACCEPTED", "cufe": "c1"}},
        ]
        with patch.object(_INVOICES_TIME, "monotonic", clock.monotonic), \
             patch.object(_INVOICES_TIME, "sleep", clock.sleep), \
             patch.object(self.client, "query", side_effect=responses) as mock_query:
            st = self.client.invoices.wait_until_stamped(1, timeout=10.0, interval=2.0)

        self.assertEqual(mock_query.call_count, 3)
        self.assertEqual(clock.sleeps, [2.0, 2.0])
        self.assertEqual(st.state, StampState.ACCEPTED)
        self.assertTrue(st.is_emitted)
        self.assertTrue(st.is_final)

    def test_wait_until_stamped_returns_rejected(self):
        clock = _FakeClock()
        rejected = {
            "id": 1,
            "status": "open",
            "stamp": {"legalStatus": "STAMPED_AND_REJECTED", "errors": ["Error DIAN"]},
        }
        with patch.object(_INVOICES_TIME, "monotonic", clock.monotonic), \
             patch.object(_INVOICES_TIME, "sleep", clock.sleep), \
             patch.object(self.client, "query", return_value=rejected):
            st = self.client.invoices.wait_until_stamped(1, timeout=10.0, interval=2.0)

        self.assertEqual(st.state, StampState.REJECTED)
        self.assertFalse(st.is_emitted)
        self.assertTrue(st.is_final)
        self.assertEqual(st.observations, ["Error DIAN"])

    def test_wait_until_stamped_draft_keeps_polling_and_times_out(self):
        clock = _FakeClock()
        draft = {"id": 1, "status": "draft"}
        with patch.object(_INVOICES_TIME, "monotonic", clock.monotonic), \
             patch.object(_INVOICES_TIME, "sleep", clock.sleep), \
             patch.object(self.client, "query", return_value=draft) as mock_query:
            with self.assertRaises(AlegraStampTimeoutError) as ctx:
                self.client.invoices.wait_until_stamped(1, timeout=5.0, interval=2.0)

        self.assertIsInstance(ctx.exception, AlegraTimeoutError)
        self.assertIsInstance(ctx.exception, AlegraAPIError)
        self.assertIsNotNone(ctx.exception.last_status)
        self.assertEqual(ctx.exception.last_status.state, StampState.DRAFT)
        self.assertGreaterEqual(mock_query.call_count, 2)

    def test_wait_until_stamped_validates_timeout_and_interval(self):
        for kwargs in (
            {"timeout": 0},
            {"timeout": -1},
            {"timeout": float("nan")},
            {"interval": 0},
            {"interval": -0.5},
            {"interval": float("inf")},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.client.invoices.wait_until_stamped(1, **kwargs)

    def test_alegra_shim_reexports_stamping_types(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import alegra

        self.assertIs(alegra.StampState, StampState)
        self.assertIs(alegra.StampStatus, StampStatus)
        self.assertIs(alegra.StampResult, StampResult)
        self.assertIs(alegra.AlegraStampTimeoutError, AlegraStampTimeoutError)


if __name__ == "__main__":
    unittest.main()
