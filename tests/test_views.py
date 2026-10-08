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
    "columns": [{"assessment": "Listen Actively", "criterion": "Asks clarifying questions"}],
    "learners": [{
        "name": "=Evil", "username": "u1", "email": "u1@example.com",
        "cells": [{"percent": 87, "status": "demonstrated"}],
    }],
}


def _request():
    request = RequestFactory().get("/csv")
    request.user = SimpleNamespace(is_authenticated=True)
    return request


@pytest.fixture(autouse=True)
def _patch(monkeypatch, settings):
    settings.EDL_AUTO_ASSESSMENT_THRESHOLD = 75
    monkeypatch.setattr(views, "get_course_with_access", lambda *a, **k: None)
    monkeypatch.setattr(views.data, "build_report", lambda course_key, threshold: REPORT)


def test_csv_download():
    response = views.auto_assessment_scores_csv(_request(), COURSE_ID)

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert response["Content-Disposition"].startswith('attachment; filename="auto_assessment_scores_')
    assert response["Content-Disposition"].endswith('.csv"')
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["Assessment Name", "", "", "Listen Actively"]
    assert rows[1] == ["Learner", "Username", "Email", "Asks clarifying questions"]
    assert rows[2] == ["'=Evil", "u1", "u1@example.com", "87% (Demonstrated)"]


def test_invalid_course_id_is_404():
    with pytest.raises(Http404):
        views.auto_assessment_scores_csv(_request(), "not-a-course-id")


def test_non_staff_is_rejected(monkeypatch):
    def _deny(*args, **kwargs):
        raise Http404()
    monkeypatch.setattr(views, "get_course_with_access", _deny)
    with pytest.raises(Http404):
        views.auto_assessment_scores_csv(_request(), COURSE_ID)
