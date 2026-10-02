from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


# Fixed candidate sets. The order here is also the tie-break priority: when
# two dialects score equally, the earlier candidate wins.
_DELIMITERS: Tuple[str, ...] = (",", "\t", ";", "|")
_QUOTES: Tuple[str, ...] = ('"', "'")
_ESCAPES: Tuple[Optional[str], ...] = (None, "\\")

# We treat truly empty fields as width 1 for scoring, but fields that are
# *only* whitespace still count. A row of a single empty string is almost
# never a real CSV record, so we penalize it.
_MIN_FIELD_WIDTH = 1

# Rows that parse to a single field are weak evidence. We cap how much they
# can contribute so they cannot dominate a file that happens to contain a few
# un-delimited lines.
_SINGLE_FIELD_CAP = 0.25


@dataclass(frozen=True)
class Dialect:
    """A detected CSV dialect.

    Attributes:
        delimiter: The field separator character.
        quotechar: The quote character used to wrap fields containing the
            delimiter, newlines, or the quote character itself.
        escapechar: The character used to escape the quote character inside
            quoted fields, or ``None`` if escaping is done by doubling.
        lineterminator: Always ``"\r\n"``. Returned for compatibility with
            :class:`csv.Dialect`; the detector itself accepts any line
            ending in the input.
        doublequote: Always ``True``. The detector assumes that when no
            explicit escape character is in use, quotes are escaped by
            doubling, which is the RFC 4180 convention.
    """

    delimiter: str
    quotechar: str
    escapechar: Optional[str]
    lineterminator: str = "\r\n"
    doublequote: bool = True

    def as_csv_dialect(self) -> csv.Dialect:
        """Return a runtime :class:`csv.Dialect` subclass for this dialect.

        Useful when the caller wants to pass the result straight into
        :func:`csv.reader` via the ``dialect`` argument.
        """

        instance = self

        class _Runtime(csv.Dialect):
            delimiter = instance.delimiter
            quotechar = instance.quotechar
            escapechar = instance.escapechar
            lineterminator = instance.lineterminator
            doublequote = instance.doublequote
            quoting = csv.QUOTE_MINIMAL
            skipinitialspace = False

        _Runtime.__name__ = "DetectedDialect"
        return _Runtime  # type: ignore[return-value]


@dataclass(frozen=True)
class _Score:
    """Internal scoring result for a single candidate dialect."""

    dialect: Dialect
    value: float
    fields_per_row: Tuple[int, ...]


def _split_preserving_quotes(text: str) -> List[str]:
    """Split text into logical CSV lines without losing embedded newlines.

    ``str.splitlines`` would happily break a quoted field that contains a
    newline into two pieces. For a dialect detector that is fatal: the row
    that actually had N fields would look like two rows of fewer fields. We
    therefore walk the text character by character, tracking quote state so
    that newlines inside quotes are kept.
    """

    lines: List[str] = []
    buf: List[str] = []
    in_quote = False
    quote_char = ""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quote:
            buf.append(ch)
            if ch == quote_char:
                # Handle doubled-quote escaping (the default when no
                # explicit escapechar is present). We peek ahead; if the
                # next character is the same quote, we consume it as a
                # literal quote and stay inside the quoted region.
                if i + 1 < n and text[i + 1] == quote_char:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                in_quote = False
            i += 1
            continue

        if ch in ('"', "'") and not buf:
            # A quote at the start of a field opens a quoted region.
            in_quote = True
            quote_char = ch
            buf.append(ch)
            i += 1
            continue

        if ch in ("\r", "\n") and not in_quote and any(buf):
            # End of a logical line. We treat a bare \r or \n as a record
            # separator; a \r\n pair is handled by the second character
            # falling into the ``not any(buf)`` branch below.
            lines.append("".join(buf))
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    if any(buf):
        lines.append("".join(buf))
    return lines


def _parse_rows(text: str, dialect: Dialect) -> List[List[str]]:
    """Parse ``text`` under ``dialect`` and return the logical rows.

    We use the stdlib :mod:`csv` module to do the actual field splitting,
    but we feed it our own pre-split logical lines so that embedded newlines
    in quoted fields survive. This keeps the detector honest: it scores
    dialects on the rows a human reader would see, not on whatever
    ``csv.reader`` happens to produce when handed a raw blob.
    """

    logical_lines = _split_preserving_quotes(text)
    reader = csv.reader(logical_lines, dialect=dialect.as_csv_dialect())
    rows: List[List[str]] = []
    for row in reader:
        rows.append(row)
    return rows


def _score_dialect(dialect: Dialect, text: str) -> _Score:
    """Score a candidate dialect against ``text``.

    The score rewards two things:
      * Consistency — the fraction of rows that share the modal field count.
      * Breadth — the number of fields in that modal count, so that a file
        that genuinely has eight columns beats one that has one.

    Single-field rows are heavily discounted: a dialect that parses every
    line as one big field is technically consistent but useless.
    """

    try:
        rows = _parse_rows(text, dialect)
    except csv.Error:
        return _Score(dialect, 0.0, ())

    if not rows:
        return _Score(dialect, 0.0, ())

    counts = tuple(len(r) for r in rows)
    # Find the modal field count. Ties go to the higher count, which is the
    # more generous interpretation of the file.
    distinct = sorted(set(counts), reverse=True)
    modal = max(distinct, key=lambda c: (counts.count(c), c))
    consistent = counts.count(modal)
    consistency = consistent / len(counts)

    if modal <= 1:
        breadth = _SINGLE_FIELD_CAP
    else:
        breadth = float(modal)

    score = consistency * breadth
    return _Score(dialect, score, counts)


def _candidate_dialects() -> Iterable[Dialect]:
    """Yield every candidate dialect in priority order."""

    for delim in _DELIMITERS:
        for quote in _QUOTES:
            for esc in _ESCAPES:
                yield Dialect(
                    delimiter=delim,
                    quotechar=quote,
                    escapechar=esc,
                )


def detect_dialects(text: str) -> List[Dialect]:
    """Return all dialects that parse ``text`` well, best-first.

    A dialect is included if it produces more than one field per row on at
    least one row, and has a positive score. The list is sorted by score
    descending; ties are broken by the fixed candidate order (comma, tab,
    semicolon, pipe; double-quote, single-quote; no-escape, backslash).
    """

    if not text:
        return []

    scored: List[_Score] = []
    for dialect in _candidate_dialects():
        s = _score_dialect(dialect, text)
        if s.value > 0.0 and max(s.fields_per_row, default=0) > 1:
            scored.append(s)

    scored.sort(key=lambda s: s.value, reverse=True)
    return [s.dialect for s in scored]


def detect_dialect(text: str) -> Dialect:
    """Detect the best-scoring CSV dialect for ``text``.

    Raises :class:`ValueError` if the input is empty or no candidate
    dialect produces a useful parse (i.e. every candidate yields only
    single-field rows). This is an explicit refusal to guess: returning a
    default dialect on garbage would mask real misconfiguration.
    """

    if not text:
        raise ValueError("cannot detect a dialect from empty input")

    ranked = detect_dialects(text)
    if not ranked:
        raise ValueError(
            "no candidate dialect parsed the input into more than one field; "
            "the input may not be delimited CSV"
        )
    return ranked[0]
