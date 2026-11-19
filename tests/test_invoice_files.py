import errno
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import alegrapy
from alegrapy import AlegraClient, invoices as legacy_invoices

# `alegra.invoices.time` cannot be patched by dotted string: `alegra.invoices` is shadowed
# by the legacy class alias, and Python 3.10's mock resolves the dotted path as a module.
_INVOICES_TIME = importlib.import_module('alegrapy.invoices').time

PDF_URL = "https://cdn.example.com/files/invoice.pdf?Expires=1&Signature=SECRET"
PDF_URL_2 = "https://cdn.example.com/files/invoice-2.pdf?Expires=2&Signature=SECRET2"
URL_B = "https://cdn2.example.com/files/b.pdf?Signature=B"
URL_C = "https://cdn3.example.com/files/c.pdf?Signature=C"
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


def _redirect(location, status=302, url=PDF_URL):
    return _response(status=status, content=b"", url=url, headers={"Location": location})


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
                    with self.assertRaises(alegrapy.AlegraFileNotAvailableError):
                        self.client.invoices.get_pdf(42)
                mock_get.assert_not_called()

    def test_insecure_or_credentialed_file_url_is_rejected(self):
        for url in ("http://cdn.example.com/f.pdf",
                    "https://user:password@cdn.example.com/f.pdf"):
            with self.subTest(url=url):
                self.query.return_value = {"pdf": url}
                with patch('requests.get') as mock_get:
                    with self.assertRaises(alegrapy.AlegraAPIError):
                        self.client.invoices.get_pdf(42)
                mock_get.assert_not_called()

    def test_https_redirect_chain_succeeds(self):
        responses = [_redirect(URL_B), _redirect(URL_C, url=URL_B), _response(url=URL_C)]

        with patch('requests.get', side_effect=responses) as mock_get:
            content = self.client.invoices.get_pdf(42)

        self.assertEqual(content, PDF_BYTES)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual([call.args[0] for call in mock_get.call_args_list],
                         [PDF_URL, URL_B, URL_C])
        for call in mock_get.call_args_list:
            self.assertFalse(call.kwargs.get('allow_redirects', False))
            for forbidden in ('headers', 'cookies', 'auth'):
                self.assertNotIn(forbidden, call.kwargs)

    def test_redirect_to_http_is_rejected_before_requesting_it(self):
        responses = [_redirect("http://evil.example/f.pdf")]

        with patch('requests.get', side_effect=responses) as mock_get:
            with self.assertRaises(alegrapy.AlegraAPIError):
                self.client.invoices.get_pdf(42)

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(mock_get.call_args_list[0].args[0], PDF_URL)

    def test_redirect_chain_rejected_at_the_http_hop(self):
        responses = [_redirect(URL_B), _redirect("http://evil.example/f.pdf", url=URL_B)]

        with patch('requests.get', side_effect=responses) as mock_get:
            with self.assertRaises(alegrapy.AlegraAPIError):
                self.client.invoices.get_pdf(42)

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual([call.args[0] for call in mock_get.call_args_list],
                         [PDF_URL, URL_B])

    def test_relative_redirect_is_resolved(self):
        relative = "/files/relative.pdf?Signature=R"
        responses = [_redirect(relative), _response(url="https://cdn.example.com" + relative)]

        with patch('requests.get', side_effect=responses) as mock_get:
            content = self.client.invoices.get_pdf(42)

        self.assertEqual(content, PDF_BYTES)
        self.assertEqual(mock_get.call_args_list[1].args[0],
                         "https://cdn.example.com" + relative)

    def test_too_many_redirects_are_rejected(self):
        responses = [_redirect(URL_B)] * 6

        with patch('requests.get', side_effect=responses) as mock_get:
            with self.assertRaises(alegrapy.AlegraAPIError) as ctx:
                self.client.invoices.get_pdf(42)

        self.assertIn("too many redirects", str(ctx.exception))
        self.assertEqual(mock_get.call_count, 6)

    def test_redirect_without_location_is_rejected(self):
        with patch('requests.get', return_value=_response(status=302, content=b"", headers={})):
            with self.assertRaises(alegrapy.AlegraAPIError):
                self.client.invoices.get_pdf(42)

    def test_download_deadline_is_enforced(self):
        with patch.object(_INVOICES_TIME, 'monotonic', side_effect=[0.0, 0.0, 100.0]):
            with patch('requests.get', return_value=_response()):
                with self.assertRaises(alegrapy.AlegraTimeoutError):
                    self.client.invoices.get_pdf(42, deadline=10)

    def test_invalid_deadline_is_rejected_before_any_request(self):
        for deadline in (0, -1, True, float("nan"), float("inf"), "10"):
            with self.subTest(deadline=deadline):
                self.query.reset_mock()
                with patch('requests.get') as mock_get:
                    with self.assertRaises(ValueError):
                        self.client.invoices.get_pdf(42, deadline=deadline)
                mock_get.assert_not_called()
                self.query.assert_not_called()

    def test_server_error_is_not_retried_with_a_fresh_url(self):
        with patch('requests.get',
                   return_value=_response(status=500, content=b"")) as mock_get:
            with self.assertRaises(alegrapy.AlegraServerError):
                self.client.invoices.get_pdf(42)

        self.assertEqual(self.query.call_count, 1)
        self.assertEqual(mock_get.call_count, 1)

    def test_invalid_max_bytes_is_rejected_before_any_request(self):
        for max_bytes in (0, -1, True, 1.5, "10"):
            with self.subTest(max_bytes=max_bytes):
                with patch('requests.get') as mock_get:
                    with self.assertRaises(ValueError):
                        self.client.invoices.get_pdf(42, max_bytes=max_bytes)
                mock_get.assert_not_called()
                self.query.assert_not_called()

    def test_get_xml_rejects_non_xml_content(self):
        self.query.return_value = {"xml": XML_URL}
        html = b"<html>SECRET-ERROR-PAGE</html>"
        with patch('requests.get', return_value=_response(html, url=XML_URL)):
            with self.assertRaises(alegrapy.AlegraAPIError) as ctx:
                self.client.invoices.get_xml(42)

        self.assertNotIn("SECRET-ERROR-PAGE", str(ctx.exception))

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
            with self.assertRaises(alegrapy.AlegraAuthError):
                self.client.invoices.get_pdf(42)

        self.assertEqual(mock_get.call_count, 2)

    def test_missing_url_on_refresh_raises_file_not_available(self):
        self.query.side_effect = [{"pdf": PDF_URL}, {"pdf": None}]
        with patch('requests.get', return_value=_response(status=404, content=b"")):
            with self.assertRaises(alegrapy.AlegraFileNotAvailableError):
                self.client.invoices.get_pdf(42)

    def test_wrong_content_is_rejected_without_echoing_it(self):
        html = b"<html>SECRET-ERROR-PAGE</html>"
        with patch('requests.get', return_value=_response(html)):
            with self.assertRaises(alegrapy.AlegraAPIError) as ctx:
                self.client.invoices.get_pdf(42)

        self.assertNotIn("SECRET-ERROR-PAGE", str(ctx.exception))

    def test_size_cap_is_enforced(self):
        with patch('requests.get', return_value=_response(PDF_BYTES)):
            with self.assertRaises(alegrapy.AlegraAPIError):
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

    def test_download_does_not_clobber_a_file_created_during_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"

            def fetch(*args, **kwargs):
                target.write_bytes(b"concurrent")
                return _response()

            with patch('requests.get', side_effect=fetch):
                with self.assertRaises(FileExistsError):
                    self.client.invoices.download_pdf(42, target)

            self.assertEqual(target.read_bytes(), b"concurrent")
            self.assertEqual([path.name for path in Path(directory).iterdir()], ["FE.pdf"])

    def test_download_falls_back_when_hardlinks_are_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"

            with patch('os.link', side_effect=OSError(errno.EPERM, "not supported")):
                with patch('requests.get', return_value=_response()):
                    result = self.client.invoices.download_pdf(42, target)

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), PDF_BYTES)
            self.assertEqual([path.name for path in Path(directory).iterdir()], ["FE.pdf"])

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
                with self.assertRaises(alegrapy.AlegraAPIError):
                    self.client.invoices.download_pdf(42, target)

            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stream_transport_error_is_typed_and_leaves_no_file(self):
        response = _response()
        response.iter_content.side_effect = requests.exceptions.ConnectionError("dropped")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FE.pdf"
            with patch('requests.get', return_value=response):
                with self.assertRaises(alegrapy.AlegraConnectionError):
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
        default_client = sys.modules['alegrapy.session'].default_client
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
