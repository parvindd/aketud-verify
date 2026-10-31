"""Policy sale-date parsing (Fix 36).

Deterministic only — a sale date is never guessed by a model. A sale
date is held as a range ``(earliest, latest)`` of ``datetime.date``:

* an explicit ``YYYY-MM-DD`` (``--sale-date`` / the web date field)
  is a single day;
* text such as "bought in 2021", "purchased in March 2021",
  "2021 mein li thi" or "2021 में ली थी" gives that year or month.

Only text next to a purchase word is read, so "under the 2024 product
rules" is never taken as a sale date. A range that straddles a rule's
``applies_from`` date is ``unknown`` (fail closed: the caller must
not pick a side).
"""
import calendar
import re
from datetime import date

CURRENT = "current"   # sold on/after applies_from
OLDER = "older"       # sold before applies_from
UNKNOWN = "unknown"   # no sale date, or the range straddles it

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_MONTHS = {}
for _i, _name in enumerate(calendar.month_name[1:], 1):
    _MONTHS[_name.lower()] = _i
    _MONTHS[_name[:3].lower()] = _i
_MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_HI_MONTHS = ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
              "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर")

_ISO_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")

# English: purchase word, a few words, optional day/month, a year.
_EN_RE = re.compile(
    r"\b(?:bought|buy|purchased|purchase|took|taken)\b"
    r"[^.?!\n\d]{0,40}?"
    r"(?:\b(?:in|on|during|from)\s+)?"
    r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?"
    r"(?:(" + _MONTH_RE + r")\.?,?\s+)?"
    r"((?:19|20)\d{2})\b",
    re.IGNORECASE)
# Hinglish: "[March] 2021 mein (policy) li / kharidi".
_HINGLISH_RE = re.compile(
    r"(?:\b(" + _MONTH_RE + r")\s+)?\b((?:19|20)\d{2})\s*(?:mein|me|main)"
    r"\s+(?:\w+\s+){0,2}?(?:li|liya|lee|liye|kharidi|kharida|khareedi|"
    r"khareeda|kharide|buy)\b",
    re.IGNORECASE)
# Hindi: "2021 में (पॉलिसी) ली / खरीदी".
_HI_RE = re.compile(
    r"((?:19|20)\d{2})\s*में\s+(?:\S+\s+){0,2}?"
    r"(?:ली|लिया|लिए|खरीदी|खरीदा|ख़रीदी|ख़रीदा|खरीदे)")


def _range(year, month=None, day=None):
    if day and month:
        d = date(year, month, day)
        return d, d
    if month:
        return (date(year, month, 1),
                date(year, month, calendar.monthrange(year, month)[1]))
    return date(year, 1, 1), date(year, 12, 31)


def _result(earliest, latest, source, precision, text):
    return {"earliest": earliest, "latest": latest, "source": source,
            "precision": precision, "text": text}


def parse_iso(value):
    """Parse an explicit ``YYYY-MM-DD``; raise ``ValueError`` if not."""
    match = _ISO_RE.match(str(value or ""))
    if not match:
        raise ValueError("sale date must be YYYY-MM-DD: %r" % (value,))
    day = date(int(match.group(1)), int(match.group(2)),
               int(match.group(3)))
    return _result(day, day, "explicit", "day", day.isoformat())


def parse_text(text):
    """Find a sale date in free text; ``None`` if none is stated."""
    if not text:
        return None
    text = str(text).translate(_DEVANAGARI_DIGITS)
    match = _EN_RE.search(text)
    if match:
        day = int(match.group(1)) if match.group(1) else None
        month = (_MONTHS[match.group(2).lower()]
                 if match.group(2) else None)
        year = int(match.group(3))
        if day and not month:
            day = None  # "bought 2 policies in 2021": not a day
        try:
            earliest, latest = _range(year, month, day)
        except ValueError:
            return None
        precision = "day" if day else ("month" if month else "year")
        return _result(earliest, latest, "text", precision,
                       match.group(0))
    match = _HINGLISH_RE.search(text)
    if match:
        month = (_MONTHS[match.group(1).lower()]
                 if match.group(1) else None)
        earliest, latest = _range(int(match.group(2)), month)
        return _result(earliest, latest, "text",
                       "month" if month else "year", match.group(0))
    match = _HI_RE.search(text)
    if match:
        earliest, latest = _range(int(match.group(1)))
        return _result(earliest, latest, "text", "year",
                       match.group(0))
    return None


def resolve(sale_date=None, question=None):
    """Explicit date wins; else parse the question text.

    Returns ``(sale, error)``. An invalid explicit date is not
    guessed at: ``sale`` is ``None`` (treated as unknown) and
    ``error`` says why.
    """
    if isinstance(sale_date, date):
        return _result(sale_date, sale_date, "explicit", "day",
                       sale_date.isoformat()), None
    if sale_date is not None and str(sale_date).strip():
        try:
            return parse_iso(sale_date), None
        except ValueError as exc:
            return None, str(exc)
    return parse_text(question), None


def classify(sale, applies_from):
    """``current`` / ``older`` / ``unknown`` against ``applies_from``."""
    if not applies_from:
        return CURRENT
    if not sale:
        return UNKNOWN
    cutoff = date.fromisoformat(str(applies_from))
    if sale["earliest"] >= cutoff:
        return CURRENT
    if sale["latest"] < cutoff:
        return OLDER
    return UNKNOWN


def display(sale, lang="en"):
    """Sale date as stated precision, e.g. ``March 2021`` / ``2021``."""
    if not sale:
        return ""
    d = sale["earliest"]
    if lang == "hi":
        month = _HI_MONTHS[d.month - 1]
    else:
        month = calendar.month_name[d.month]
    if sale["precision"] == "day":
        return "%d %s %d" % (d.day, month, d.year)
    if sale["precision"] == "month":
        return "%s %d" % (month, d.year)
    return str(d.year)


def date_display(iso_date, lang="en"):
    """``2024-04-01`` -> ``1 April 2024`` (``1 अप्रैल 2024`` in hi)."""
    d = date.fromisoformat(str(iso_date))
    month = (_HI_MONTHS[d.month - 1] if lang == "hi"
             else calendar.month_name[d.month])
    return "%d %s %d" % (d.day, month, d.year)


def to_trace(sale):
    """JSON-safe copy of ``sale`` for the trace."""
    if not sale:
        return None
    out = dict(sale)
    out["earliest"] = sale["earliest"].isoformat()
    out["latest"] = sale["latest"].isoformat()
    return out
