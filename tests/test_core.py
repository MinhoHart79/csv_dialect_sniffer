"""Tests for csv_dialect_sniffer.core.

These tests exercise the behaviour the implementation actually claims to
support: deterministic dialect selection over a fixed candidate set, quote
and escape handling, and refusal to guess on non-CSV input. They do not
assert on line-terminator detection or skip-initial-space, because the
library explicitly does not support those.
"""

from __future__ import annotations

import csv
import io
import unittest

from csv_dialect_sniffer import Dialect, detect_dialect, detect_dialects


class TestDetectDialect(unittest.TestCase):
    def test_comma_delimited(self):
        text = "a,b,c\n1,2,3\n4,5,6\n"
        d = detect_dialect(text)
        self.assertEqual(d.delimiter, ",")
        self.assertEqual(d.quotechar, '"')
        self.assertIsNone(d.escapechar)

    def test_tab_delimited(self):
        text = "a\tb\tc\n1\t2\t3\n4\t5\t6\n"
        d = detect_dialect(text)
        self.assertEqual(d.delimiter, "\t")

    def test_semicolon_delimited(self):
        text = "a;b;c\n1;2;3\n4;5;6\n"
        d = detect_dialect(text)
        self.assertEqual(d.delimiter, ";")

    def test_pipe_delimited(self):
        text = "a|b|c\n1|2|3\n4|5|6\n"
        d = detect_dialect(text)
        self.assertEqual(d.delimiter, "|")

    def test_dialect_is_a_dataclass_instance(self):
        d = detect_dialect("a,b\n1,2\n")
        self.assertIsInstance(d, Dialect)
        self.assertEqual(d.lineterminator, "\r\n")
        self.assertTrue(d.doublequote)

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            detect_dialect("")

    def test_non_csv_input_raises(self):
        # Prose with no consistent delimiter: every candidate should parse
        # every line as a single field, so no dialect qualifies.
        text = (
            "the quick brown fox\n"
            "jumps over the lazy dog\n"
            "pack my box with five dozen liquor jugs\n"
        )
        with self.assertRaises(ValueError):
            detect_dialect(text)

    def test_deterministic_same_result_every_call(self):
        text = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"
        first = detect_dialect(text)
        second = detect_dialect(text)
        self.assertEqual(first, second)

    def test_quoted_field_containing_delimiter(self):
        text = 'name,note\n"Smith, Jr.","hello, world"\n'
        d = detect_dialect(text)
        self.assertEqual(d.delimiter, ",")
        self.assertEqual(d.quotechar, '"')
        # Re-parsing under the detected dialect should yield the expected
        # field count, proving the quote handling is real.
        rows = list(csv.reader(text.splitlines(), dialect=d.as_csv_dialect()))
        self.assertEqual([len(r) for r in rows], [2, 2])

    def test_quoted_field_containing_newline(self):
        text = 'a,b\n"line1\nline2",2\n3,4\n'
        d = detect_dialect(text)
        self.assertEqual(d.delimiter, ",")
        rows = list(csv.reader(io.StringIO(text), dialect=d.as_csv_dialect()))
        # First data row must contain the embedded newline intact.
        self.assertEqual(rows[1], ["line1\nline2", "2"])

    def test_single_quote_character(self):
        text = "a,b\n'has,comma',2\n3,4\n"
        d = detect_dialect(text)
        self.assertEqual(d.quotechar, "'")


class TestDetectDialects(unittest.TestCase):
    def test_returns_ranked_list(self):
        text = "a,b,c\n1,2,3\n4,5,6\n"
        ranked = detect_dialects(text)
        self.assertGreater(len(ranked), 0)
        self.assertEqual(ranked[0].delimiter, ",")
        # Every ranked dialect should parse to more than one field somewhere.
        for d in ranked:
            rows = list(csv.reader(text.splitlines(), dialect=d.as_csv_dialect()))
            self.assertGreater(max(len(r) for r in rows), 1)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(detect_dialects(""), [])

    def test_non_csv_returns_empty_list(self):
        text = "just some prose\nwith no delimiters\nat all\n"
        self.assertEqual(detect_dialects(text), [])


class TestAsCsvDialect(unittest.TestCase):
    def test_runtime_dialect_round_trips(self):
        text = "a,b\n1,2\n"
        d = detect_dialect(text)
        runtime = d.as_csv_dialect()
        rows = list(csv.reader(text.splitlines(), dialect=runtime))
        self.assertEqual(rows, [["a", "b"], ["1", "2"]])


if __name__ == "__main__":
    unittest.main()
