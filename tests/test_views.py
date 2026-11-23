"""Tests for the CSV view with data and access checks monkeypatched."""

import csv
import io
from types import SimpleNamespace

import pytest
from django.http import Http404
from django.test import RequestFactory

views = pytest.importorskip(
    "edl_plugin.auto_assessment_scores.views",
    reason="requires Django and opaque-keys",
)

COURSE_ID = "course-v1:Org+C+R"
REPORT = {
    "columns": [{
        "competency": "Communication", "block_id": "b1", "assessment": "Listen Actively",
        "criterion": "Asks clarifying questions",
    }],
    "learners": [{
        "name": "=Evil", "username": "u1", "email": "u1@example.com",
        "cells": [{"percent": 87, "status": "demonstrated"}],
        "dates": {"b1": {"date": "Oct 14, 2026", "note": ""}},
    }],
}


def _request(**params):
    request = RequestFactory().get("/csv", params)
    request.user = SimpleNamespace(is_authenticated=True)
    return request


@pytest.fixture(autouse=True)
def _patch(monkeypatch, settings):
    settings.EDL_AUTO_ASSESSMENT_THRESHOLD = 75
    monkeypatch.setattr(views, "get_course_with_access", lambda *a, **k: None)
    calls = []

    def build_report(course_key, threshold, tz=None):
        calls.append({"tz": tz})
        return REPORT

    monkeypatch.setattr(views.data, "build_report", build_report)
    return calls


def test_csv_download():
    response = views.auto_assessment_scores_csv(_request(), COURSE_ID)

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert response["Content-Disposition"].startswith('attachment; filename="auto_assessment_scores_')
    assert response["Content-Disposition"].endswith('.csv"')
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["Competency", "", "", "Communication", "Communication"]
    assert rows[1] == ["Assessment Name", "", "", "Listen Actively", "Listen Actively"]
    assert rows[2] == ["Learner", "Username", "Email", "Attempt Date", "Asks clarifying questions"]
    assert rows[3] == ["'=Evil", "u1", "u1@example.com", "Oct 14, 2026", "87% (Demonstrated)"]


def test_invalid_course_id_is_404():
    with pytest.raises(Http404):
        views.auto_assessment_scores_csv(_request(), "not-a-course-id")


def test_non_staff_is_rejected(monkeypatch):
    def _deny(*args, **kwargs):
        raise Http404()
    monkeypatch.setattr(views, "get_course_with_access", _deny)
    with pytest.raises(Http404):
        views.auto_assessment_scores_csv(_request(), COURSE_ID)


def test_csv_without_params_builds_the_full_report(_patch):
    views.auto_assessment_scores_csv(_request(), COURSE_ID)
    assert _patch == [{"tz": ""}]


def test_csv_forwards_the_zone_and_ignores_search_params(_patch):
    views.auto_assessment_scores_csv(_request(q="ayesha", assessment="b1", tz="Asia/Karachi"), COURSE_ID)
    assert _patch == [{"tz": "Asia/Karachi"}]


def test_csv_cell_text_uses_sentence_case_status(monkeypatch):
    report_data = {
        "columns": REPORT["columns"],
        "learners": [dict(REPORT["learners"][0], cells=[{"percent": 40, "status": "not_demonstrated"}])],
    }
    monkeypatch.setattr(views.data, "build_report", lambda *a, **k: report_data)
    rows = list(csv.reader(io.StringIO(views.auto_assessment_scores_csv(_request(), COURSE_ID).content.decode())))
    assert rows[3][4] == "40% (Not demonstrated)"


def test_csv_unauthenticated_user_is_redirected_to_login():
    request = _request()
    request.user = SimpleNamespace(is_authenticated=False)
    assert views.auto_assessment_scores_csv(request, COURSE_ID).status_code == 302
