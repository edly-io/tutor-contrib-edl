"""
Pure helpers for the auto assessment scores report.

Imports nothing from Django or edx-platform so the logic can be unit tested
with only the standard library.
"""

from datetime import timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from .constants import STATUS_DEMONSTRATED, STATUS_LABELS, STATUS_NOT_DEMONSTRATED

# Fixed so the text does not depend on the server locale (``%b``) or platform (``%-d``).
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def percent(score_given, score_maximum):
    """
    Return the score as a percent of the maximum, at most 2 decimals, capped at 100.

    Rounds half up at the second decimal (66.666 is 66.67, 74.995 is 75).
    Trailing zeros are dropped, so whole values come back as ``int`` and display
    as ``75``, not ``75.00``. Decimal keeps float noise out (0.145 of 1 is 14.5,
    not 14.499999999999998). Returns ``None`` when the score cannot be computed.
    """
    if score_given is None or not score_maximum or score_maximum <= 0:
        return None
    value = min(Decimal(str(score_given)) * 100 / Decimal(str(score_maximum)), Decimal(100))
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value) if value == value.to_integral_value() else float(value)


def status(pct, threshold):
    """Return the status for a percent."""
    return STATUS_DEMONSTRATED if pct >= threshold else STATUS_NOT_DEMONSTRATED


def make_cell(score_given, score_maximum, threshold):
    """Return ``{"percent", "status"}`` for a score, or ``None`` if it has no usable value."""
    pct = percent(score_given, score_maximum)
    if pct is None:
        return None
    return {"percent": pct, "status": status(pct, threshold)}


def cell_text(cell):
    """Return the CSV text for a cell: ``87% (Demonstrated)``, ``40% (Not demonstrated)`` or an empty string."""
    if cell is None:
        return ""
    return "{}% ({})".format(cell["percent"], STATUS_LABELS[cell["status"]])


def safe(value):
    """Prefix values a spreadsheet could run as a formula (``=``, ``+``, ``-``, ``@``, tab, carriage return)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def resolve_zone(name):
    """Return the tzinfo for an IANA zone name from the browser, or UTC if it is empty or unknown."""
    if name and isinstance(name, str) and len(name) <= 64:
        try:
            return ZoneInfo(name)
        except (KeyError, ValueError, OSError):
            pass
    return timezone.utc


def format_date(value, tz=None):
    """
    Return ``value`` as ``Oct 20, 2026`` in the zone named ``tz`` (an IANA name), or ``""`` for ``None``.

    The month is always the English abbreviation and the day has no leading zero.
    An empty or unknown ``tz`` means UTC. Naive datetimes are treated as UTC.
    """
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(resolve_zone(tz))
    return "{} {}, {}".format(MONTHS[local.month - 1], local.day, local.year)


def date_entry(date_text, note=""):
    """Return the per-assessment date info sent to the browser: ``{"date", "note"}``."""
    return {"date": date_text, "note": note}


def build_rows(report):
    """
    Return the CSV rows for ``report``.

    ``report`` is ``{"columns": [{"competency", "block_id", "assessment", "criterion"}],
    "learners": [{"name", "username", "email", "cells": [cell | None],
    "dates": {block_id: {"date", "note"}}}]}``.

    Row 1 repeats the competency (the course title) and row 2 the assessment
    name above each criterion (a CSV cannot merge cells). Row 3 holds the
    learner headings and the criteria names.

    Each assessment (a run of columns with the same ``block_id``) starts with a
    ``Attempt Date`` column. A learner who has not taken the assessment gets an
    empty cell there. The date note (``learner["dates"][block_id]["note"]``) is
    shown on screen only and is never written to the CSV.
    """
    columns = report["columns"]
    row1 = ["Competency", "", ""]
    row2 = ["Assessment Name", "", ""]
    row3 = ["Learner", "Username", "Email"]
    # One entry per output column after the learner columns: ("date", block_id) or ("cell", column index).
    layout = []
    previous_block = None
    for index, column in enumerate(columns):
        if index == 0 or column["block_id"] != previous_block:
            row1.append(safe(column["competency"]))
            row2.append(safe(column["assessment"]))
            row3.append("Attempt Date")
            layout.append(("date", column["block_id"]))
        previous_block = column["block_id"]
        row1.append(safe(column["competency"]))
        row2.append(safe(column["assessment"]))
        row3.append(safe(column["criterion"]))
        layout.append(("cell", index))
    rows = [row1, row2, row3]
    for learner in report["learners"]:
        row = [safe(learner["name"]), safe(learner["username"]), safe(learner["email"])]
        dates = learner.get("dates") or {}
        for kind, key in layout:
            if kind == "date":
                row.append(dates.get(key, {}).get("date", ""))
            else:
                row.append(cell_text(learner["cells"][key]))
        rows.append(row)
    return rows
