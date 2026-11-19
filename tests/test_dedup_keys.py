import re
import unittest
from datetime import date, datetime
from decimal import Decimal

from alegrapy import AlegraClient, make_dedup_key, make_dedup_key_from

KEY_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class TestMakeDedupKey(unittest.TestCase):

    def test_readable_form_joins_parts(self):
        self.assertEqual(make_dedup_key("mercadopago", 123456789), "mercadopago:123456789")
        self.assertEqual(make_dedup_key(" a "), "a")

    def test_int_and_decimal_parts_are_compared_by_value(self):
        self.assertEqual(make_dedup_key(1), make_dedup_key(Decimal("1")))
        self.assertEqual(make_dedup_key(Decimal("21008.40")), "21008.4")

    def test_namespace_is_prepended(self):
        self.assertEqual(make_dedup_key("123", namespace="provider"), "provider:123")

    def test_long_or_non_matching_parts_are_hashed(self):
        key = make_dedup_key("x" * 70)
        self.assertTrue(key.startswith("h:"))
        self.assertEqual(len(key), 42)

        other = make_dedup_key("x" * 69 + "y")
        self.assertNotEqual(key, other)

    def test_colon_prevents_part_boundary_collisions(self):
        first = make_dedup_key("a:b", "c")
        second = make_dedup_key("a", "b:c")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("h:"))
        self.assertTrue(second.startswith("h:"))

    def test_deterministic(self):
        self.assertEqual(make_dedup_key("order", 42), make_dedup_key("order", 42))

    def test_invalid_parts_raise(self):
        for part in ("", "   ", True, 1.5, None, ["a"]):
            with self.subTest(part=part):
                with self.assertRaises(ValueError):
                    make_dedup_key(part)
        with self.assertRaises(ValueError):
            make_dedup_key()

    def test_output_is_always_valid_for_create_once(self):
        keys = [
            make_dedup_key("provider", 123),
            make_dedup_key("x" * 70),
            make_dedup_key("a:b", "c"),
            make_dedup_key(Decimal("21008.40"), namespace="ns"),
        ]
        for key in keys:
            with self.subTest(key=key):
                self.assertRegex(key, KEY_PATTERN)


class TestReadableKeysNeverLookHashed(unittest.TestCase):

    def test_parts_shaped_like_a_hash_are_hashed(self):
        hex40 = "a" * 40
        key = make_dedup_key("h", hex40)
        self.assertNotEqual(key, f"h:{hex40}")
        self.assertTrue(key.startswith("h:"))
        self.assertNotEqual(make_dedup_key("ns", "h", hex40), f"ns:h:{hex40}")


