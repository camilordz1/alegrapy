import json
import unittest
from unittest.mock import MagicMock, patch

from alegrapy import AlegraAPIError, AlegraClient, RetryPolicy
from alegrapy.exceptions import AlegraNotFoundError

COMMENTS_URL = "https://api.alegra.com/api/v1/purchase-orders/456/comments"


def _response(status, body):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(body) if body is not None else ""
    resp.json.return_value = body
    resp.headers = {}
    return resp


class TestPurchaseOrderAddCommentErrorBody(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="user", token="token", retry=RetryPolicy(max_retries=0))

    def _add_comment(self, mock_request, status, body):
        mock_request.return_value = _response(status, body)
        return self.client.purchase_orders.add_comment(456, "hello")

    @patch("requests.Session.request")
    def test_missing_order_raises_not_found(self, mock_request):
        body = {"message": "El documento no existe", "code": 37009}
        with self.assertRaises(AlegraNotFoundError) as ctx:
            self._add_comment(mock_request, 200, body)
        exc = ctx.exception
        self.assertEqual(str(exc), "El documento no existe")
        self.assertIsNone(exc.status_code)
        self.assertIn("37009", exc.response_body)
        self.assertEqual(json.loads(exc.response_body), body)
        args, kwargs = mock_request.call_args
        self.assertEqual((kwargs.get("method") or args[0]).lower(), "post")
        self.assertEqual(kwargs.get("url") or args[1], COMMENTS_URL)
        self.assertEqual(kwargs["json"], {"comments": "hello"})

    @patch("requests.Session.request")
    def test_string_code_raises_not_found(self, mock_request):
        with self.assertRaises(AlegraNotFoundError):
            self._add_comment(mock_request, 200, {"message": "x", "code": "37009"})

    @patch("requests.Session.request")
    def test_other_error_code_raises_generic_api_error(self, mock_request):
        with self.assertRaises(AlegraAPIError) as ctx:
            self._add_comment(mock_request, 200, {"message": "Otro error", "code": 10030})
        self.assertNotIsInstance(ctx.exception, AlegraNotFoundError)
        self.assertEqual(str(ctx.exception), "Otro error")
        self.assertIsNone(ctx.exception.status_code)

    @patch("requests.Session.request")
    def test_non_error_bodies_are_returned_unchanged(self, mock_request):
        cases = [
            {"id": 1, "message": "ok", "code": 37009},
            {"code": 200, "message": "ok"},
            {"code": 299, "message": "ok"},
            {"code": True, "message": "ok"},
            {"code": 37009},
            {"code": 37009, "message": "x", "id": "9"},
            {"code": "abc", "message": "x"},
            {"message": "no code"},
            [{"code": 37009, "message": "x"}],
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self._add_comment(mock_request, 200, body), body)

    @patch("requests.Session.request")
    def test_empty_success_returns_empty_dict(self, mock_request):
        self.assertEqual(self._add_comment(mock_request, 204, None), {})

    @patch("requests.Session.request")
    def test_http_404_keeps_typed_error(self, mock_request):
        with self.assertRaises(AlegraNotFoundError) as ctx:
            self._add_comment(mock_request, 404, {"message": "Not found"})
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
