import copy
import importlib
import json
import unittest
from datetime import date
from unittest.mock import patch

import alegra
from alegra import AlegraClient

# The shared create-once flow owns the clock; patch the module object directly because
# `alegra.<resource>` names are shadowed by the legacy class aliases.
_FLOW_TIME = importlib.import_module('alegra._create_once').time

INVOICE = {
    "id": 11742,
    "status": "open",
    "total": 21008.4,
    "client": {"id": 126, "name": "ACME"},
    "warehouse": {"id": 3, "name": "Principal"},
    "costCenter": {"id": 7},
    "stamp": {"legalStatus": "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS"},
    "items": [
        {"id": 11, "price": 10000.2, "quantity": 2,
         "tax": [{"id": 1, "percentage": 19}], "reference": "A", "description": "Item A"},
        {"id": 12, "price": 1008, "quantity": 1, "tax": [{"id": 2}], "reference": "B"},
    ],
}

MARKER = "alegrapy:dedup:annul:11742"


class TestCreditNotes(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="user", token="token")
        self.calls = []
        self.invoice = copy.deepcopy(INVOICE)
        self.note_pages = []
        self.posts = []

        def query(method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method.lower() == 'get' and '/invoices/' in url:
                return copy.deepcopy(self.invoice)
            if method.lower() == 'get' and '/credit-notes' in url:
                return self.note_pages.pop(0) if self.note_pages else []
            if method.lower() == 'post' and '/credit-notes' in url:
                item = self.posts.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            if method.lower() == 'post' and '/void' in url:
                item = self.posts.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            raise AssertionError(f"unexpected call {method} {url}")

        self.client.query = query

    def _all_calls(self):
        return self.calls

    def _post_calls(self):
        return [call for call in self.calls if call[0].lower() == 'post']

    def _note_gets(self):
        return [call for call in self.calls
                if call[0].lower() == 'get' and '/credit-notes' in call[1]]

    def test_resource_is_exported_and_reachable(self):
        self.assertIsInstance(self.client.credit_notes, alegra.CreditNotes)
        self.assertEqual(self.client.credit_notes.endpoint, "credit-notes")
        self.assertIs(alegra.credit_notes, alegra.CreditNotes)
        self.assertEqual(alegra.credit_notes().endpoint, "credit-notes")
        self.assertIn("CreditNotes", alegra.__all__)
        self.assertIn("credit_notes", alegra.__all__)

    def test_catalog_constants_match_the_api(self):
        self.assertEqual(alegra.CreditNoteType.PARTIALL_DEVOLUTION.value, "PARTIALL_DEVOLUTION")
        self.assertEqual(alegra.CreditNoteType.VOID_ELECTRONIC_INVOICE.value,
                         "VOID_ELECTRONIC_INVOICE")
        self.assertEqual(alegra.CreditNoteType.REDUCTION_DISCOUNT_PARTIAL_TOTAL.value,
                         "REDUCTION_DISCOUNT_PARTIAL_TOTAL")
        self.assertEqual(alegra.CreditNoteType.PRICE_ADJUSTMENT.value, "PRICE_ADJUSTMENT")
        self.assertEqual(alegra.CreditNoteType.OTHER.value, "OTHER")
        self.assertEqual(
            alegra.CreditNoteOperationType.REFERENCE_TO_ELECTRONIC_INVOICE.value,
            "REFERENCE_TO_ELECTRONIC_INVOICE")
        self.assertEqual(
            alegra.CreditNoteOperationType.NO_REFERENCE_TO_ELECTRONIC_INVOICE.value,
            "NO_REFERENCE_TO_ELECTRONIC_INVOICE")

    def test_annul_builds_the_credit_note_payload(self):
        self.note_pages = [[]]
        self.posts = [{"id": 900, "status": "open"}]
        original_invoice = copy.deepcopy(self.invoice)

        result = self.client.invoices.annul(11742, "Anulación solicitada por el cliente")

        self.assertEqual(result, {"id": 900, "status": "open"})
        self.assertEqual(self.invoice, original_invoice)

        payload = self._post_calls()[0][2]['data']
        self.assertEqual(payload['date'], date.today().isoformat())
        self.assertEqual(payload['client'], {"id": 126})
        self.assertEqual(payload['type'], "VOID_ELECTRONIC_INVOICE")
        self.assertEqual(payload['creditNoteOperationType'], "REFERENCE_TO_ELECTRONIC_INVOICE")
        self.assertEqual(payload['cause'], "Anulación solicitada por el cliente")
        self.assertEqual(payload['invoices'], [{"id": 11742, "amount": 21008.4}])
        self.assertEqual(payload['warehouse'], {"id": 3, "name": "Principal"})
        self.assertEqual(payload['costCenter'], {"id": 7})
        self.assertEqual(payload['stamp'], {"generateStamp": True})
        self.assertEqual(
            payload['items'],
            [
                {"id": 11, "price": 10000.2, "quantity": 2, "tax": [1],
                 "reference": "A", "description": "Item A"},
                {"id": 12, "price": 1008, "quantity": 1, "tax": [2], "reference": "B"},
            ],
        )
        self.assertIn(MARKER, payload['observations'].splitlines())

        lookup_params = self._note_gets()[0][2]['params']
        self.assertEqual(lookup_params['order_field'], 'id')
        self.assertEqual(lookup_params['order_direction'], 'DESC')
        self.assertNotIn('status', lookup_params)

    def test_annul_rejects_unusable_invoices_before_posting(self):
        cases = [
            {"status": "draft"},
            {"status": "void"},
            {"stamp": {"legalStatus": "NOT_STAMPED"}},
            {"stamp": None},
        ]
        for change in cases:
            with self.subTest(change=change):
                self.invoice = dict(copy.deepcopy(INVOICE), **change)
                self.calls = []
                with self.assertRaises(ValueError):
                    self.client.invoices.annul(11742, "motivo")
                self.assertEqual(self._post_calls(), [])
                self.assertEqual(self._note_gets(), [])

    def test_annul_rejects_blank_cause_without_reading(self):
        for cause in ("", "   "):
            with self.subTest(cause=cause):
                self.calls = []
                with self.assertRaises(ValueError):
                    self.client.invoices.annul(11742, cause)
                self.assertEqual(self.calls, [])

    def test_operation_type_accepts_enum_and_raw_string(self):
        for operation in (alegra.CreditNoteOperationType.NO_REFERENCE_TO_ELECTRONIC_INVOICE,
                          "NO_REFERENCE_TO_ELECTRONIC_INVOICE"):
            with self.subTest(operation=operation):
                self.calls = []
                self.note_pages = [[]]
                self.posts = [{"id": 900}]
                self.client.invoices.annul(11742, "motivo", operation_type=operation)
                payload = self._post_calls()[0][2]['data']
                self.assertEqual(payload['creditNoteOperationType'],
                                 "NO_REFERENCE_TO_ELECTRONIC_INVOICE")

    def test_annul_returns_existing_note_from_precheck(self):
        existing = {"id": 901, "observations": MARKER}
        self.note_pages = [[existing]]

        result = self.client.invoices.annul(11742, "motivo")

        self.assertIs(result, existing)
        self.assertEqual(self._post_calls(), [])

    def test_annul_verifies_ambiguous_post(self):
        existing = {"id": 902, "observations": MARKER}
        self.note_pages = [[], [existing]]
        self.posts = [alegra.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                result = self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertIs(result, existing)
        self.assertEqual(len(self._post_calls()), 1)
        self.assertGreaterEqual(len(self._note_gets()), 2)

    def test_annul_unverified_raises_with_credit_note_resource(self):
        self.note_pages = [[], [], []]
        self.posts = [alegra.AlegraServerError("boom", status_code=503),
                      alegra.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                with self.assertRaises(alegra.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertEqual(ctx.exception.resource, "credit-notes")
        self.assertEqual(ctx.exception.attempts, 2)
        self.assertEqual(ctx.exception.dedup_key, "annul:11742")
        self.assertEqual(len(self._post_calls()), 2)

    def test_stamp_failure_400_with_created_note_raises_stamp_error(self):
        created = {"id": 903, "status": "open", "total": 21008.4}
        body = json.dumps({"message": "stamp failed", "creditNote": created})
        error = alegra.AlegraValidationError("stamp failed", status_code=400,
                                             response_body=body)
        self.note_pages = [[]]
        self.posts = [error]

        with self.assertRaises(alegra.AlegraStampError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertEqual(ctx.exception.document, created)
        self.assertIs(ctx.exception.__cause__, error)
        self.assertEqual(len(self._post_calls()), 1)
        self.assertEqual(len(self._note_gets()), 1)

    def test_plain_400_is_raised_unchanged(self):
        error = alegra.AlegraValidationError(
            "invalid", status_code=400, response_body='{"message": "invalid"}')
        self.note_pages = [[]]
        self.posts = [error]

        with self.assertRaises(alegra.AlegraValidationError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertIs(ctx.exception, error)
        self.assertEqual(len(self._post_calls()), 1)

    def test_void_sends_cause_only_when_given(self):
        self.posts = [{"status": "void"}]
        self.client.invoices.void(5, cause="motivo")
        post = [call for call in self.calls if call[0].lower() == 'post'][0]
        self.assertTrue(post[1].endswith('/invoices/5/void'))
        self.assertEqual(post[2]['data'], {"cause": "motivo"})

        self.calls = []
        self.posts = [{"status": "void"}]
        self.client.invoices.void(5)
        post = [call for call in self.calls if call[0].lower() == 'post'][0]
        self.assertNotIn('data', post[2])


if __name__ == '__main__':
    unittest.main()
