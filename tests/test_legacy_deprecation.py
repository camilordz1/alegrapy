import importlib
import sys
import unittest
import warnings
from unittest.mock import MagicMock, patch

from alegrapy import AlegraClient, RetryPolicy, contacts, invoices, items, session


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = "[]" if isinstance(payload, list) else "{}"
    resp.json.return_value = payload
    resp.headers = {}
    return resp


class TestLegacyDeprecationWarnings(unittest.TestCase):

    def setUp(self):
        from alegrapy._deprecation import reset_legacy_warnings
        from alegrapy.session import _default_client

        reset_legacy_warnings()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            session.user = None
            session.token = None
            session.url = "https://api.alegra.com/api/v1/"
            session.timeout = 30
            session.retry = None
        session.headers.pop("Authorization", None)
        _default_client._user = None
        _default_client._token = None
        _default_client._retry = None
        reset_legacy_warnings()

    def test_session_setattr_warns_once_per_attribute(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            session.user = "u1"
            session.user = "u2"
        future = [w for w in caught if issubclass(w.category, FutureWarning)]
        self.assertEqual(len(future), 1)
        self.assertIn("session.user is deprecated", str(future[0].message))
        self.assertIn("AlegraClient", str(future[0].message))

    def test_session_query_warns_once(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            session.user = "u"
            session.token = "t"
            with patch("requests.Session.request", return_value=_mock_response([])):
                session.query("get", "https://api.alegra.com/api/v1/contacts")
                session.query("get", "https://api.alegra.com/api/v1/contacts")
        msgs = [
            str(w.message) for w in caught
            if issubclass(w.category, FutureWarning) and "session.query()" in str(w.message)
        ]
        self.assertEqual(len(msgs), 1)

    def test_create_auth_warns_and_is_noop_with_no_authorization_in_headers(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            session.user = "secret-user"
            session.token = "secret-token"
            session.headers["Authorization"] = "Basic stale"
            session.create_auth()
            session.create_auth()
        self.assertNotIn("Authorization", session.headers)
        msgs = [
            str(w.message) for w in caught
            if issubclass(w.category, FutureWarning) and "session.create_auth()" in str(w.message)
        ]
        self.assertEqual(len(msgs), 1)

    def test_default_client_getattr_warns_once(self):
        session_mod = importlib.import_module("alegrapy.session")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            c1 = session_mod.default_client
            c2 = session_mod.default_client
        self.assertIs(c1, c2)
        msgs = [
            str(w.message) for w in caught
            if issubclass(w.category, FutureWarning) and "default_client" in str(w.message)
        ]
        self.assertEqual(len(msgs), 1)

    def test_actions_default_client_fallback_warns_once(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = invoices().client
            _ = contacts().client
        msgs = [
            str(w.message) for w in caught
            if issubclass(w.category, FutureWarning) and "without an explicit AlegraClient" in str(w.message)
        ]
        self.assertEqual(len(msgs), 1)

    def test_client_query_fallback_warns_once_for_global_overrides(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            session.user = "legacy-u"
            session.token = "legacy-t"
            session.url = "https://custom.alegra.test/api/v1"
            session.timeout = 12
            session.retry = RetryPolicy(max_retries=0)

        client = AlegraClient()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with patch.object(client.session, "request", return_value=_mock_response([])):
                client.contacts.list()
                client.contacts.list()
        future = [str(w.message) for w in caught if issubclass(w.category, FutureWarning)]
        self.assertEqual(len(future), 4)
        joined = "\n".join(future)
        self.assertIn("session.user/session.token", joined)
        self.assertIn("session.url", joined)
        self.assertIn("session.timeout", joined)
        self.assertIn("session.retry", joined)

    def test_modern_flow_emits_zero_warnings(self):
        client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

        def fake_request(**kwargs):
            url = kwargs["url"]
            method = kwargs["method"].lower()
            if url.endswith("/invoices/stamp"):
                return _mock_response({
                    "data": [{
                        "id": "11742",
                        "success": True,
                        "emissionStatus": "STAMPED_AND_ACCEPTED",
                        "message": "OK",
                    }]
                })
            if url.endswith("/invoices") and method == "post":
                return _mock_response({"id": 11742, "observations": "alegrapy:dedup:k1"})
            return _mock_response([])

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with patch.object(client.session, "request", side_effect=fake_request) as mock_req:
                client.contacts.list()
                client.invoices.create_once(
                    {"client": {"id": 1}, "items": [{"id": 1}]},
                    dedup_key="k1",
                )
                client.invoices.stamp([11742])

        urls = [call.kwargs["url"] for call in mock_req.call_args_list]
        self.assertEqual(urls, [
            "https://api.alegra.com/api/v1/contacts",
            "https://api.alegra.com/api/v1/invoices",
            "https://api.alegra.com/api/v1/invoices",
            "https://api.alegra.com/api/v1/invoices/stamp",
        ])

    def test_legacy_behavior_still_sends_basic_auth_header(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            session.user = "u@example.com"
            session.token = "tok123"
            session.retry = RetryPolicy(max_retries=0)
            with patch("requests.Session.request", return_value=_mock_response([])) as mock_req:
                res = contacts().list()
        self.assertEqual(res, [])
        auth = mock_req.call_args.kwargs["headers"]["Authorization"]
        self.assertTrue(auth.startswith("Basic "))

    def test_alegra_shim_still_reexports_session_and_resources(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import alegra
        self.assertIs(alegra.session, session)
        self.assertIs(alegra.items, items)




class TestLegacyWarningLocation(unittest.TestCase):
    """Each legacy warning must point at the caller's line, not at alegrapy internals."""

    def setUp(self):
        from alegrapy._deprecation import reset_legacy_warnings

        self.session_module = importlib.import_module("alegrapy.session")
        self.saved = {name: getattr(session, name)
                      for name in ("user", "token", "url", "timeout", "retry")}
        reset_legacy_warnings()
        self.addCleanup(self._restore)

    def _restore(self):
        from alegrapy._deprecation import reset_legacy_warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            for name, value in self.saved.items():
                setattr(session, name, value)
        reset_legacy_warnings()

    def _assert_points_here(self, action):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            action()
        future = [w for w in caught if issubclass(w.category, FutureWarning)]
        self.assertTrue(future, "expected a FutureWarning")
        for w in future:
            self.assertEqual(w.filename, __file__, str(w.message))

    def test_setattr_points_at_caller(self):
        self._assert_points_here(lambda: setattr(session, "user", "u"))

    def test_create_auth_points_at_caller(self):
        self._assert_points_here(session.create_auth)

    def test_default_client_access_points_at_caller(self):
        def access():
            from alegrapy.session import default_client  # noqa: F401
        self._assert_points_here(access)

    def test_resource_and_client_fallbacks_point_at_caller(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            session.user = "u"
            session.token = "t"
        from alegrapy._deprecation import reset_legacy_warnings
        reset_legacy_warnings()
        client = self.session_module._default_client
        with patch.object(client.session, "request", return_value=_mock_response([])):
            self._assert_points_here(lambda: contacts().list())

    def test_session_query_points_at_caller(self):
        client = self.session_module._default_client
        with patch.object(client.session, "request", return_value=_mock_response([])):
            self._assert_points_here(
                lambda: session.query("get", "https://api.alegra.com/api/v1/contacts"))

    def test_documented_filter_silences_every_legacy_warning(self):
        client = self.session_module._default_client
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warnings.filterwarnings(
                "ignore",
                message=r".*The global (session|default client) will be removed",
                category=FutureWarning,
            )
            session.user = "u"
            session.token = "t"
            session.timeout = 10
            session.create_auth()
            from alegrapy.session import default_client  # noqa: F401
            with patch.object(client.session, "request", return_value=_mock_response([])):
                contacts().list()
                session.query("get", "https://api.alegra.com/api/v1/contacts")


if __name__ == "__main__":
    unittest.main()