class TestMakeDedupKeyFrom(unittest.TestCase):

    PAYLOAD = {
        "client": {"id": 126, "name": "ACME"},
        "date": "2026-11-19",
        "items": [
            {"id": 11, "price": Decimal("21008.4"), "quantity": 2},
            {"id": 7, "price": 10, "quantity": 1},
        ],
        "observations": "nota",
    }

    def test_item_order_does_not_matter(self):
        fields = ["client.id", "items[].id", "items[].quantity"]
        reordered = dict(self.PAYLOAD, items=list(reversed(self.PAYLOAD["items"])))

        self.assertEqual(make_dedup_key_from(self.PAYLOAD, fields),
                         make_dedup_key_from(reordered, fields))

    def test_projected_fields_keep_their_pairing_within_each_item(self):
        fields = ["client.id", "items[].id", "items[].quantity"]
        first = {"client": {"id": 126}, "items": [{"id": 1, "quantity": 2}, {"id": 2, "quantity": 1}]}
        second = {"client": {"id": 126}, "items": [{"id": 1, "quantity": 1}, {"id": 2, "quantity": 2}]}

        self.assertNotEqual(make_dedup_key_from(first, fields), make_dedup_key_from(second, fields))

    def test_nested_projection_inside_a_projected_item(self):
        fields = ["items[].id", "items[].tax[].id"]
        first = {"items": [{"id": 1, "tax": [{"id": 3}, {"id": 4}]}, {"id": 2, "tax": []}]}
        swapped_taxes = {"items": [{"id": 1, "tax": []}, {"id": 2, "tax": [{"id": 4}, {"id": 3}]}]}
        reordered = {"items": [{"id": 2, "tax": []}, {"id": 1, "tax": [{"id": 4}, {"id": 3}]}]}

        self.assertNotEqual(make_dedup_key_from(first, fields),
                            make_dedup_key_from(swapped_taxes, fields))
        self.assertEqual(make_dedup_key_from(first, fields), make_dedup_key_from(reordered, fields))

    def test_numbers_never_collide_with_numeric_strings(self):
        for number, text in ((1, "1"), (21008.4, "21008.4"), (float("nan"), "nan")):
            with self.subTest(number=number):
                self.assertNotEqual(make_dedup_key_from({"v": number}, ["v"]),
                                    make_dedup_key_from({"v": text}, ["v"]))

    def test_long_numbers_are_not_rounded_together(self):
        first = 10 ** 30 + 1
        second = 10 ** 30 + 2
        self.assertNotEqual(make_dedup_key_from({"v": first}, ["v"]),
                            make_dedup_key_from({"v": second}, ["v"]))
        self.assertNotEqual(make_dedup_key("order", first), make_dedup_key("order", second))

    def test_malformed_projection_path_is_rejected(self):
        payload = {"items": [{"id": 1}]}
        for path in ("items[]id", "items[]x.id"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    make_dedup_key_from(payload, [path])

    def test_numbers_compared_by_value_but_strings_stay_strings(self):
        number_payload = dict(self.PAYLOAD, items=[{"price": 21008.4}])
        decimal_payload = dict(self.PAYLOAD, items=[{"price": Decimal("21008.40")}])
        string_payload = dict(self.PAYLOAD, items=[{"price": "21008.40"}])

        fields = ["items[].price"]
        self.assertEqual(make_dedup_key_from(number_payload, fields),
                         make_dedup_key_from(decimal_payload, fields))
        self.assertNotEqual(make_dedup_key_from(number_payload, fields),
                            make_dedup_key_from(string_payload, fields))

    def test_bool_is_not_a_number(self):
        true_key = make_dedup_key_from({"flag": True}, ["flag"])
        one_key = make_dedup_key_from({"flag": 1}, ["flag"])

        self.assertNotEqual(true_key, one_key)

    def test_zero_and_negative_zero_match(self):
        self.assertEqual(make_dedup_key_from({"value": 0}, ["value"]),
                         make_dedup_key_from({"value": -0.0}, ["value"]))

    def test_strings_are_stripped(self):
        self.assertEqual(make_dedup_key_from({"ref": " ABC "}, ["ref"]),
                         make_dedup_key_from({"ref": "ABC"}, ["ref"]))

    def test_selected_fields_change_the_key_unselected_do_not(self):
        fields = ["client.id", "items[].id"]
        changed_selected = dict(self.PAYLOAD, client={"id": 127, "name": "ACME"})
        changed_unselected = dict(self.PAYLOAD, date="2027-01-01")

        base = make_dedup_key_from(self.PAYLOAD, fields)
        self.assertNotEqual(base, make_dedup_key_from(changed_selected, fields))
        self.assertEqual(base, make_dedup_key_from(changed_unselected, fields))

    def test_different_field_selections_do_not_collide(self):
        self.assertNotEqual(make_dedup_key_from(self.PAYLOAD, ["client.id"]),
                            make_dedup_key_from(self.PAYLOAD, ["client.id", "date"]))

    def test_missing_paths_raise_with_the_path_name(self):
        for fields in (["client.nope"], ["items[].missing"], ["items.id"], ["client.id.x"]):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError) as ctx:
                    make_dedup_key_from(self.PAYLOAD, fields)
                self.assertIn(fields[0], str(ctx.exception))

    def test_invalid_fields_raise(self):
        for fields in ([], ["client.id", "client.id"], "client.id", [""], [123]):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    make_dedup_key_from(self.PAYLOAD, fields)

    def test_namespace_prefixes_and_separates(self):
        key = make_dedup_key_from(self.PAYLOAD, ["client.id"], namespace="billing")
        other = make_dedup_key_from(self.PAYLOAD, ["client.id"], namespace="other")

        self.assertTrue(key.startswith("billing:h:"))
        self.assertNotEqual(key, other)
        self.assertRegex(key, KEY_PATTERN)

    def test_invalid_namespace_raises(self):
        for namespace in ("", "bad name", "x" * 21):
            with self.subTest(namespace=namespace):
                with self.assertRaises(ValueError):
                    make_dedup_key_from(self.PAYLOAD, ["client.id"], namespace=namespace)

    def test_dates_and_none_are_canonical(self):
        first = {"day": date(2026, 11, 19), "at": datetime(2026, 11, 19, 10, 30), "note": None}
        second = {"day": "2026-11-19", "at": "2026-11-19T10:30:00", "note": None}

        self.assertEqual(make_dedup_key_from(first, ["day", "at", "note"]),
                         make_dedup_key_from(second, ["day", "at", "note"]))
        self.assertNotEqual(make_dedup_key_from(first, ["day"]),
                            make_dedup_key_from(first, ["at"]))

    def test_round_trip_with_create_once_precheck(self):
        key = make_dedup_key_from(self.PAYLOAD, ["client.id", "date"])
        invoice = {"id": 77, "observations": f"alegrapy:dedup:{key}"}
        calls = []

        def query(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method.lower() == 'post':
                return invoice
            return [invoice]

        client = AlegraClient(user="user", token="token")
        client.query = query

        created = client.invoices.create_once(self.PAYLOAD, key, precheck=False)
        found = client.invoices.create_once(self.PAYLOAD, key)

        self.assertIs(created, invoice)
        self.assertIs(found, invoice)
        self.assertEqual(len([call for call in calls if call[0].lower() == 'post']), 1)


if __name__ == '__main__':
    unittest.main()
