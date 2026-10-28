# csv_dialect_sniffer

A deterministic, transparent replacement for `csv.Sniffer`. It detects the
delimiter, quote character, and escape character of CSV-like input by scoring
a fixed candidate set and picking the best parse — no random sampling, no
hidden heuristics.

## Usage

```python
from csv_dialect_sniffer import detect_dialect, detect_dialects, Dialect

d: Dialect = detect_dialect("a,b,c\n1,2,3\n4,5,6\n")
print(d.delimiter, d.quotechar, d.escapechar)  # , " None

# All plausible dialects, best-first:
ranked = detect_dialects("a,b,c\n1,2,3\n4,5,6\n")
```

`Dialect` is a frozen dataclass with `delimiter`, `quotechar`, `escapechar`,
`lineterminator` (always `"\r\n"`), and `doublequote` (always `True`). Call
`d.as_csv_dialect()` to get a `csv.Dialect` subclass you can pass to
`csv.reader`.

## Why this exists

`csv.Sniffer` uses a randomized sample and a set of internal heuristics,
which means the same input can produce different results across runs and
the reasoning is hard to audit. This library trades coverage for
transparency: it considers a small, explicit candidate set (comma, tab,
semicolon, pipe; double- and single-quote; no-escape and backslash) and
scores each by how consistently it splits the input into a sensible number
of fields. The result is reproducible and the criteria are visible in code.

## The awkward edge

The detector refuses to guess on input it cannot parse into more than one
field per row — prose, log lines, or genuinely non-delimited text will raise
`ValueError` from `detect_dialect` rather than returning a default dialect
that silently mislabels the data. If your input is single-column, you do not
need a dialect detector; you already know the structure.

It also does not detect line terminators (it accepts whatever the input
contains) and does not infer `skipinitialspace`, because that interacts with
quoting in ways a transparent scorer should not paper over. If your files
mix spaces and quotes at field boundaries, preprocess them first.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

## Limitations

Values are coerced to floats, so very large integers lose precision. If you need
exact integer aggregates over a window, this is the wrong tool.

## Contributing

Issues and pull requests are welcome. Please keep the dependency list empty —
that constraint is the point of the project, not an oversight.

