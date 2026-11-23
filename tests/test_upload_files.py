import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from alegrapy import AlegraClient, RetryPolicy


def _mock_response(payload, status=201):
    resp = MagicMock()
    resp.status_code = status
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestUploadFiles(unittest.TestCase):
    """Multipart uploads through the real AlegraClient.query().

    Live 2026-11-23: Alegra answered 400 "El archivo adjunto es un campo obligatorio"
    when the file part had no Content-Type, and 201 once it was sent as image/jpeg.
    """

    def setUp(self):
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _file(self, name, content=b"\xff\xd8\xff\xe0fake-jpeg"):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def _upload(self, resource, path):
        with patch.object(self.client.session, "request",
                          return_value=_mock_response({"id": "1"})) as mock_req:
            getattr(self.client, resource).add_attachment(5, path)
        return mock_req.call_args.kwargs

    def test_file_part_carries_its_mime_type(self):
        cases = [
            ("photo.jpg", "image/jpeg"),
            ("photo.JPEG", "image/jpeg"),
            ("logo.png", "image/png"),
            ("invoice.pdf", "application/pdf"),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                path = self._file(name)
                kw = self._upload("items", path)
                self.assertEqual(kw["url"], "https://api.alegra.com/api/v1/items/5/attachment")
                file_part = kw["files"]["file"]
                self.assertEqual(file_part[0], name)
                self.assertEqual(file_part[1], b"\xff\xd8\xff\xe0fake-jpeg")
                self.assertEqual(file_part[2], expected)
                self.assertIsNone(kw.get("json"))
                self.assertNotEqual(kw["headers"].get("Content-Type"), "application/json")

    def test_unknown_extension_falls_back_to_octet_stream(self):
        path = self._file("data.unknownext")
        self.assertEqual(self._upload("contacts", path)["files"]["file"][2],
                         "application/octet-stream")

    def test_every_attachment_resource_sends_the_mime_type(self):
        path = self._file("photo.jpg")
        for resource in ("invoices", "items", "contacts", "bills", "remissions"):
            with self.subTest(resource=resource):
                self.assertEqual(self._upload(resource, path)["files"]["file"][2], "image/jpeg")


if __name__ == "__main__":
    unittest.main()
