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
        from alegra import RetryPolicy
        session.retry = RetryPolicy(max_retries=0)

        # The legacy class shadows the module on the package, so reach the module itself
        # to reset the global default client's credentials.
        default_client = sys.modules['alegra.session'].default_client
        default_client._user = None
        default_client._token = None
        default_client._retry = None

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

class TestTypedExceptions(unittest.TestCase):
    """Typed errors reachable without breaking `except AlegraAPIError`."""

    def setUp(self):
        session.user = None
        session.token = None
        session.url = "https://api.alegra.com/api/v1/"
        session.timeout = 30
        from alegra import RetryPolicy
        session.retry = RetryPolicy(max_retries=0)
        default_client = sys.modules['alegra.session'].default_client
        default_client._user = None
        default_client._token = None
        default_client._retry = None

    @staticmethod
    def _response(status_code, headers=None):
        response = MagicMock()
        response.status_code = status_code
        response.text = '{"message": "boom"}'
        response.json.return_value = {"message": "boom"}
        response.headers = headers if headers is not None else {}
        return response

    def _error_for_response(self, response):
        with patch('requests.Session.request', return_value=response):
            client = AlegraClient(user="user", token="token")
            with self.assertRaises(AlegraAPIError) as ctx:
                client.contacts.read(1)
        return ctx.exception

    def _error_for_transport(self, original):
        with patch('requests.Session.request', side_effect=original):
            client = AlegraClient(user="user", token="token")
            with self.assertRaises(AlegraAPIError) as ctx:
                client.contacts.list()
        return ctx.exception

    def test_status_codes_map_to_typed_errors(self):
        from alegra import (AlegraAuthError, AlegraNotFoundError, AlegraValidationError,
                            AlegraRateLimitError, AlegraServerError)
        expected = {
            400: AlegraValidationError,
            401: AlegraAuthError,
            403: AlegraAuthError,
            404: AlegraNotFoundError,
            422: AlegraValidationError,
            429: AlegraRateLimitError,
            500: AlegraServerError,
            503: AlegraServerError,
            409: AlegraAPIError,
        }
        for status, cls in expected.items():
            with self.subTest(status=status):
                error = self._error_for_response(self._response(status))
                self.assertIs(type(error), cls)

    def test_typed_errors_subclass_base_and_keep_attributes(self):
        from alegra import AlegraNotFoundError
        error = self._error_for_response(self._response(404))

        self.assertIsInstance(error, AlegraAPIError)
        self.assertIsInstance(error, AlegraNotFoundError)
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.response_body, '{"message": "boom"}')
        self.assertEqual(str(error), "boom")

    def test_connect_timeout_is_a_connection_error(self):
        from alegra import AlegraConnectionError
        from requests.exceptions import ConnectTimeout

        original = ConnectTimeout("connection timed out before sending")
        error = self._error_for_transport(original)

        self.assertIs(type(error), AlegraConnectionError)
        self.assertIs(error.__cause__, original)
        self.assertIsNone(error.status_code)
        self.assertIsNone(error.response_body)

    def test_read_timeout_is_a_timeout_error(self):
        from alegra import AlegraTimeoutError
        from requests.exceptions import ReadTimeout

        original = ReadTimeout("waiting for the response timed out")
        error = self._error_for_transport(original)

        self.assertIs(type(error), AlegraTimeoutError)
        self.assertIs(error.__cause__, original)
        self.assertIsNone(error.status_code)

    def test_connection_error_is_a_connection_error(self):
        from alegra import AlegraConnectionError
        from requests.exceptions import ConnectionError as RequestsConnectionError

        original = RequestsConnectionError("dns failure")
        error = self._error_for_transport(original)

        self.assertIs(type(error), AlegraConnectionError)
        self.assertIs(error.__cause__, original)

    def test_other_request_exceptions_stay_base_class(self):
        from requests.exceptions import TooManyRedirects

        original = TooManyRedirects("too many redirects")
        error = self._error_for_transport(original)

        self.assertIs(type(error), AlegraAPIError)
        self.assertIs(error.__cause__, original)

    def test_retry_after_delta_seconds(self):
        error = self._error_for_response(self._response(429, {"Retry-After": "7"}))

        self.assertEqual(error.retry_after, 7.0)

    def test_retry_after_http_date(self):
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime

        target = datetime.now(timezone.utc) + timedelta(seconds=90)
        header = format_datetime(target, usegmt=True)
        error = self._error_for_response(self._response(503, {"Retry-After": header}))

        self.assertAlmostEqual(error.retry_after, 90, delta=5)

    def test_retry_after_negative_is_zero(self):
        error = self._error_for_response(self._response(429, {"Retry-After": "-5"}))

        self.assertEqual(error.retry_after, 0.0)

    def test_retry_after_unparseable_is_none(self):
        error = self._error_for_response(self._response(429, {"Retry-After": "soon"}))

        self.assertIsNone(error.retry_after)

    def test_retry_after_missing_is_none(self):
        error = self._error_for_response(self._response(500))

        self.assertIsNone(error.retry_after)

    @patch('requests.Session.request')
    def test_legacy_path_raises_typed_errors(self, mock_request):
        from alegra import AlegraNotFoundError

        mock_request.return_value = self._response(404)
        session.user = "legacy_user@example.com"
        session.token = "legacy_token"

        with self.assertRaises(AlegraNotFoundError) as ctx:
            contacts().read(1)

        self.assertEqual(ctx.exception.status_code, 404)

    def test_non_request_exception_propagates_unwrapped(self):
        original = TypeError("Object of type Decimal is not JSON serializable")
        with patch('requests.Session.request', side_effect=original):
            client = AlegraClient(user="user", token="token")
            with self.assertNoLogs("alegra", level="ERROR"):
                with self.assertRaises(TypeError) as ctx:
                    client.contacts.list()

        self.assertIs(ctx.exception, original)

    def test_204_returns_empty_dict(self):
        response = self._response(204)
        response.text = ""

        with patch('requests.Session.request', return_value=response):
            client = AlegraClient(user="user", token="token")
            self.assertEqual(client.contacts.read(1), {})

    def test_empty_or_whitespace_body_returns_empty_dict(self):
        for body in ("", "   \n\t "):
            with self.subTest(body=repr(body)):
                response = self._response(200)
                response.text = body

                with patch('requests.Session.request', return_value=response):
                    client = AlegraClient(user="user", token="token")
                    self.assertEqual(client.contacts.read(1), {})

    def test_non_json_success_body_returns_response_text(self):
        response = self._response(200)
        response.text = "plain text answer"
        response.json.side_effect = ValueError("no json")

        with patch('requests.Session.request', return_value=response):
            client = AlegraClient(user="user", token="token")
            self.assertEqual(client.contacts.read(1), {"response_text": "plain text answer"})

    def test_error_with_non_dict_json_uses_generic_message(self):
        from alegra import AlegraRateLimitError

        response = self._response(429)
        response.text = '["rate limited"]'
        response.json.return_value = ["rate limited"]

        error = self._error_for_response(response)

        self.assertIs(type(error), AlegraRateLimitError)
        self.assertEqual(str(error), "API error (Status 429)")
        self.assertEqual(error.response_body, '["rate limited"]')

    def test_error_without_message_uses_generic_message(self):
        from alegra import AlegraValidationError

        response = self._response(400)
        response.text = '{"errors": "invalid"}'
        response.json.return_value = {"errors": "invalid"}

        error = self._error_for_response(response)

        self.assertIs(type(error), AlegraValidationError)
        self.assertEqual(str(error), "API error (Status 400)")

    def test_error_with_non_json_body_uses_body_as_message(self):
        from alegra import AlegraServerError

        response = self._response(503)
        response.text = "upstream unavailable"
        response.json.side_effect = ValueError("no json")

        error = self._error_for_response(response)

        self.assertIs(type(error), AlegraServerError)
        self.assertEqual(str(error), "upstream unavailable")

    def test_public_imports(self):
        from alegra import AlegraNotFoundError
        from alegra.exceptions import AlegraAPIError as ModuleError
        from alegra.session import AlegraAPIError as LegacyImport

        self.assertIs(ModuleError, AlegraAPIError)
        self.assertIs(LegacyImport, AlegraAPIError)
        self.assertTrue(issubclass(AlegraNotFoundError, AlegraAPIError))
        self.assertIn("AlegraNotFoundError", alegra.__all__)


