"""Tests for the paged JSON endpoint with data and access checks monkeypatched."""

import json
from types import SimpleNamespace

import pytest
from django.http import Http404
from django.test import RequestFactory

views = pytest.importorskip(
    "edl_plugin.auto_assessment_scores.views",
    reason="requires Django and opaque-keys",
)

COURSE_ID = "course-v1:Org+C+R"
COLUMNS = [
    {"block_id": "b1", "assessment": "Listen Actively", "criterion": "C1", "line_item_ids": [1]},
    {"block_id": "b1", "assessment": "Listen Actively", "criterion": "C2", "line_item_ids": [2]},
    {"block_id": "b2", "assessment": "Focus on Solutions", "criterion": "C3", "line_item_ids": [3]},
]


class _Users(list):
    """Minimal queryset: count and slicing."""

    def count(self):
        return len(self)

    def __getitem__(self, item):
        result = super().__getitem__(item)
        return _Users(result) if isinstance(item, slice) else result


def _user(i):
    return SimpleNamespace(id=i, username="u%02d" % i, email="u%02d@example.com" % i,
                           profile=SimpleNamespace(name="Learner %d" % i))


def _get(**params):
    request = RequestFactory().get("/data", params)
    request.user = SimpleNamespace(is_authenticated=True)
    response = views.auto_assessment_scores_data(request, COURSE_ID)
    return json.loads(response.content)


@pytest.fixture(autouse=True)
def _patch(monkeypatch, settings):
    settings.EDL_AUTO_ASSESSMENT_THRESHOLD = 75
    calls = {}
    users = _Users([_user(i) for i in range(1, 24)])  # 23 learners

    def learners_queryset(course_key, query=None):
        calls["q"] = query
        return users

    def get_cells(columns, page_users, threshold):
        calls["columns"] = columns
        calls["page_users"] = page_users
        return {u.id: [None] * len(columns) for u in page_users}

    monkeypatch.setattr(views, "get_course_with_access", lambda *a, **k: None)
    monkeypatch.setattr(views.data, "get_columns", lambda key: COLUMNS)
    monkeypatch.setattr(views.data, "learners_queryset", learners_queryset)
    monkeypatch.setattr(views.data, "get_cells", get_cells)
    return calls


def test_first_page_defaults():
    body = _get()
    assert (body["page"], body["page_size"], body["total"], body["num_pages"]) == (1, 10, 23, 3)
    assert len(body["learners"]) == 10
    assert body["learners"][0]["username"] == "u01"
    assert body["threshold"] == 75
    assert len(body["columns"]) == 3


def test_last_page_is_partial():
    body = _get(page=3)
    assert len(body["learners"]) == 3
    assert body["learners"][0]["username"] == "u21"


def test_page_past_end_is_clamped():
    assert _get(page=99)["page"] == 3


def test_page_size_capped_and_invalid_values_ignored():
    assert _get(page_size=1000)["page_size"] == 100
    assert _get(page_size="abc")["page_size"] == 10
    assert _get(page="abc")["page"] == 1
    assert _get(page=0)["page"] == 1


def test_assessment_filter_limits_columns_but_not_dropdown():
    body = _get(assessment="b2")
    assert [c["criterion"] for c in body["columns"]] == ["C3"]
    assert [a["id"] for a in body["assessments"]] == ["b1", "b2"]


def test_query_is_passed_through(_patch):
    _get(q="  ayesha ")
    assert _patch["q"] == "ayesha"


def test_cells_requested_only_for_page_users(_patch):
    _get(page=2, page_size=5)
    assert [u.id for u in _patch["page_users"]] == [6, 7, 8, 9, 10]


def test_non_staff_is_rejected(monkeypatch):
    def _deny(*args, **kwargs):
        raise Http404()
    monkeypatch.setattr(views, "get_course_with_access", _deny)
    with pytest.raises(Http404):
        _get()
