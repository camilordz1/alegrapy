import importlib
import importlib.metadata
import os
import subprocess
import sys
import unittest
import warnings

import alegrapy


class TestCompatShim(unittest.TestCase):

    def test_alegrapy_exposes_the_public_api(self):
        for name in ("AlegraClient", "AlegraAPIError", "RetryPolicy", "CreditNotes",
                     "make_dedup_key"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(alegrapy, name))
                self.assertIn(name, alegrapy.__all__)
        self.assertIsInstance(alegrapy.__version__, str)

    def test_version_has_a_single_source(self):
        source = importlib.import_module("alegrapy._version").__version__
        self.assertEqual(alegrapy.__version__, source)
        try:
            installed = importlib.metadata.version("AlegraPy")
        except importlib.metadata.PackageNotFoundError:
            return
        # A stale installed distribution would shadow the checkout's version
        self.assertEqual(installed, source)

    def test_import_alegra_reexports_identity(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import alegra

        self.assertIs(alegra.AlegraClient, alegrapy.AlegraClient)
        self.assertEqual(alegra.__all__, alegrapy.__all__)

    def test_submodules_are_the_same_module_objects(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import alegra
            import alegra.session  # noqa: F401
            import alegra.invoices  # noqa: F401
            from alegra.session import AlegraAPIError
            from alegra.exceptions import AlegraNotFoundError

        self.assertIs(alegra.session, alegrapy.session)
        self.assertIs(alegra.invoices, alegrapy.invoices)
        self.assertIs(AlegraAPIError,
                      sys.modules["alegrapy.session"].AlegraAPIError)
        self.assertIs(AlegraNotFoundError,
                      sys.modules["alegrapy.exceptions"].AlegraNotFoundError)
        self.assertIs(sys.modules["alegra.session"], sys.modules["alegrapy.session"])
        self.assertIs(sys.modules["alegra.invoices"], sys.modules["alegrapy.invoices"])
        self.assertIs(sys.modules["alegra.exceptions"], sys.modules["alegrapy.exceptions"])

    def test_submodules_outside_all_are_package_attributes(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import alegra
            import alegra.exceptions  # noqa: F401

        for name in ("exceptions", "retry", "dedup"):
            with self.subTest(name=name):
                self.assertNotIn(name, alegrapy.__all__)
                self.assertIs(getattr(alegra, name), sys.modules[f"alegrapy.{name}"])
        self.assertIs(alegra.exceptions.AlegraNotFoundError, alegrapy.AlegraNotFoundError)

    def test_legacy_names_still_work(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from alegra import session, invoices, contacts

        self.assertIs(session, alegrapy.session)
        self.assertIs(invoices, alegrapy.invoices)
        self.assertIs(contacts, alegrapy.contacts)

    def test_fresh_interpreter_warns_once(self):
        code = "import alegra"
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        strict = subprocess.run(
            [sys.executable, "-W", "error::DeprecationWarning", "-c", code],
            cwd=root, capture_output=True, text=True)
        self.assertNotEqual(strict.returncode, 0)
        self.assertIn("The 'alegra' import name is deprecated", strict.stderr)

        default = subprocess.run(
            [sys.executable, "-W", "default", "-c", code],
            cwd=root, capture_output=True, text=True)
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stderr.count("The 'alegra' import name is deprecated"), 1)


if __name__ == '__main__':
    unittest.main()
