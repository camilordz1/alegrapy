import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import alegrapy
from alegrapy import AlegraClient, AlegraValidationError, Company, RetryPolicy


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestCompany(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_cached_property_export_and_no_collection_methods(self):
        self.assertIsInstance(self.client.company, Company)
        self.assertIs(self.client.company, self.client.company)
        self.assertIn("Company", alegrapy.__all__)
        self.assertIs(alegrapy.Company, Company)
        for forbidden in ("list", "read", "create", "delete", "iter_all"):
            self.assertFalse(hasattr(self.client.company, forbidden), forbidden)
        with self.assertRaises(TypeError):
            Company()

    def test_get_without_fields_and_with_single_or_multiple_fields(self):
        payload = {"name": "ACME", "country": "col"}
        with patch.object(
            self.client.session, "request", return_value=_mock_response(payload)
        ) as mock_req:
            self.assertEqual(self.client.company.get(), payload)
            self.assertEqual(mock_req.call_args.kwargs["method"].lower(), "get")
            self.assertEqual(mock_req.call_args.kwargs["url"], "https://api.alegra.com/api/v1/company")
            self.assertIsNone(mock_req.call_args.kwargs.get("params"))

            self.client.company.get("country")
            self.assertEqual(mock_req.call_args.kwargs["params"], {"fields": "country"})

            self.client.company.get(["country", "status"])
            self.assertEqual(mock_req.call_args.kwargs["params"], {"fields": "country,status"})

    def test_get_validates_fields_before_request(self):
        with patch.object(self.client.session, "request") as mock_req:
            for bad in ("unknown", "", ["country", "bad"], [], 123):
                with self.subTest(fields=bad):
                    with self.assertRaises(ValueError):
                        self.client.company.get(bad)
            mock_req.assert_not_called()

    def test_update_sends_put_and_rejects_non_dict_before_request(self):
        body = {"name": "Nueva Empresa", "decimalPrecision": 2}
        with patch.object(
            self.client.session, "request", return_value=_mock_response(body)
        ) as mock_req:
            res = self.client.company.update(body)

        self.assertEqual(res, body)
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["method"].lower(), "put")
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/company")
        self.assertEqual(kw["json"], body)

        with patch.object(self.client.session, "request") as mock_req:
            for bad in (None, [], "bad", 42):
                with self.subTest(params=bad):
                    with self.assertRaises(ValueError):
                        self.client.company.update(bad)
            mock_req.assert_not_called()

    def test_upload_logo_sends_multipart_without_json_content_type(self):
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        expected = {"file": "https://cdn.example.com/logo.png", "type": "logo"}
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(png_bytes)
            tmp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(tmp_path) and os.unlink(tmp_path))

        self.client.session.headers["Content-Type"] = "application/json"
        with patch.object(
            self.client.session, "request", return_value=_mock_response(expected)
        ) as mock_req:
            res = self.client.company.upload_logo(tmp_path)

        self.assertEqual(res, expected)
        kw = mock_req.call_args.kwargs
        self.assertEqual(kw["method"].lower(), "post")
        self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/company/attachment")
        self.assertIsNone(kw.get("json"))
        self.assertNotIn("Content-Type", kw["headers"])
        self.assertEqual(
            kw["files"],
            {
                "file": (os.path.basename(tmp_path), png_bytes, "image/png"),
                "type": (None, "logo"),
            },
        )

    def test_upload_logo_validates_file_and_surfaces_400(self):
        with patch.object(self.client.session, "request") as mock_req:
            with self.assertRaises(FileNotFoundError):
                self.client.company.upload_logo("/tmp/definitely-missing-logo-12345.png")

            with tempfile.TemporaryDirectory() as tmpdir:
                with self.assertRaises(ValueError):
                    self.client.company.upload_logo(tmpdir)

                txt_path = os.path.join(tmpdir, "notes.txt")
                with open(txt_path, "wb") as f:
                    f.write(b"hello")
                with self.assertRaises(ValueError):
                    self.client.company.upload_logo(txt_path)
            mock_req.assert_not_called()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"\x89PNG")
            tmp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(tmp_path) and os.unlink(tmp_path))

        with patch.object(
            self.client.session,
            "request",
            return_value=_mock_response({"message": "Invalid image"}, status=400),
        ):
            with self.assertRaises(AlegraValidationError):
                self.client.company.upload_logo(tmp_path)


if __name__ == "__main__":
    unittest.main()
