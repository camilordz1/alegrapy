import unittest
from unittest.mock import patch, MagicMock
import base64
import json
import numbers
import sys

import requests

import alegra
from alegra import session, contacts, invoices, payments, items, AlegraClient, AlegraAPIError

class _IntLike:
    """Minimal stand-in for integral types such as numpy.int64."""

    def __init__(self, value):
        self._value = value

    def __int__(self):
        return self._value

    def __index__(self):
        return self._value

    def __ge__(self, other):
        return self._value >= other

    def __repr__(self):
        return f"_IntLike({self._value})"


numbers.Integral.register(_IntLike)


class TestAlegraPy(unittest.TestCase):

    def setUp(self):
        # Reset legacy session configurations
        session.user = None
        session.token = None
        session.url = "https://api.alegra.com/api/v1/"
        session.timeout = 30

        # The legacy class shadows the module on the package, so reach the module itself
        # to reset the global default client's credentials.
        default_client = sys.modules['alegra.session'].default_client
        default_client._user = None
        default_client._token = None

    @patch('requests.Session.request')
    def test_legacy_read_and_list(self, mock_request):
        # Configure mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"id": 123, "name": "Legacy Contact"}'
        mock_response.json.return_value = {"id": 123, "name": "Legacy Contact"}
        mock_request.return_value = mock_response

        # Set legacy global credentials
        session.user = "test_user@example.com"
        session.token = "test_token_123"

        # Legacy contacts instantiation
        c = contacts()
        res = c.read(123)

        self.assertEqual(res, {"id": 123, "name": "Legacy Contact"})
        mock_request.assert_called_once()
        
        # Verify call arguments
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'get')
        self.assertTrue(url.endswith('/contacts/123'))
        
        # Check basic auth header
        headers = kwargs['headers']
        expected_auth = base64.b64encode(b"test_user@example.com:test_token_123").decode()
        self.assertEqual(headers['Authorization'], f"Basic {expected_auth}")

    @patch('requests.Session.request')
    def test_client_read_and_list(self, mock_request):
        # Configure mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '[{"id": 1}, {"id": 2}]'
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]
        mock_request.return_value = mock_response

        # Instantiating client (modern style)
        client = AlegraClient(user="client_user", token="client_token")
        res = client.invoices.list(0, 10, fields='id')

        self.assertEqual(res, [{"id": 1}, {"id": 2}])
        mock_request.assert_called_once()
        
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'get')
        self.assertTrue(url.endswith('/invoices'))
        self.assertEqual(kwargs['params']['start'], 0)
        self.assertEqual(kwargs['params']['limit'], 10)
        self.assertEqual(kwargs['params']['fields'], 'id')
        
        headers = kwargs['headers']
        expected_auth = base64.b64encode(b"client_user:client_token").decode()
        self.assertEqual(headers['Authorization'], f"Basic {expected_auth}")

    @patch('requests.Session.request')
    def test_create_post_payload(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 201  # 201 Created
        mock_response.text = '{"id": 456, "name": "New Item"}'
        mock_response.json.return_value = {"id": 456, "name": "New Item"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        payload = {"name": "New Item", "price": 10.5}
        res = client.items.create(payload)

        self.assertEqual(res, {"id": 456, "name": "New Item"})
        mock_request.assert_called_once()
        
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'post')
        self.assertEqual(kwargs['json'], payload)  # Must be passed as json body!
        self.assertEqual(kwargs.get('params'), {})  # No URL params should be here unless kwargs are passed

    @patch('requests.Session.request')
    def test_update_put_payload(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"id": 456, "name": "Updated Item"}'
        mock_response.json.return_value = {"id": 456, "name": "Updated Item"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        payload = {"name": "Updated Item"}
        res = client.items.update(456, payload)

        self.assertEqual(res, {"id": 456, "name": "Updated Item"})
        mock_request.assert_called_once()
        
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'put')
        self.assertTrue(url.endswith('/items/456'))
        self.assertEqual(kwargs['json'], payload)

    @patch('requests.Session.request')
    def test_delete_http_verb(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "deleted"}'
        mock_response.json.return_value = {"status": "deleted"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        res = client.payments.delete(999)

        self.assertEqual(res, {"status": "deleted"})
        mock_request.assert_called_once()
        
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'delete')
        self.assertTrue(url.endswith('/payments/999'))

    @patch('requests.Session.request')
    def test_error_handling(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"message": "Unauthorized access"}'
        mock_response.json.return_value = {"message": "Unauthorized access"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="bad_user", token="bad_token")
        
        with self.assertRaises(AlegraAPIError) as ctx:
            client.contacts.read(1)
            
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Unauthorized access", str(ctx.exception))

    @patch('requests.Session.request')
    def test_list_defaults(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '[]'
        mock_response.json.return_value = []
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        client.contacts.list()

        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs['params']['start'], 0)
        self.assertEqual(kwargs['params']['limit'], 30)

    @patch('requests.Session.request')
    def test_estimates_void_and_email(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "void"}'
        mock_response.json.return_value = {"status": "void"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        
        # Test void
        res_void = client.estimates.void(123)
        self.assertEqual(res_void, {"status": "void"})
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'post')
        self.assertTrue(url.endswith('/estimates/123/void'))

        # Test email
        client.estimates.send_email(123, "test@example.com", subject="Hello", message="World")
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'post')
        self.assertTrue(url.endswith('/estimates/123/email'))
        self.assertEqual(kwargs['json']['emails'], ["test@example.com"])
        self.assertEqual(kwargs['json']['emailTemplate']['subject'], "Hello")

    @patch('requests.Session.request')
    def test_purchase_orders_add_comment(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "success"}'
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        client.purchase_orders.add_comment(456, "PO Comment")

        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'post')
        self.assertTrue(url.endswith('/purchase-orders/456/comments'))
        self.assertEqual(kwargs['json'], {"comments": "PO Comment"})

    @patch('requests.Session.request')
    def test_bank_accounts_transfer(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "success"}'
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        client.bank_accounts.transfer(1, 2, 100.50, "2026-06-21", "Test description")

        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'post')
        self.assertTrue(url.endswith('/bank-accounts/transfer'))
        self.assertEqual(kwargs['json']['from'], 1)
        self.assertEqual(kwargs['json']['to'], 2)
        self.assertEqual(kwargs['json']['amount'], 100.50)
        self.assertEqual(kwargs['json']['description'], "Test description")

    @patch('requests.Session.request')
    def test_users_self_info(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"email": "me@example.com"}'
        mock_response.json.return_value = {"email": "me@example.com"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        res = client.users.self_info()

        self.assertEqual(res, {"email": "me@example.com"})
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'get')
        self.assertTrue(url.endswith('/users/self'))

    @staticmethod
    def _ok_response():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{}'
        mock_response.json.return_value = {}
        return mock_response

    @patch('requests.Session.request')
    def test_default_timeout_is_passed(self, mock_request):
        mock_request.return_value = self._ok_response()

        client = AlegraClient(user="user", token="token")
        client.contacts.read(1)

        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs['timeout'], 30)

    @patch('requests.Session.request')
    def test_custom_client_timeout_is_passed(self, mock_request):
        mock_request.return_value = self._ok_response()

        client = AlegraClient(user="user", token="token", timeout=5)
        client.contacts.read(1)

        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs['timeout'], 5)

    @patch('requests.Session.request')
    def test_legacy_session_timeout_is_honored(self, mock_request):
        mock_request.return_value = self._ok_response()
        session.timeout = 12

        session.user = "test_user@example.com"
        session.token = "test_token_123"
        contacts().read(1)

        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs['timeout'], 12)

    @patch('requests.Session.request')
    def test_timeout_raises_alegra_api_error(self, mock_request):
        mock_request.side_effect = requests.exceptions.Timeout("timed out")

        client = AlegraClient(user="user", token="token")

        with self.assertRaises(AlegraAPIError) as ctx:
            client.contacts.read(1)

        self.assertIn("HTTP request failed", str(ctx.exception))

    @patch('requests.Session.request')
    def test_read_rejects_path_traversal_id(self, mock_request):
        client = AlegraClient(user="user", token="token")

        with self.assertRaises(ValueError):
            client.contacts.read("1/../../users/self")

        mock_request.assert_not_called()

    @patch('requests.Session.request')
    def test_sub_actions_reject_traversal_id(self, mock_request):
        client = AlegraClient(user="user", token="token")

        with self.assertRaises(ValueError):
            client.invoices.void("1/../../users/self")
        with self.assertRaises(ValueError):
            client.estimates.void("1/../../users/self")
        with self.assertRaises(ValueError):
            client.payments.open("../x")
        with self.assertRaises(ValueError):
            client.purchase_orders.add_comment("1/x", "hi")
        with self.assertRaises(ValueError):
            client.invoices.send_email("1/x", "a@example.com")

        mock_request.assert_not_called()

    @patch('requests.Session.request')
    def test_update_delete_attachment_reject_invalid_id(self, mock_request):
        client = AlegraClient(user="user", token="token")

        with self.assertRaises(ValueError):
            client.items.update("1/x", {"name": "n"})
        with self.assertRaises(ValueError):
            client.items.delete("1/x")
        with self.assertRaises(ValueError):
            client.items.add_attachment("1/x", "dummy.txt")

        mock_request.assert_not_called()

    @patch('requests.Session.request')
    def test_invalid_id_values_are_rejected(self, mock_request):
        client = AlegraClient(user="user", token="token")
        bad_ids = [
            "1?x=y", "1#frag", "1%2F", "1.5", "a b", "..", "", " ",
            True, False, -1, 1.5, None, [1], "1\n",
        ]
        for bad in bad_ids:
            with self.subTest(id=bad):
                with self.assertRaises(ValueError):
                    client.contacts.read(bad)

        mock_request.assert_not_called()

    @patch('requests.Session.request')
    def test_valid_ids_are_accepted(self, mock_request):
        mock_request.return_value = self._ok_response()
        client = AlegraClient(user="user", token="token")

        client.contacts.read(0)
        client.contacts.read(123)
        client.contacts.read("123")
        client.contacts.read("abc_DEF-9")

        urls = [c.args[1] if len(c.args) > 1 else c.kwargs['url']
                for c in mock_request.call_args_list]
        base = "https://api.alegra.com/api/v1/contacts/"
        self.assertEqual(urls, [base + "0", base + "123", base + "123", base + "abc_DEF-9"])

    @patch('requests.Session.request')
    def test_int_like_ids_are_accepted(self, mock_request):
        mock_request.return_value = self._ok_response()
        client = AlegraClient(user="user", token="token")

        client.contacts.read(_IntLike(42))
        client.invoices.void(_IntLike(7))

        urls = [c.args[1] if len(c.args) > 1 else c.kwargs['url']
                for c in mock_request.call_args_list]
        self.assertEqual(urls, [
            "https://api.alegra.com/api/v1/contacts/42",
            "https://api.alegra.com/api/v1/invoices/7/void",
        ])

    @patch('requests.Session.request')
    def test_negative_int_like_id_is_rejected(self, mock_request):
        client = AlegraClient(user="user", token="token")

        with self.assertRaises(ValueError):
            client.contacts.read(_IntLike(-1))

        mock_request.assert_not_called()

    @patch('requests.Session.request')
    def test_constructor_rejects_insecure_or_malformed_urls(self, mock_request):
        bad_urls = [
            "http://evil.example.com/",
            "ftp://x.example.com/",
            "https:///nohost",
            "//api.alegra.com/api/v1/",
            "api.alegra.com/api/v1/",
            "",
        ]
        for bad in bad_urls:
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    AlegraClient(user="user", token="token", url=bad)

        mock_request.assert_not_called()

    @patch('requests.Session.request')
    def test_url_setter_rejects_insecure_or_malformed_urls(self, mock_request):
        client = AlegraClient(user="user", token="token")

        for bad in ["http://evil.example.com/", "ftp://x.example.com/", "https:///nohost"]:
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    client.url = bad

        self.assertEqual(client.url, "https://api.alegra.com/api/v1/")
        mock_request.assert_not_called()

    @patch('requests.Session.request')
    def test_custom_https_url_is_accepted_and_used(self, mock_request):
        mock_request.return_value = self._ok_response()

        client = AlegraClient(user="user", token="token", url="https://custom.example.com/api/v1/")
        client.contacts.read(1)

        args, kwargs = mock_request.call_args
        url = kwargs.get('url') or args[1]
        self.assertEqual(url, "https://custom.example.com/api/v1/contacts/1")

    @patch('requests.Session.request')
    def test_loopback_http_urls_are_accepted(self, mock_request):
        for good in ["http://localhost:8000/api/v1/", "http://127.0.0.1/", "http://[::1]:8000/"]:
            with self.subTest(url=good):
                client = AlegraClient(user="user", token="token", url=good)
                self.assertEqual(client.url, good)
                client.url = good

    @patch('requests.Session.request')
    def test_legacy_insecure_session_url_is_rejected_before_sending(self, mock_request):
        mock_request.return_value = self._ok_response()
        session.user = "test_user@example.com"
        session.token = "test_token_123"
        session.url = "http://evil.example.com/"

        with self.assertRaises(ValueError):
            contacts().read(1)

        mock_request.assert_not_called()

    @staticmethod
    def _basic(user, token):
        return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()

    @patch('requests.Session.request')
    def test_client_with_only_user_does_not_use_global_token(self, mock_request):
        mock_request.return_value = self._ok_response()
        session.user = "global_user"
        session.token = "global_token"

        client = AlegraClient(user="own_user")
        client.contacts.read(1)

        headers = mock_request.call_args.kwargs['headers']
        self.assertNotIn('Authorization', headers)
        self.assertEqual(client.get_auth_header(), "")

    @patch('requests.Session.request')
    def test_client_with_only_token_does_not_use_global_user(self, mock_request):
        mock_request.return_value = self._ok_response()
        session.user = "global_user"
        session.token = "global_token"

        client = AlegraClient(token="own_token")
        client.contacts.read(1)

        self.assertNotIn('Authorization', mock_request.call_args.kwargs['headers'])

    @patch('requests.Session.request')
    def test_client_without_credentials_uses_global_pair(self, mock_request):
        mock_request.return_value = self._ok_response()
        session.user = "global_user"
        session.token = "global_token"

        client = AlegraClient()
        client.contacts.read(1)

        headers = mock_request.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], self._basic("global_user", "global_token"))

    @patch('requests.Session.request')
    def test_client_with_both_credentials_uses_own_pair(self, mock_request):
        mock_request.return_value = self._ok_response()
        session.user = "global_user"
        session.token = "global_token"

        client = AlegraClient(user="own_user", token="own_token")
        client.contacts.read(1)

        headers = mock_request.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], self._basic("own_user", "own_token"))

    @patch('requests.Session.request')
    def test_query_does_not_store_authorization_on_shared_session(self, mock_request):
        mock_request.return_value = self._ok_response()

        client = AlegraClient(user="own_user", token="own_token")
        client.contacts.read(1)

        self.assertNotIn('Authorization', client.session.headers)
        self.assertIn('Authorization', mock_request.call_args.kwargs['headers'])

    @patch('requests.Session.request')
    def test_stale_session_authorization_does_not_leak_without_credentials(self, mock_request):
        mock_request.return_value = self._ok_response()

        client = AlegraClient()
        client.session.headers['Authorization'] = "Basic c3RhbGU6c3RhbGU="
        client.contacts.read(1)

        self.assertNotIn('Authorization', mock_request.call_args.kwargs['headers'])

    @patch('requests.Session.request')
    def test_two_clients_send_their_own_headers(self, mock_request):
        mock_request.return_value = self._ok_response()

        first = AlegraClient(user="user_a", token="token_a")
        second = AlegraClient(user="user_b", token="token_b")
        first.contacts.read(1)
        second.contacts.read(1)
        first.contacts.read(2)

        auth = [c.kwargs['headers']['Authorization'] for c in mock_request.call_args_list]
        self.assertEqual(auth, [
            self._basic("user_a", "token_a"),
            self._basic("user_b", "token_b"),
            self._basic("user_a", "token_a"),
        ])

    @patch('requests.Session.request')
    def test_multipart_request_drops_content_type_per_request(self, mock_request):
        mock_request.return_value = self._ok_response()

        client = AlegraClient(user="user", token="token")
        client.query("post", "https://api.alegra.com/api/v1/contacts/1/attachment",
                     files={"file": ("a.txt", b"x")})

        self.assertNotIn('Content-Type', mock_request.call_args.kwargs['headers'])
        self.assertEqual(client.session.headers['Content-Type'], 'application/json')

    @patch('requests.Session.request')
    def test_error_response_body_is_not_logged(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"message": "SECRET-BODY-123"}'
        mock_response.json.return_value = {"message": "SECRET-BODY-123"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        with self.assertLogs("alegra", level="INFO") as logs:
            with self.assertRaises(AlegraAPIError) as ctx:
                client.contacts.read(1)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("SECRET-BODY-123", ctx.exception.response_body)
        self.assertIn("SECRET-BODY-123", str(ctx.exception))
        for message in logs.output:
            self.assertNotIn("SECRET-BODY-123", message)
        self.assertTrue(any("400" in m for m in logs.output))

    @patch('requests.Session.request')
    def test_non_json_error_body_is_not_logged(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "SECRET-BODY-123 internal trace"
        mock_response.json.side_effect = ValueError("no json")
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        with self.assertLogs("alegra", level="INFO") as logs:
            with self.assertRaises(AlegraAPIError):
                client.contacts.read(1)

        for message in logs.output:
            self.assertNotIn("SECRET-BODY-123", message)

    @patch('requests.Session.request')
    def test_transport_error_text_is_not_logged_or_embedded(self, mock_request):
        original = requests.exceptions.ConnectionError(
            "Max retries exceeded with url: https://api.alegra.com/api/v1/contacts?email=pii@example.com"
        )
        mock_request.side_effect = original

        client = AlegraClient(user="user", token="token")
        with self.assertLogs("alegra", level="INFO") as logs:
            with self.assertRaises(AlegraAPIError) as ctx:
                client.contacts.list(email="pii@example.com")

        for message in logs.output:
            self.assertNotIn("pii@example.com", message)
        self.assertIn("ConnectionError", "".join(logs.output))
        self.assertNotIn("pii@example.com", str(ctx.exception))
        self.assertIs(ctx.exception.__cause__, original)

    @patch('requests.Session.request')
    def test_success_log_has_no_query_string(self, mock_request):
        mock_request.return_value = self._ok_response()

        client = AlegraClient(user="user", token="token")
        with self.assertLogs("alegra", level="INFO") as logs:
            client.query("get", "https://api.alegra.com/api/v1/contacts?email=pii@example.com",
                         params={"query": "pii@example.com"})

        output = "".join(logs.output)
        self.assertNotIn("pii@example.com", output)
        self.assertNotIn("?", output)
        self.assertIn("/contacts", output)
        self.assertIn("200", output)

    def test_base_url_with_userinfo_is_rejected_without_echo(self):
        for bad in ["https://user:pw@api.alegra.com/api/v1/", "https://user@api.alegra.com/api/v1/"]:
            with self.subTest(url=bad):
                with self.assertRaises(ValueError) as ctx:
                    AlegraClient(user="user", token="token", url=bad)
                self.assertNotIn("pw", str(ctx.exception))
                self.assertNotIn(bad, str(ctx.exception))

    def test_base_url_errors_do_not_echo_the_url(self):
        bad = "http://evil.example.com/secret-path"
        with self.assertRaises(ValueError) as ctx:
            AlegraClient(user="user", token="token", url=bad)

        message = str(ctx.exception)
        self.assertNotIn(bad, message)
        self.assertNotIn("secret-path", message)
        for host in ("localhost", "127.0.0.1", "::1"):
            self.assertIn(host, message)

    def test_constructor_validates_through_url_setter(self):
        with patch.object(AlegraClient, "url", new_callable=unittest.mock.PropertyMock) as prop:
            AlegraClient(user="user", token="token", url="https://custom.example.com/")
        prop.assert_called_with("https://custom.example.com/")

    @patch('os.path.exists')
    @patch('builtins.open', create=True)
    @patch('requests.Session.request')
    def test_add_attachment(self, mock_request, mock_open, mock_exists):
        mock_exists.return_value = True
        mock_open.return_value.__enter__.return_value.read.return_value = b"test content"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "uploaded"}'
        mock_response.json.return_value = {"status": "uploaded"}
        mock_request.return_value = mock_response

        client = AlegraClient(user="user", token="token")
        res = client.contacts.add_attachment(99, "dummy.txt")

        self.assertEqual(res, {"status": "uploaded"})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        method = kwargs.get('method') or args[0]
        url = kwargs.get('url') or args[1]
        self.assertEqual(method.lower(), 'post')
        self.assertTrue(url.endswith('/contacts/99/attachment'))
        self.assertIn('files', kwargs)
        self.assertEqual(kwargs['files']['file'][0], 'dummy.txt')

if __name__ == '__main__':
    unittest.main()

