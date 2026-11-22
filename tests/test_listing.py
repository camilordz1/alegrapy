import datetime as dt
import unittest

from alegrapy._listing import (
    build_list_params,
    validate_choice,
    validate_date_filters,
    validate_pagination,
)


class TestListingHelpers(unittest.TestCase):

    def test_validate_pagination(self):
        self.assertEqual(validate_pagination(0, 30), (0, 30))
        self.assertEqual(validate_pagination(5, 1), (5, 1))
        for start, limit in ((-1, 10), (True, 10), ("0", 10), (0, 0), (0, 31), (0, True)):
            with self.subTest(start=start, limit=limit):
                with self.assertRaises(ValueError):
                    validate_pagination(start, limit)

    def test_validate_choice(self):
        allowed = frozenset({"name", "date"})
        self.assertEqual(validate_choice("order_field", "name", allowed), "name")
        for bad in ("id", "", 123):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_choice("order_field", bad, allowed)

    def test_validate_date_filters(self):
        res = validate_date_filters({"date": dt.date(2026, 11, 22), "status": "open"}, ("date", "dueDate"))
        self.assertEqual(res, {"date": "2026-11-22", "status": "open"})
        with self.assertRaises(ValueError):
            validate_date_filters({"date": "22/11/2026"}, ("date",))

    def test_build_list_params_with_and_without_pagination_and_ordering(self):
        params = build_list_params(
            0,
            30,
            {"order_field": "date", "order_direction": "DESC", "status": "open", "date": dt.date(2026, 11, 22)},
            order_fields=frozenset({"date", "name", "dueDate"}),
            enums={"status": frozenset({"open", "closed"})},
            date_keys=("date", "dueDate"),
            paginate=True,
        )
        self.assertEqual(
            params,
            {
                "start": 0,
                "limit": 30,
                "order_field": "date",
                "order_direction": "DESC",
                "status": "open",
                "date": "2026-11-22",
            },
        )

        no_order = build_list_params(
            0, 15, {"number": 10}, order_fields=frozenset(), enums={}, date_keys=(), paginate=True
        )
        self.assertEqual(no_order, {"start": 0, "limit": 15, "number": 10})

        with self.assertRaises(ValueError):
            build_list_params(0, 30, {"order_field": "id"}, order_fields=frozenset(), enums={}, date_keys=())

        no_pag = build_list_params(
            None, None, {"fields": "deletable"}, order_fields=frozenset(),
            enums={"fields": frozenset({"deletable"})}, date_keys=(), paginate=False,
        )
        self.assertEqual(no_pag, {"fields": "deletable"})


if __name__ == "__main__":
    unittest.main()
