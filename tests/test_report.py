"""Tests for the pure report helpers."""

from datetime import datetime, timedelta, timezone

from edl_plugin.auto_assessment_scores import report
from edl_plugin.auto_assessment_scores.constants import STATUS_DEMONSTRATED, STATUS_LABELS, STATUS_NOT_DEMONSTRATED


def test_percent_keeps_at_most_two_decimals():
    assert report.percent(74.5, 100) == 74.5
    assert report.percent(74.4, 100) == 74.4
    assert report.percent(0.145, 1) == 14.5
    assert report.percent(15, 20) == 75
    assert report.percent(2, 3) == 66.67
    assert report.percent(1, 3) == 33.33
    assert report.percent(74.995, 100) == 75
    assert isinstance(report.percent(75.0, 100), int)


def test_status_uses_displayed_percent():
    assert report.status(report.percent(74.9, 100), 75) == STATUS_NOT_DEMONSTRATED
    assert report.status(report.percent(74.994, 100), 75) == STATUS_NOT_DEMONSTRATED
    assert report.status(report.percent(74.995, 100), 75) == STATUS_DEMONSTRATED
    assert report.status(report.percent(75, 100), 75) == STATUS_DEMONSTRATED


def test_cell_text_keeps_decimals():
    assert report.cell_text(report.make_cell(74.5, 100, 75)) == "74.5% (Not demonstrated)"


def test_percent_caps_at_100():
    assert report.percent(120, 100) == 100


def test_percent_none_when_not_computable():
    assert report.percent(None, 100) is None
    assert report.percent(5, 0) is None
    assert report.percent(5, None) is None
    assert report.percent(5, -1) is None


def test_status_boundary():
    assert report.status(75, 75) == STATUS_DEMONSTRATED
    assert report.status(74, 75) == STATUS_NOT_DEMONSTRATED


def test_make_cell_does_not_round_up_to_threshold():
    cell = report.make_cell(74.6, 100, 75)
    assert cell == {"percent": 74.6, "status": STATUS_NOT_DEMONSTRATED}


def test_make_cell_none_without_usable_score():
    assert report.make_cell(None, 100, 75) is None
    assert report.make_cell(5, 0, 75) is None


def test_cell_text():
    assert report.cell_text(None) == ""
    assert report.cell_text({"percent": 87, "status": STATUS_DEMONSTRATED}) == "87% (Demonstrated)"
    assert report.cell_text({"percent": 53, "status": STATUS_NOT_DEMONSTRATED}) == "53% (Not demonstrated)"


def test_status_labels_are_sentence_case():
    assert STATUS_LABELS == {STATUS_DEMONSTRATED: "Demonstrated", STATUS_NOT_DEMONSTRATED: "Not demonstrated"}


def test_safe_prefixes_formula_characters():
    for char in ("=", "+", "-", "@", "\t", "\r"):
        assert report.safe(char + "cmd") == "'" + char + "cmd"
    assert report.safe("Ayesha") == "Ayesha"
    assert report.safe(None) == ""


def test_format_date_utc_aware():
    assert report.format_date(datetime(2026, 10, 14, 9, 30, tzinfo=timezone.utc)) == "Oct 14, 2026"


def test_format_date_day_has_no_leading_zero():
    assert report.format_date(datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)) == "Oct 5, 2026"
    assert report.format_date(datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)) == "Oct 20, 2026"


def test_format_date_december_and_every_month_name():
    assert report.format_date(datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)) == "Dec 31, 2026"
    names = [report.format_date(datetime(2026, m, 1, tzinfo=timezone.utc)).split()[0] for m in range(1, 13)]
    assert names == ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def test_format_date_zone_can_move_the_year():
    late = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert report.format_date(late, "Asia/Karachi") == "Jan 1, 2027"


def test_format_date_converts_to_utc_across_midnight():
    minus_five = timezone(timedelta(hours=-5))
    assert report.format_date(datetime(2026, 10, 14, 23, 30, tzinfo=minus_five)) == "Oct 15, 2026"


def test_format_date_naive_is_treated_as_utc():
    assert report.format_date(datetime(2026, 1, 5, 0, 0)) == "Jan 5, 2026"


