import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import alegra
from alegra import AlegraClient, invoices as legacy_invoices

PDF_URL = "https://cdn.example.com/files/invoice.pdf?Expires=1&Signature=SECRET"
PDF_URL_2 = "https://cdn.example.com/files/invoice-2.pdf?Expires=2&Signature=SECRET2"
XML_URL = "https://files.example.com/invoice.xml?AWSAccessKeyId=x&Signature=SECRET3"

PDF_BYTES = b"%PDF-1.4\nfake pdf body"
XML_BYTES = b'<?xml version="1.0"?><Invoice/>'


def _response(content=PDF_BYTES, status=200, url=PDF_URL, headers=None):
    response = MagicMock()
    response.status_code = status
    response.url = url
    response.headers = headers if headers is not None else {}
    response.text = ""
    response.iter_content.return_value = [content] if content else []
    response.close = MagicMock()
    return response


class TestInvoiceFiles(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="user", token="token")
        self.query = MagicMock(return_value={"pdf": PDF_URL})
        self.client.query = self.query

    def test_get_pdf_returns_bytes(self):
        with patch('requests.get', return_value=_response()) as mock_get:
            content = self.client.invoices.get_pdf(42)

        self.assertEqual(content, PDF_BYTES)
        self.assertEqual(self.query.call_args.kwargs['params'], {'fields': 'pdf'})
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.args[0], PDF_URL)

    def test_get_xml_returns_bytes_and_accepts_utf8_bom(self):
        self.query.return_value = {"xml": XML_URL}
        bom_xml = b"\xef\xbb\xbf" + XML_BYTES

        with patch('requests.get', return_value=_response(bom_xml, url=XML_URL)):
            content = self.client.invoices.get_xml(42)

        self.assertEqual(content, bom_xml)
        self.assertEqual(self.query.call_args.kwargs['params'], {'fields': 'xml'})

    def test_download_never_uses_client_credentials_or_session(self):
        with patch.object(self.client.session, 'request') as session_request:
            with patch('requests.get', return_value=_response()) as mock_get:
                self.client.invoices.get_pdf(42)

        session_request.assert_not_called()
        kwargs = mock_get.call_args.kwargs
        for forbidden in ('headers', 'cookies', 'auth'):
            self.assertNotIn(forbidden, kwargs)

    def test_missing_file_field_raises_file_not_available(self):
        for record in ({}, {"pdf": None}, {"pdf": ""}, {"pdf": "   "}):
            with self.subTest(record=record):
                self.query.return_value = record
                with patch('requests.get') as mock_get:
                    with self.assertRaises(alegra.AlegraFileNotAvailableError):
                        self.client.invoices.get_pdf(42)
                mock_get.assert_not_called()

    def test_insecure_or_credentialed_file_url_is_rejected(self):
        for url in ("http://cdn.example.com/f.pdf",
                    "https://user:password@cdn.example.com/f.pdf"):
            with self.subTest(url=url):
                self.query.return_value = {"pdf": url}
                with patch('requests.get') as mock_get:
                    with self.assertRaises(alegra.AlegraAPIError):
                        self.client.invoices.get_pdf(42)
                mock_get.assert_not_called()

    def test_redirect_to_http_is_rejected(self):
        with patch('requests.get', return_value=_response(url="http://evil.example/f.pdf")):
            with self.assertRaises(alegra.AlegraAPIError):
                self.client.invoices.get_pdf(42)

    def test_expired_url_is_refreshed_once(self):
        self.query.side_effect = [{"pdf": PDF_URL}, {"pdf": PDF_URL_2}]
        responses = [_response(status=403, content=b""), _response()]

        with patch('requests.get', side_effect=responses) as mock_get:
            content = self.client.invoices.get_pdf(42)

        self.assertEqual(content, PDF_BYTES)
        self.assertEqual(self.query.call_count, 2)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1].args[0], PDF_URL_2)

    def test_expired_url_twice_raises_typed_error(self):
        self.query.side_effect = [{"pdf": PDF_URL}, {"pdf": PDF_URL_2}]
        responses = [_response(status=403, content=b""), _response(status=403, content=b"")]

        with patch('requests.get', side_effect=responses) as mock_get:
            with self.assertRaises(alegra.AlegraAuthError):
                self.client.invoices.get_pdf(42)

        self.assertEqual(mock_get.call_count, 2)

    def test_missing_url_on_refresh_raises_file_not_available(self):
        self.query.side_effect = [{"pdf": PDF_URL}, {"pdf": None}]
        with patch('requests.get', return_value=_response(status=404, content=b"")):
            with self.assertRaises(alegra.AlegraFileNotAvailableError):
                self.client.invoices.get_pdf(42)

    def test_wrong_content_is_rejected_without_echoing_it(self):
        html = b"<html>SECRET-ERROR-PAGE</html>"
        with patch('requests.get', return_value=_response(html)):
            with self.assertRaises(alegra.AlegraAPIError) as ctx:
                self.client.invoices.get_pdf(42)

        self.assertNotIn("SECRET-ERROR-PAGE", str(ctx.exception))

    def test_size_cap_is_enforced(self):
        with patch('requests.get', return_value=_response(PDF_BYTES)):
            with self.assertRaises(alegra.AlegraAPIError):
                self.client.invoices.get_pdf(42, max_bytes=5)

    def test_download_writes_atomically_and_returns_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"
            with patch('requests.get', return_value=_response()):
                result = self.client.invoices.download_pdf(42, target)

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), PDF_BYTES)
            self.assertEqual([path.name for path in Path(directory).iterdir()], ["FE.pdf"])

    def test_download_refuses_to_overwrite_before_any_request(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"
            target.write_bytes(b"old")

            with patch('requests.get') as mock_get:
                with self.assertRaises(FileExistsError):
                    self.client.invoices.download_pdf(42, target)

            mock_get.assert_not_called()
            self.query.assert_not_called()
            self.assertEqual(target.read_bytes(), b"old")

    def test_download_overwrite_replaces_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"
            target.write_bytes(b"old")

            with patch('requests.get', return_value=_response()):
                self.client.invoices.download_pdf(42, target, overwrite=True)

            self.assertEqual(target.read_bytes(), PDF_BYTES)

    def test_download_requires_an_existing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing" / "FE.pdf"

            with patch('requests.get') as mock_get:
                with self.assertRaises(FileNotFoundError):
                    self.client.invoices.download_pdf(42, target)

            mock_get.assert_not_called()

    def test_download_leaves_no_partial_file_when_download_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"
            with patch('requests.get', return_value=_response(b"<html>error</html>")):
                with self.assertRaises(alegra.AlegraAPIError):
                    self.client.invoices.download_pdf(42, target)

            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stream_transport_error_is_typed_and_leaves_no_file(self):
        response = _response()
        response.iter_content.side_effect = requests.exceptions.ConnectionError("dropped")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"
            with patch('requests.get', return_value=response):
                with self.assertRaises(alegra.AlegraConnectionError):
                    self.client.invoices.download_pdf(42, target)

            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_logs_include_host_but_never_the_signed_url(self):
        with patch('requests.get', return_value=_response()):
            with self.assertLogs("alegra", level="INFO") as logs:
                self.client.invoices.get_pdf(42)

        output = "\n".join(logs.output)
        self.assertIn("cdn.example.com", output)
        self.assertNotIn("Signature", output)
        self.assertNotIn("SECRET", output)
        self.assertNotIn("Expires", output)

    def test_download_xml_and_legacy_reachability(self):
        default_client = sys.modules['alegra.session'].default_client
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.xml"
            with patch.object(default_client, 'query', return_value={"xml": XML_URL}) as query:
                with patch('requests.get', return_value=_response(XML_BYTES, url=XML_URL)) as mock_get:
                    result = legacy_invoices().download_xml(42, target)

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), XML_BYTES)

        mock_get.assert_called_once()
        query.assert_called_once()


if __name__ == '__main__':
    unittest.main()
