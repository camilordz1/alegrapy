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


class TestWarnOnceRegistry(unittest.TestCase):
    """A warning only counts as delivered once warnings.warn returned normally."""

    def setUp(self):
        from alegrapy._deprecation import reset_legacy_warnings

        self.saved = {name: getattr(session, name) for name in ("user", "url")}
        reset_legacy_warnings()
        self.addCleanup(self._restore)

    def _restore(self):
        from alegrapy._deprecation import reset_legacy_warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            for name, value in self.saved.items():
                setattr(session, name, value)
        reset_legacy_warnings()

    def test_error_filter_raises_on_every_attempt(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            for _ in range(2):
                with self.assertRaises(FutureWarning):
                    session.user = "u"

    def test_warning_raised_as_error_is_emitted_again_later(self):
        from alegrapy._deprecation import warn_legacy

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            with self.assertRaises(FutureWarning):
                warn_legacy("test.feature", "test message")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warn_legacy("test.feature", "test message")
            warn_legacy("test.feature", "test message")
        self.assertEqual(len(caught), 1)

    def test_ignored_warning_counts_as_delivered(self):
        from alegrapy._deprecation import warn_legacy

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            warn_legacy("test.ignored", "test message")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warn_legacy("test.ignored", "test message")
        self.assertEqual(caught, [])

    def test_reentrant_use_from_showwarning_hook_warns_once(self):
        from alegrapy._deprecation import warn_legacy

        delivered = []

        def hook(message, category, filename, lineno, file=None, line=None):
            delivered.append(str(message))
            warn_legacy("test.reentrant", "test message")

        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.showwarning = hook
            warn_legacy("test.reentrant", "test message")
            warn_legacy("test.reentrant", "test message")
        self.assertEqual(delivered, ["test message"])

    def _url_warnings(self, url):
        client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            session.url = url
        from alegrapy._deprecation import reset_legacy_warnings
        reset_legacy_warnings()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with patch.object(client.session, "request", return_value=_mock_response([])) as req:
                client.contacts.list()
        return [str(w.message) for w in caught if "session.url" in str(w.message)], req

    def test_default_url_without_trailing_slash_does_not_warn(self):
        msgs, req = self._url_warnings("https://api.alegra.com/api/v1")
        self.assertEqual(msgs, [])
        self.assertTrue(req.call_args.kwargs["url"].startswith("https://api.alegra.com/api/v1/contacts"))

    def test_non_default_global_url_warns(self):
        msgs, req = self._url_warnings("https://sandbox.example.com/api/v1/")
        self.assertEqual(len(msgs), 1)
        self.assertTrue(req.call_args.kwargs["url"].startswith("https://sandbox.example.com/api/v1/contacts"))


class TestUndocumentedEndpointsNotDeprecated(unittest.TestCase):

    def setUp(self):
        from alegrapy._deprecation import reset_legacy_warnings

        reset_legacy_warnings()
        self.addCleanup(reset_legacy_warnings)
        self.client = AlegraClient(user="u", token="t", retry=RetryPolicy(max_retries=0))

    def test_undocumented_methods_emit_no_warning_and_preserve_requests(self):
        cases = [
            (
                "estimates.void",
                lambda: self.client.estimates.void(5),
                "post",
                "https://api.alegra.com/api/v1/estimates/5/void",
                None,
            ),
            (
                "estimates.open",
                lambda: self.client.estimates.open(5),
                "post",
                "https://api.alegra.com/api/v1/estimates/5/open",
                None,
            ),
            (
                "purchase_orders.send_email",
                lambda: self.client.purchase_orders.send_email(
                    7, ["a@example.com"], send_copy_to_user=True, subject="S", message="M"
                ),
                "post",
                "https://api.alegra.com/api/v1/purchase-orders/7/email",
                {
                    "emails": ["a@example.com"],
                    "sendCopyToUser": True,
                    "emailTemplate": {"subject": "S", "message": "M"},
                },
            ),
            (
                "purchase_orders.add_comment",
                lambda: self.client.purchase_orders.add_comment(7, "nota"),
                "post",
                "https://api.alegra.com/api/v1/purchase-orders/7/comments",
                {"comments": "nota"},
            ),
        ]
        for label, call_fn, expected_method, expected_url, expected_body in cases:
            with self.subTest(method=label):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    with patch.object(
                        self.client.session, "request", return_value=_mock_response({"ok": True})
                    ) as mock_req:
                        res1 = call_fn()
                        res2 = call_fn()
                self.assertEqual(res1, {"ok": True})
                self.assertEqual(res2, {"ok": True})
                self.assertEqual(mock_req.call_count, 2)
                for req_call in mock_req.call_args_list:
                    self.assertEqual(req_call.kwargs["method"].lower(), expected_method)
                    self.assertEqual(req_call.kwargs["url"], expected_url)
                    if expected_body is not None:
                        self.assertEqual(req_call.kwargs["json"], expected_body)
                    else:
                        self.assertIsNone(req_call.kwargs.get("json"))

                future = [w for w in caught if issubclass(w.category, FutureWarning)]
                self.assertEqual(future, [])

    def test_invalid_ids_still_raise_value_error_without_request(self):
        calls = [
            lambda: self.client.estimates.void("../bad"),
            lambda: self.client.estimates.open("../bad"),
            lambda: self.client.purchase_orders.send_email("../bad", "a@example.com"),
            lambda: self.client.purchase_orders.add_comment("../bad", "nota"),
        ]
        for call_fn in calls:
            with patch.object(self.client.session, "request") as mock_req:
                with self.assertRaises(ValueError):
                    call_fn()
                mock_req.assert_not_called()

    def test_documented_sibling_methods_emit_zero_warnings(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            with patch.object(
                self.client.session, "request", return_value=_mock_response({"ok": True})
            ) as mock_req:
                self.client.estimates.send_email(5, "a@example.com")
                self.client.purchase_orders.void(7)
        self.assertEqual(mock_req.call_count, 2)

    def test_probe_script_refuses_without_confirmation_flag(self):
        import pathlib

        script_path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "probe_undocumented_routes.py"
        spec = importlib.util.spec_from_file_location("probe_undocumented_routes", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with patch("requests.request") as mock_req, patch("requests.Session.request") as mock_sess:
            with self.assertRaises(SystemExit) as ctx:
                module.main([])
            self.assertNotEqual(ctx.exception.code, 0)
            mock_req.assert_not_called()
            mock_sess.assert_not_called()

    def test_probe_classify_and_excerpt(self):
        import pathlib
        from types import SimpleNamespace

        script_path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "probe_undocumented_routes.py"
        spec = importlib.util.spec_from_file_location("probe_undocumented_routes", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def fake_resp(status_code, text):
            return SimpleNamespace(status_code=status_code, text=text)

        self.assertEqual(
            module._classify(
                fake_resp(404, '{"code": 404, "message": "Not found"}'),
                fake_resp(404, '{"code": 404, "message": "Not found"}'),
            ),
            "route exists",
        )
        self.assertEqual(
            module._classify(
                fake_resp(404, '{"code": 404, "message": "Documento no encontrado"}'),
                fake_resp(404, '{"code": 404, "message": "Cotización no encontrada"}'),
            ),
            "inconclusive",
        )
        self.assertEqual(
            module._classify(
                fake_resp(405, '{"message": "Method Not Allowed"}'),
                fake_resp(404, '{"message": "Not found"}'),
            ),
            "route missing",
        )
        self.assertEqual(
            module._classify(
                fake_resp(404, "<html>Cannot POST /estimates/999999999/void</html>"),
                fake_resp(404, '{"message": "Not found"}'),
            ),
            "route missing",
        )

        long_text = "  hola \n\t mundo   " + ("x" * 200)
        excerpt = module._excerpt(long_text)
        self.assertLessEqual(len(excerpt), 120)
        self.assertNotIn("\n", excerpt)
        self.assertNotIn("\t", excerpt)
        self.assertTrue(excerpt.startswith("hola mundo "))



if __name__ == "__main__":
    unittest.main()
