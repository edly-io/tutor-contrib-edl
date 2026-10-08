"""Tests for the pure report helpers."""

from edl_plugin.auto_assessment_scores import report
from edl_plugin.auto_assessment_scores.constants import STATUS_DEMONSTRATED, STATUS_NOT_DEMONSTRATED


def test_percent_rounds_half_up():
    assert report.percent(74.5, 100) == 75
    assert report.percent(74.4, 100) == 74
    assert report.percent(2, 3) == 67


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


def test_status_uses_rounded_value():
    cell = report.make_cell(74.6, 100, 75)
    assert cell == {"percent": 75, "status": STATUS_DEMONSTRATED}


def test_make_cell_none_without_usable_score():
    assert report.make_cell(None, 100, 75) is None
    assert report.make_cell(5, 0, 75) is None


def test_cell_text():
    assert report.cell_text(None) == ""
    assert report.cell_text({"percent": 87, "status": STATUS_DEMONSTRATED}) == "87% (Demonstrated)"
    assert report.cell_text({"percent": 53, "status": STATUS_NOT_DEMONSTRATED}) == "53% (Not Demonstrated)"


def test_safe_prefixes_formula_characters():
    for char in ("=", "+", "-", "@"):
        assert report.safe(char + "cmd") == "'" + char + "cmd"
    assert report.safe("Ayesha") == "Ayesha"
    assert report.safe(None) == ""


def test_build_rows_layout():
    data = {
        "columns": [
            {"assessment": "Listen Actively", "criterion": "Asks clarifying questions"},
            {"assessment": "Listen Actively", "criterion": "Paraphrases speakers concerns"},
            {"assessment": "Focus on Solutions", "criterion": "Identify a set of 3-5 possible solutions"},
        ],
        "learners": [
            {
                "name": "Ayesha Khan", "username": "ayesha.k", "email": "ayesha.khan@example.com",
                "cells": [
                    {"percent": 87, "status": STATUS_DEMONSTRATED},
                    {"percent": 53, "status": STATUS_NOT_DEMONSTRATED},
                    None,
                ],
            },
        ],
    }
    rows = report.build_rows(data)
    assert rows[0] == ["Assessment Name", "", "", "Listen Actively", "Listen Actively", "Focus on Solutions"]
    assert rows[1] == [
        "Learner", "Username", "Email",
        "Asks clarifying questions", "Paraphrases speakers concerns", "Identify a set of 3-5 possible solutions",
    ]
    assert rows[2] == [
        "Ayesha Khan", "ayesha.k", "ayesha.khan@example.com",
        "87% (Demonstrated)", "53% (Not Demonstrated)", "",
    ]
    assert len(rows) == 3