def test_format_date_in_browser_zone_moves_the_day():
    late_utc = datetime(2026, 10, 15, 3, 30, tzinfo=timezone.utc)
    assert report.format_date(late_utc, "UTC") == "Oct 15, 2026"
    assert report.format_date(late_utc, "Pacific/Honolulu") == "Oct 14, 2026"
    assert report.format_date(late_utc, "Asia/Karachi") == "Oct 15, 2026"
    assert report.format_date(datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc), "Asia/Karachi") == "Oct 16, 2026"


def test_format_date_naive_value_with_zone_is_read_as_utc():
    assert report.format_date(datetime(2026, 10, 15, 3, 30), "Pacific/Honolulu") == "Oct 14, 2026"


def test_format_date_unknown_or_empty_zone_falls_back_to_utc():
    value = datetime(2026, 10, 15, 3, 30, tzinfo=timezone.utc)
    for bad in (None, "", "Not/AZone", "../etc/passwd", "x" * 200, 5):
        assert report.format_date(value, bad) == "Oct 15, 2026"


def test_format_date_none_is_empty():
    assert report.format_date(None) == ""


def test_date_entry():
    assert report.date_entry("Oct 14, 2026") == {"date": "Oct 14, 2026", "note": ""}
    assert report.date_entry("Oct 14, 2026", "Peer score") == {"date": "Oct 14, 2026", "note": "Peer score"}


def test_build_rows_layout():
    data = {
        "columns": [
            {"competency": "Communication", "block_id": "b1", "assessment": "Listen Actively",
             "criterion": "Asks clarifying questions"},
            {"competency": "Communication", "block_id": "b1", "assessment": "Listen Actively",
             "criterion": "Paraphrases speakers concerns"},
            {"competency": "Communication", "block_id": "b2", "assessment": "Focus on Solutions",
             "criterion": "Identify a set of 3-5 possible solutions"},
        ],
        "learners": [
            {
                "name": "Ayesha Khan", "username": "ayesha.k", "email": "ayesha.khan@example.com",
                "cells": [
                    {"percent": 87, "status": STATUS_DEMONSTRATED},
                    {"percent": 53, "status": STATUS_NOT_DEMONSTRATED},
                    None,
                ],
                "dates": {"b1": {"date": "Oct 14, 2026", "note": "Peer score"}},
            },
            {
                "name": "Bilal Ahmed", "username": "bilal.a", "email": "bilal@example.com",
                "cells": [None, None, {"percent": 100, "status": STATUS_DEMONSTRATED}],
                "dates": {"b2": {"date": "Nov 1, 2026", "note": ""}},
            },
            {
                "name": "Chen Wei", "username": "chen.w", "email": "chen@example.com",
                "cells": [None, None, None],
                "dates": {},
            },
        ],
    }
    rows = report.build_rows(data)
    assert rows[0] == [
        "Competency", "", "",
        "Communication", "Communication", "Communication", "Communication", "Communication",
    ]
    assert rows[1] == [
        "Assessment Name", "", "",
        "Listen Actively", "Listen Actively", "Listen Actively", "Focus on Solutions", "Focus on Solutions",
    ]
    assert rows[2] == [
        "Learner", "Username", "Email",
        "Attempt Date", "Asks clarifying questions", "Paraphrases speakers concerns",
        "Attempt Date", "Identify a set of 3-5 possible solutions",
    ]
    assert rows[3] == [
        "Ayesha Khan", "ayesha.k", "ayesha.khan@example.com",
        "Oct 14, 2026", "87% (Demonstrated)", "53% (Not demonstrated)", "", "",
    ]
    assert rows[4] == [
        "Bilal Ahmed", "bilal.a", "bilal@example.com",
        "", "", "", "Nov 1, 2026", "100% (Demonstrated)",
    ]
    assert rows[5] == ["Chen Wei", "chen.w", "chen@example.com", "", "", "", "", ""]
    assert len(rows) == 6
    # The note is on screen only.
    assert not any("Peer score" in str(cell) for row in rows for cell in row)


def test_build_rows_without_columns_has_only_learner_headings():
    rows = report.build_rows({"columns": [], "learners": []})
    assert rows == [["Competency", "", ""], ["Assessment Name", "", ""], ["Learner", "Username", "Email"]]
