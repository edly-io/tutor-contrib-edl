"""Tests for the paged JSON endpoint with data and access checks monkeypatched."""

import json
from datetime import datetime
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
    {
        "competency": "Course Title", "block_id": "b1", "assessment": "Listen Actively",
        "criterion": "C1", "line_item_ids": [1],
    },
    {
        "competency": "Course Title", "block_id": "b1", "assessment": "Listen Actively",
        "criterion": "C2", "line_item_ids": [2],
    },
    {
        "competency": "Course Title", "block_id": "b2", "assessment": "Focus on Solutions",
        "criterion": "C3", "line_item_ids": [3],
    },
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


def _request_for_data():
    request = RequestFactory().get("/data")
    request.user = SimpleNamespace(is_authenticated=True)
    return request


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
        dates = {u.id: {"b1": datetime(2026, 10, 14, 23, 30)} for u in page_users if u.id % 2}
        dates.update({u.id: {} for u in page_users if not u.id % 2})
        return {u.id: [None] * len(columns) for u in page_users}, dates

    monkeypatch.setattr(views, "get_course_with_access", lambda *a, **k: None)
    monkeypatch.setattr(views.data, "get_columns", lambda key: COLUMNS)
    monkeypatch.setattr(views.data, "learners_queryset", learners_queryset)
    monkeypatch.setattr(views.data, "get_cells", get_cells)

    def get_attempt_counts(columns, key):
        calls["count_columns"] = columns
        return {"b1": 2, "b2": 0}, len(users)

    monkeypatch.setattr(views.data, "get_attempt_counts", get_attempt_counts)
    return calls


def test_first_page_defaults():
    body = _get()
    assert (body["page"], body["page_size"], body["total"], body["num_pages"]) == (1, 10, 23, 3)
    assert len(body["learners"]) == 10
    assert body["learners"][0]["username"] == "u01"
    assert body["threshold"] == 75
    assert len(body["columns"]) == 3


def test_learners_carry_dates_for_attempted_blocks_only():
    learners = _get()["learners"]
    assert learners[0]["dates"] == {"b1": {"date": "Oct 14, 2026", "note": ""}}   # u01 attempted b1
    assert learners[1]["dates"] == {}                                           # u02 attempted nothing


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


def test_assessments_carry_attempted_and_total():
    assessments = _get()["assessments"]
    assert assessments == [
        {"id": "b1", "name": "Listen Actively", "attempted": 2, "total": 23},
        {"id": "b2", "name": "Focus on Solutions", "attempted": 0, "total": 23},
    ]


def test_total_counts_all_enrolled_not_the_page_size():
    body = _get(page_size=5)
    assert len(body["learners"]) == 5
    assert {a["total"] for a in body["assessments"]} == {23}


def test_counts_ignore_search_and_assessment_filters(_patch):
    body = _get(q="u01", assessment="b2")
    assert [c["block_id"] for c in _patch["count_columns"]] == ["b1", "b1", "b2"]
    assert [(a["id"], a["attempted"], a["total"]) for a in body["assessments"]] == [("b1", 2, 23), ("b2", 0, 23)]


def test_block_missing_from_the_counts_shows_zero_attempted(monkeypatch):
    monkeypatch.setattr(views.data, "get_attempt_counts", lambda columns, key: ({}, 7))
    assert [(a["attempted"], a["total"]) for a in _get()["assessments"]] == [(0, 7), (0, 7)]


def test_no_columns_gives_no_assessments(monkeypatch):
    monkeypatch.setattr(views.data, "get_columns", lambda key: [])
    monkeypatch.setattr(views.data, "get_attempt_counts", lambda columns, key: ({}, 23))
    body = _get()
    assert body["assessments"] == [] and body["columns"] == []


def test_unknown_assessment_id_gives_no_columns_but_full_dropdown():
    body = _get(assessment="nope")
    assert body["columns"] == []
    assert len(body["assessments"]) == 2
    assert len(body["learners"]) == 10


def test_unauthenticated_user_is_redirected_to_login():
    request = RequestFactory().get("/data")
    request.user = SimpleNamespace(is_authenticated=False)
    response = views.auto_assessment_scores_data(request, COURSE_ID)
    assert response.status_code == 302


def test_invalid_course_id_is_404():
    with pytest.raises(Http404):
        views.auto_assessment_scores_data(_request_for_data(), "not-a-course-id")