class TestRetries(unittest.TestCase):
    """Retries are bounded, backed off and never unsafe for non-idempotent requests."""

    URL = "https://api.alegra.com/api/v1/contacts"

    def setUp(self):
        session.user = None
        session.token = None
        session.url = "https://api.alegra.com/api/v1/"
        session.timeout = 30
        session.retry = None
        default_client = sys.modules['alegra.session'].default_client
        default_client._user = None
        default_client._token = None
        default_client._retry = None

    @staticmethod
    def _response(status_code, body='{"message": "boom"}', headers=None):
        import json as json_module

        response = MagicMock()
        response.status_code = status_code
        response.text = body
        response.headers = headers if headers is not None else {}
        try:
            response.json.return_value = json_module.loads(body)
        except ValueError:
            response.json.side_effect = ValueError("no json")
        return response

    @staticmethod
    def _policy(**kwargs):
        from alegra import RetryPolicy
        return RetryPolicy(**kwargs)

    def _client(self, retry=None):
        return AlegraClient(user="user", token="token", retry=retry)

    def _get(self, client):
        return client.query("get", self.URL)

    def _post(self, client):
        return client.query("post", self.URL, data={"total": 100})

    def test_get_retries_503_then_succeeds(self):
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [self._response(503), self._response(200, '{"id": 1}')]
            with patch('alegra.retry.time.sleep') as mock_sleep:
                result = self._get(self._client())

        self.assertEqual(result, {"id": 1})
        self.assertEqual(mock_request.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

    def test_get_honors_retry_after(self):
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [
                self._response(429, headers={"Retry-After": "3"}),
                self._response(200, '{"id": 1}'),
            ]
            with patch('alegra.retry.time.sleep') as mock_sleep:
                result = self._get(self._client())

        self.assertEqual(result, {"id": 1})
        mock_sleep.assert_called_once_with(3.0)

    def test_get_uses_x_rate_limit_reset_when_retry_after_is_absent(self):
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [
                self._response(429, headers={"X-Rate-Limit-Reset": "12"}),
                self._response(200, '{"id": 1}'),
            ]
            with patch('alegra.retry.time.sleep') as mock_sleep:
                self._get(self._client())

        mock_sleep.assert_called_once_with(12.0)

    def test_get_retries_read_timeout(self):
        from requests.exceptions import ReadTimeout

        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [ReadTimeout("slow"), self._response(200, '{"id": 1}')]
            with patch('alegra.retry.time.sleep'):
                result = self._get(self._client())

        self.assertEqual(result, {"id": 1})
        self.assertEqual(mock_request.call_count, 2)

    def test_exhausted_retries_raise_last_error_with_cause(self):
        from requests.exceptions import ConnectionError as RequestsConnectionError

        originals = [RequestsConnectionError("first"), RequestsConnectionError("second"),
                     RequestsConnectionError("third")]
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = list(originals)
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(AlegraAPIError) as ctx:
                    self._get(self._client())

        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertIs(type(ctx.exception), alegra.AlegraConnectionError)
        self.assertIs(ctx.exception.__cause__, originals[-1])

    def test_max_retries_zero_makes_one_attempt(self):
        policy = self._policy(max_retries=0)
        with patch('requests.Session.request') as mock_request:
            mock_request.return_value = self._response(503)
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(alegra.AlegraServerError):
                    self._get(self._client(retry=policy))

        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_post_503_is_not_retried(self):
        with patch('requests.Session.request') as mock_request:
            mock_request.return_value = self._response(503)
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(alegra.AlegraServerError):
                    self._post(self._client())

        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_post_read_timeout_is_not_retried(self):
        from requests.exceptions import ReadTimeout

        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = ReadTimeout("maybe created")
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(alegra.AlegraTimeoutError):
                    self._post(self._client())

        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_post_connection_error_after_sending_is_not_retried(self):
        import urllib3
        from requests.exceptions import ConnectionError as RequestsConnectionError

        original = RequestsConnectionError(urllib3.exceptions.ProtocolError("Connection aborted."))
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = original
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(alegra.AlegraConnectionError):
                    self._post(self._client())

        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_post_connect_timeout_is_retried(self):
        from requests.exceptions import ConnectTimeout

        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [ConnectTimeout("never sent"), self._response(201, '{"id": 2}')]
            with patch('alegra.retry.time.sleep'):
                result = self._post(self._client())

        self.assertEqual(result, {"id": 2})
        self.assertEqual(mock_request.call_count, 2)

    def test_post_connection_refused_is_retried(self):
        import urllib3
        from requests.exceptions import ConnectionError as RequestsConnectionError

        refused = urllib3.exceptions.MaxRetryError(
            None, "/", reason=urllib3.exceptions.NewConnectionError(None, "Connection refused")
        )
        original = RequestsConnectionError(refused)
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [original, self._response(201, '{"id": 2}')]
            with patch('alegra.retry.time.sleep'):
                result = self._post(self._client())

        self.assertEqual(result, {"id": 2})
        self.assertEqual(mock_request.call_count, 2)

    def test_post_429_is_retried(self):
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [
                self._response(429, headers={"Retry-After": "1"}),
                self._response(201, '{"id": 2}'),
            ]
            with patch('alegra.retry.time.sleep') as mock_sleep:
                result = self._post(self._client())

        self.assertEqual(result, {"id": 2})
        mock_sleep.assert_called_once_with(1.0)

    def test_requests_with_files_are_never_retried(self):
        with patch('requests.Session.request') as mock_request:
            mock_request.return_value = self._response(503)
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(alegra.AlegraServerError):
                    self._client().query("get", self.URL, files={"file": ("a.txt", b"x")})

        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_retry_after_above_max_raises_immediately(self):
        policy = self._policy(max_retry_after=2.0)
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [
                self._response(429, headers={"Retry-After": "10"}),
                self._response(200, '{"id": 1}'),
            ]
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(alegra.AlegraRateLimitError):
                    self._get(self._client(retry=policy))

        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_backoff_uses_full_jitter_bounds(self):
        policy = self._policy(max_retries=2, backoff_factor=0.5, backoff_max=30.0)
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [
                self._response(503),
                self._response(503),
                self._response(200, '{"id": 1}'),
            ]
            with patch('alegra.retry.random.uniform', return_value=0.25) as mock_uniform:
                with patch('alegra.retry.time.sleep') as mock_sleep:
                    result = self._get(self._client(retry=policy))

        self.assertEqual(result, {"id": 1})
        self.assertEqual(mock_uniform.call_args_list, [unittest.mock.call(0, 0.5),
                                                      unittest.mock.call(0, 1.0)])
        self.assertEqual(mock_sleep.call_args_list, [unittest.mock.call(0.25),
                                                     unittest.mock.call(0.25)])

    def test_other_statuses_and_ssl_errors_are_not_retried(self):
        import requests

        cases = [
            ("500", self._response(500)),
            ("400", self._response(400)),
            ("404", self._response(404)),
        ]
        for label, response in cases:
            with self.subTest(status=label):
                with patch('requests.Session.request') as mock_request:
                    mock_request.return_value = response
                    with patch('alegra.retry.time.sleep') as mock_sleep:
                        with self.assertRaises(AlegraAPIError):
                            self._get(self._client())
                self.assertEqual(mock_request.call_count, 1)
                mock_sleep.assert_not_called()

        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = requests.exceptions.SSLError("bad certificate")
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(AlegraAPIError):
                    self._get(self._client())
        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_non_request_exception_is_not_retried(self):
        original = TypeError("Object of type Decimal is not JSON serializable")
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = original
            with patch('alegra.retry.time.sleep') as mock_sleep:
                with self.assertRaises(TypeError) as ctx:
                    self._post(self._client())

        self.assertIs(ctx.exception, original)
        self.assertEqual(mock_request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_retry_warning_has_no_query_string(self):
        with patch('requests.Session.request') as mock_request:
            mock_request.side_effect = [self._response(503), self._response(200, '{"id": 1}')]
            with patch('alegra.retry.time.sleep'):
                with self.assertLogs("alegra", level="WARNING") as logs:
                    self._client().query("get", self.URL, params={"email": "pii@example.com"})

        output = "\n".join(logs.output)
        self.assertIn("retrying in", output)
        self.assertIn("/contacts", output)
        self.assertIn("attempt 1/2", output)
        self.assertIn("AlegraServerError", output)
        self.assertNotIn("pii@example.com", output)
        self.assertNotIn("?", output)

    def test_was_not_sent_with_real_exception_objects(self):
        import urllib3
        from http.client import RemoteDisconnected
        from requests.exceptions import (ConnectTimeout, ConnectionError as RequestsConnectionError,
                                         ReadTimeout, SSLError)
        from alegra.retry import _was_not_sent

        refused = urllib3.exceptions.MaxRetryError(
            None, "/", reason=urllib3.exceptions.NewConnectionError(None, "refused")
        )
        remote_closed = RemoteDisconnected("Remote end closed connection")

        self.assertTrue(_was_not_sent(ConnectTimeout("connect timed out")))
        self.assertTrue(_was_not_sent(RequestsConnectionError(refused)))
        self.assertFalse(_was_not_sent(RequestsConnectionError(remote_closed)))
        self.assertFalse(_was_not_sent(RequestsConnectionError(
            urllib3.exceptions.ProtocolError("Connection aborted."))))
        self.assertFalse(_was_not_sent(ReadTimeout("read timed out")))
        self.assertFalse(_was_not_sent(SSLError("bad certificate")))
        self.assertFalse(_was_not_sent(ValueError("not a request error")))

    def test_retry_policy_defaults_and_validation(self):
        policy = self._policy()
        self.assertEqual(policy.max_retries, 2)
        self.assertEqual(policy.backoff_factor, 0.5)
        self.assertEqual(policy.backoff_max, 30.0)
        self.assertEqual(policy.retry_statuses, frozenset({429, 502, 503, 504}))
        self.assertEqual(policy.max_retry_after, 60.0)

        invalid = [
            {"max_retries": -1},
            {"max_retries": 1.5},
            {"max_retries": True},
            {"backoff_factor": -0.1},
            {"backoff_max": -1},
            {"max_retry_after": -1},
            {"retry_statuses": frozenset({99})},
            {"retry_statuses": frozenset({"429"})},
        ]
        for kwargs in invalid:
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    self._policy(**kwargs)

    def test_legacy_session_retry_fallback(self):
        session.retry = self._policy(max_retries=0)
        client = AlegraClient()

        self.assertEqual(client.retry.max_retries, 0)

        own = self._policy(max_retries=5)
        self.assertIs(AlegraClient(retry=own).retry, own)

    def test_retry_policy_is_exported(self):
        from alegra import RetryPolicy
        self.assertIs(alegra.RetryPolicy, RetryPolicy)
        self.assertIn("RetryPolicy", alegra.__all__)


if __name__ == '__main__':
    unittest.main()

