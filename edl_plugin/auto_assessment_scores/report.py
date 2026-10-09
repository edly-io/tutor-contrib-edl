"""
Pure helpers for the auto assessment scores report.

Imports nothing from Django or edx-platform so the logic can be unit tested
with only the standard library.
"""

from decimal import ROUND_HALF_UP, Decimal

from .constants import STATUS_DEMONSTRATED, STATUS_LABELS, STATUS_NOT_DEMONSTRATED


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
    """Return the CSV text for a cell: ``87% (Demonstrated)`` or an empty string."""
    if cell is None:
        return ""
    return "{}% ({})".format(cell["percent"], STATUS_LABELS[cell["status"]])


def safe(value):
    """Prefix values a spreadsheet could run as a formula (``=``, ``+``, ``-``, ``@``, tab, carriage return)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def build_rows(report):
    """
    Return the CSV rows for ``report``.

    ``report`` is ``{"columns": [{"assessment", "criterion"}], "learners":
    [{"name", "username", "email", "cells": [cell | None]}]}``.

    Row 1 repeats the assessment name above each of its criteria (a CSV cannot
    merge cells). Row 2 holds the learner headings and the criteria names.
    """
    columns = report["columns"]
    rows = [
        ["Assessment Name", "", ""] + [safe(c["assessment"]) for c in columns],
        ["Learner", "Username", "Email"] + [safe(c["criterion"]) for c in columns],
    ]
    for learner in report["learners"]:
        rows.append(
            [safe(learner["name"]), safe(learner["username"]), safe(learner["email"])]
            + [cell_text(c) for c in learner["cells"]]
        )
    return rows
