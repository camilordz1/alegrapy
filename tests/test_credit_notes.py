import copy
import importlib
import json
import unittest
from datetime import date
from unittest.mock import patch

import alegrapy
from alegrapy import AlegraClient

# Patch module objects directly: `alegra.<resource>` names are shadowed by legacy aliases.
_FLOW_TIME = importlib.import_module('alegrapy._create_once').time
_INVOICES_MODULE = importlib.import_module('alegrapy.invoices')

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
# A completed annulment: the note was stamped and accepted by the tax authority
STAMPED = {"legalStatus": "STAMPED_AND_ACCEPTED"}


class TestCreditNotes(unittest.TestCase):

    def setUp(self):
        self.client = AlegraClient(user="user", token="token")
        self.calls = []
        self.invoice = copy.deepcopy(INVOICE)
        self.invoice_states = []
        self.note_pages = []
        self.posts = []

        def query(method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method.lower() == 'get' and '/invoices/' in url:
                if self.invoice_states:
                    state = self.invoice_states.pop(0)
                    if isinstance(state, Exception):
                        raise state
                    return copy.deepcopy(state)
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
        self.assertIsInstance(self.client.credit_notes, alegrapy.CreditNotes)
        self.assertEqual(self.client.credit_notes.endpoint, "credit-notes")
        self.assertIs(alegrapy.credit_notes, alegrapy.CreditNotes)
        self.assertEqual(alegrapy.credit_notes().endpoint, "credit-notes")
        self.assertIn("CreditNotes", alegrapy.__all__)
        self.assertIn("credit_notes", alegrapy.__all__)

    def test_catalog_constants_match_the_api(self):
        self.assertEqual(alegrapy.CreditNoteType.PARTIALL_DEVOLUTION.value, "PARTIALL_DEVOLUTION")
        self.assertEqual(alegrapy.CreditNoteType.VOID_ELECTRONIC_INVOICE.value,
                         "VOID_ELECTRONIC_INVOICE")
        self.assertEqual(alegrapy.CreditNoteType.REDUCTION_DISCOUNT_PARTIAL_TOTAL.value,
                         "REDUCTION_DISCOUNT_PARTIAL_TOTAL")
        self.assertEqual(alegrapy.CreditNoteType.PRICE_ADJUSTMENT.value, "PRICE_ADJUSTMENT")
        self.assertEqual(alegrapy.CreditNoteType.OTHER.value, "OTHER")
        self.assertEqual(
            alegrapy.CreditNoteOperationType.REFERENCE_TO_ELECTRONIC_INVOICE.value,
            "REFERENCE_TO_ELECTRONIC_INVOICE")
        self.assertEqual(
            alegrapy.CreditNoteOperationType.NO_REFERENCE_TO_ELECTRONIC_INVOICE.value,
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
        for operation in (alegrapy.CreditNoteOperationType.NO_REFERENCE_TO_ELECTRONIC_INVOICE,
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
        existing = {"id": 901, "observations": MARKER, "stamp": STAMPED}
        self.note_pages = [[existing]]

        result = self.client.invoices.annul(11742, "motivo")

        self.assertIs(result, existing)
        self.assertEqual(self._post_calls(), [])

    def test_annul_verifies_ambiguous_post(self):
        existing = {"id": 902, "observations": MARKER, "stamp": STAMPED}
        self.note_pages = [[], [existing]]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                result = self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertIs(result, existing)
        self.assertEqual(len(self._post_calls()), 1)
        self.assertGreaterEqual(len(self._note_gets()), 2)

    def test_existing_unstamped_annulment_note_is_reported_not_returned(self):
        unstamped = {"id": 950, "observations": MARKER, "client": {"id": 126},
                     "stamp": {"legalStatus": None}}
        self.note_pages = [[unstamped]]

        with self.assertRaises(alegrapy.AlegraStampError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertEqual(ctx.exception.document["id"], 950)
        self.assertEqual(self._post_calls(), [])

    def test_existing_unstamped_note_is_fine_when_stamping_was_not_requested(self):
        unstamped = {"id": 951, "observations": MARKER, "client": {"id": 126}}
        self.note_pages = [[unstamped]]

        result = self.client.invoices.annul(11742, "motivo", stamp=False)

        self.assertEqual(result["id"], 951)

    def test_already_annulled_after_ambiguous_post_is_quarantined(self):
        annulled = dict(self.invoice, status="closed", balance=0, totalPaid=0)
        # initial read, guard before POST 1, guard before POST 2 (now annulled)
        self.invoice_states = [self.invoice, self.invoice, annulled]
        self.note_pages = [[], [], []]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertIsInstance(ctx.exception.__cause__, alegrapy.AlegraAlreadyAnnulledError)
        self.assertEqual(ctx.exception.dedup_key, "annul:11742")
        self.assertEqual(len(self._post_calls()), 1)

    def test_retry_guard_failure_after_ambiguous_post_is_quarantined(self):
        paid = dict(self.invoice, status="closed", balance=0, totalPaid=21008.4)
        for label, third_read in (("read fails", alegrapy.AlegraTimeoutError("slow")),
                                  ("status changed", paid)):
            with self.subTest(guard=label):
                self.calls = []
                # initial read, guard before POST 1, guard before POST 2
                self.invoice_states = [self.invoice, self.invoice, third_read]
                self.note_pages = [[], []]
                self.posts = [alegrapy.AlegraServerError("boom", status_code=503)]

                with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
                    with patch.object(_FLOW_TIME, 'sleep'):
                        with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                            self.client.invoices.annul(11742, "motivo", verify_window=0)

                self.assertEqual(ctx.exception.attempts, 1)
                self.assertEqual(ctx.exception.resource, "credit-notes")
                self.assertIsNotNone(ctx.exception.__cause__)
                self.assertEqual(len(self._post_calls()), 1)

    def test_annul_unverified_raises_with_credit_note_resource(self):
        self.note_pages = [[], [], []]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503),
                      alegrapy.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertEqual(ctx.exception.resource, "credit-notes")
        self.assertEqual(ctx.exception.attempts, 2)
        self.assertEqual(ctx.exception.dedup_key, "annul:11742")
        self.assertEqual(len(self._post_calls()), 2)

    def test_stamp_failure_400_with_created_note_raises_stamp_error(self):
        created = {
            "id": 903, "status": "open", "total": 21008.4,
            "creditNoteOperationType": "REFERENCE_TO_ELECTRONIC_INVOICE",
            "invoices": [{"id": 11742, "amount": 21008.4}],
        }
        body = json.dumps({"message": "stamp failed", "creditNote": created})
        error = alegrapy.AlegraValidationError("stamp failed", status_code=400,
                                             response_body=body)
        self.note_pages = [[]]
        self.posts = [error]

        with self.assertRaises(alegrapy.AlegraStampError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertEqual(ctx.exception.document, created)
        self.assertIs(ctx.exception.__cause__, error)
        self.assertEqual(len(self._post_calls()), 1)
        self.assertEqual(len(self._note_gets()), 1)

    def test_plain_400_is_raised_unchanged(self):
        error = alegrapy.AlegraValidationError(
            "invalid", status_code=400, response_body='{"message": "invalid"}')
        self.note_pages = [[]]
        self.posts = [error]

        with self.assertRaises(alegrapy.AlegraValidationError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertIs(ctx.exception, error)
        self.assertEqual(len(self._post_calls()), 1)

    def test_invoice_echo_400_is_not_misread_as_stamp_error(self):
        body = json.dumps({"message": "bad",
                           "invoice": {"id": 11742, "status": "open", "total": 1}})
        error = alegrapy.AlegraValidationError("bad", status_code=400, response_body=body)
        self.note_pages = [[]]
        self.posts = [error]

        with self.assertRaises(alegrapy.AlegraValidationError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertIs(ctx.exception, error)

    def test_note_for_another_invoice_is_not_a_stamp_error(self):
        other = {"id": 904, "creditNoteOperationType": "REFERENCE_TO_ELECTRONIC_INVOICE",
                 "invoices": [{"id": 999, "amount": 1}]}
        body = json.dumps({"message": "bad", "creditNote": other})
        error = alegrapy.AlegraValidationError("bad", status_code=400, response_body=body)
        self.note_pages = [[]]
        self.posts = [error]

        with self.assertRaises(alegrapy.AlegraValidationError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertIs(ctx.exception, error)

    def _closed_invoice(self):
        invoice = copy.deepcopy(INVOICE)
        invoice.update({"status": "closed", "balance": 0, "totalPaid": 0.0})
        return invoice

    def test_annul_returns_note_when_invoice_is_already_annulled(self):
        self.invoice = self._closed_invoice()
        existing = {"id": 950, "observations": MARKER, "client": {"id": 126}, "stamp": STAMPED}
        self.note_pages = [[existing]]

        result = self.client.invoices.annul(11742, "motivo")

        self.assertIs(result, existing)
        self.assertEqual(self._post_calls(), [])

    def test_annul_already_annulled_without_note_raises(self):
        self.invoice = self._closed_invoice()
        self.note_pages = [[]]

        with self.assertRaises(alegrapy.AlegraAlreadyAnnulledError) as ctx:
            self.client.invoices.annul(11742, "motivo")

        self.assertEqual(ctx.exception.invoice_id, 11742)
        self.assertEqual(self._post_calls(), [])

    def test_annul_does_not_post_again_when_invoice_became_closed(self):
        existing = {"id": 951, "observations": MARKER, "client": {"id": 126}, "stamp": STAMPED}
        self.invoice_states = [copy.deepcopy(INVOICE), copy.deepcopy(INVOICE),
                               self._closed_invoice()]
        self.note_pages = [[], [], [existing]]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                result = self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertIs(result, existing)
        self.assertEqual(len(self._post_calls()), 1)

    def test_annul_became_closed_without_note_does_not_post_again(self):
        self.invoice_states = [copy.deepcopy(INVOICE), copy.deepcopy(INVOICE),
                               self._closed_invoice()]
        self.note_pages = [[], [], []]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                # Our own ambiguous first POST most likely annulled it: quarantine
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertIsInstance(ctx.exception.__cause__, alegrapy.AlegraAlreadyAnnulledError)
        self.assertEqual(len(self._post_calls()), 1)

    def test_annul_rejects_paid_closed_invoice(self):
        self.invoice = self._closed_invoice()
        self.invoice.update({"balance": 100, "totalPaid": 100})
        self.note_pages = []
        self.posts = []

        with self.assertRaises(ValueError):
            self.client.invoices.annul(11742, "motivo")

        self.assertEqual(self._post_calls(), [])
        self.assertEqual(self._note_gets(), [])

    def test_stamp_error_on_second_post_is_raised_unchanged(self):
        created = {"id": 905, "creditNoteOperationType": "REFERENCE_TO_ELECTRONIC_INVOICE",
                   "invoices": [{"id": 11742, "amount": 1}]}
        stamp_error = alegrapy.AlegraStampError("stamp failed", document=created,
                                              status_code=400)
        self.invoice_states = [copy.deepcopy(INVOICE), copy.deepcopy(INVOICE)]
        self.note_pages = [[], []]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503), stamp_error]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                with self.assertRaises(alegrapy.AlegraStampError) as ctx:
                    self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertIs(ctx.exception, stamp_error)
        self.assertEqual(len(self._post_calls()), 2)

    def test_reconcile_client_isolation(self):
        other = {"id": 1, "observations": MARKER, "client": {"id": 999}}
        no_client = {"id": 2, "observations": MARKER}

        self.note_pages = [[other, no_client]]
        self.assertIs(self.client.credit_notes.reconcile("annul:11742", 126), no_client)

        self.note_pages = [[other]]
        self.assertIsNone(self.client.credit_notes.reconcile("annul:11742", 126))

    def test_reconcile_honors_lookup_pages(self):
        full_page = [{"id": index, "observations": None} for index in range(30)]
        found = {"id": 31, "observations": MARKER}

        self.note_pages = [full_page]
        self.assertIsNone(self.client.credit_notes.reconcile("annul:11742", 126,
                                                             lookup_pages=1))
        self.assertEqual(len(self._note_gets()), 1)

        self.calls = []
        self.note_pages = [full_page, [found]]
        self.assertIs(self.client.credit_notes.reconcile("annul:11742", 126,
                                                         lookup_pages=2), found)
        self.assertEqual(len(self._note_gets()), 2)

    def test_annul_forwards_lookup_pages(self):
        self.note_pages = [[]]
        self.posts = [{"id": 906}]

        with patch.object(alegrapy.CreditNotes, 'reconcile', return_value=None) as reconcile:
            self.client.invoices.annul(11742, "motivo", lookup_pages=4)

        reconcile.assert_any_call("annul:11742", 126, lookup_pages=4)

    def test_annul_stamp_false_and_number_template(self):
        self.note_pages = [[]]
        self.posts = [{"id": 907}]

        self.client.invoices.annul(11742, "motivo", stamp=False, number_template_id=33)

        payload = self._post_calls()[0][2]['data']
        self.assertNotIn('stamp', payload)
        self.assertEqual(payload['numberTemplate'], {"id": 33})

    def test_annul_custom_dedup_key(self):
        self.note_pages = [[]]
        self.posts = [{"id": 908}]

        self.client.invoices.annul(11742, "motivo", dedup_key="custom-key")

        payload = self._post_calls()[0][2]['data']
        self.assertIn("alegrapy:dedup:custom-key", payload['observations'].splitlines())

    def test_annul_on_unverified_raise_makes_one_post(self):
        self.note_pages = [[], []]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503)]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.annul(11742, "motivo", verify_window=0,
                                               on_unverified="raise")

        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(len(self._post_calls()), 1)

    def test_annul_second_post_rejected_is_quarantined(self):
        rejection = alegrapy.AlegraValidationError(
            "invalid", status_code=400, response_body='{"message": "invalid"}')
        self.note_pages = [[], []]
        self.posts = [alegrapy.AlegraServerError("boom", status_code=503), rejection]

        with patch.object(_FLOW_TIME, 'monotonic', return_value=0.0):
            with patch.object(_FLOW_TIME, 'sleep'):
                with self.assertRaises(alegrapy.AlegraUnverifiedCreateError) as ctx:
                    self.client.invoices.annul(11742, "motivo", verify_window=0)

        self.assertEqual(ctx.exception.attempts, 2)
        self.assertIs(ctx.exception.__cause__, rejection)

    def test_annul_uses_the_patched_date_source(self):
        class _FixedDate:
            @staticmethod
            def today():
                return date(2026, 1, 2)

        self.note_pages = [[]]
        self.posts = [{"id": 909}]

        with patch.object(_INVOICES_MODULE, 'date', _FixedDate):
            self.client.invoices.annul(11742, "motivo")

        payload = self._post_calls()[0][2]['data']
        self.assertEqual(payload['date'], "2026-01-02")

    def test_annul_accepts_an_explicit_date(self):
        for given, expected in ((date(2026, 11, 19), "2026-11-19"), (" 2026-11-19 ", "2026-11-19")):
            with self.subTest(given=given):
                self.calls = []
                self.note_pages = [[]]
                self.posts = [{"id": 910}]

                self.client.invoices.annul(11742, "motivo", date=given)

                self.assertEqual(self._post_calls()[0][2]['data']['date'], expected)

    def test_annul_rejects_invalid_dates_before_any_request(self):
        for bad in ("19/11/2026", "2026-13-01", "", 20261119, True):
            with self.subTest(bad=bad):
                self.calls = []
                with self.assertRaises(ValueError):
                    self.client.invoices.annul(11742, "motivo", date=bad)
                self.assertEqual(self.calls, [])

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
