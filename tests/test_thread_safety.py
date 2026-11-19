import base64
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from alegrapy import AlegraClient, RetryPolicy


class _EchoAuthHandler(BaseHTTPRequestHandler):
    """Echo the Authorization header and try to set a cookie."""

    def do_GET(self):
        payload = json.dumps({"authorization": self.headers.get("Authorization")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "session=abc; Path=/")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # keep the test output clean
        pass


def _basic(user, token):
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


class TestThreadSafety(unittest.TestCase):

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoAuthHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)

    def _client(self, user="user", token="token"):
        return AlegraClient(user=user, token=token, url=self.base_url, timeout=5,
                            retry=RetryPolicy(max_retries=0))

    def test_two_clients_do_not_mix_credentials_under_concurrency(self):
        pairs = [
            (self._client("first@example.com", "token-one"), _basic("first@example.com", "token-one")),
            (self._client("second@example.com", "token-two"), _basic("second@example.com", "token-two")),
        ]

        def call(index):
            client, expected = pairs[index % 2]
            received = client.contacts.list()["authorization"]
            return received == expected

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(call, range(200)))

        self.assertEqual(len(results), 200)
        self.assertTrue(all(results))

    def test_one_shared_client_never_changes_credentials(self):
        client = self._client("shared@example.com", "shared-token")
        expected = _basic("shared@example.com", "shared-token")

        def call(_):
            return client.contacts.list()["authorization"] == expected

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(call, range(100)))

        self.assertTrue(all(results))

    def test_lazy_resources_can_be_first_accessed_from_many_threads(self):
        client = AlegraClient(user="lazy@example.com", token="lazy-token", url=self.base_url,
                              timeout=5, retry=RetryPolicy(max_retries=0))
        expected = _basic("lazy@example.com", "lazy-token")
        barrier = threading.Barrier(16)

        def call(index):
            barrier.wait(timeout=5)
            resource = (client.contacts, client.invoices, client.items)[index % 3]
            received = client.contacts.list()["authorization"]
            return resource is not None and received == expected

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(call, range(16)))

        self.assertEqual(len(results), 16)
        self.assertTrue(all(results))

    def test_cookies_from_responses_are_not_stored(self):
        client = self._client()

        client.contacts.list()

        self.assertEqual(len(client.session.cookies), 0)

    def test_close_is_idempotent_with_the_real_session(self):
        client = self._client()

        with patch.object(client.session, 'close', wraps=client.session.close) as spy:
            client.close()
            client.close()

        self.assertEqual(spy.call_count, 2)

    def test_context_manager_returns_client_and_closes(self):
        client = self._client()

        with patch.object(client.session, "close") as mock_close:
            with client as entered:
                self.assertIs(entered, client)
            mock_close.assert_called_once()

    def test_context_manager_closes_and_propagates_exceptions(self):
        client = self._client()

        with patch.object(client.session, "close") as mock_close:
            with self.assertRaises(RuntimeError):
                with client:
                    raise RuntimeError("boom")

        mock_close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
