import unittest
from unittest.mock import patch, MagicMock
import base64
import json

import alegra
from alegra import session, contacts, invoices, payments, items, AlegraClient, AlegraAPIError

class TestAlegraPy(unittest.TestCase):

    def setUp(self):
        # Reset legacy session configurations
        session.user = None
        session.token = None
        session.url = "https://api.alegra.com/api/v1/"
        
        # We also reset any default client state if needed
        # (This will be defined in session.py later)
        if hasattr(session, 'default_client'):
            session.default_client._user = None
            session.default_client._token = None

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

