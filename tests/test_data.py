"""
Tests for the data layer with fake platform models.

``get_columns`` and ``get_cells`` import ``lti_consumer``, ``xmodule`` and the
external-id model lazily, so each test injects small fakes into ``sys.modules``.
"""

import sys
import types
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from edl_plugin.auto_assessment_scores import data

BASE = datetime(2026, 1, 1)


class _Rows(list):
    """A list that understands the few queryset calls the data layer makes."""

    def filter(self, **kwargs):
        rows = list(self)
        for key, value in kwargs.items():
            if key.endswith("__in"):
                field = key[:-4]
                allowed = list(value)
                rows = [r for r in rows if getattr(r, field) in allowed]
            elif key.endswith("__isnull"):
                field = key[:-8]
                rows = [r for r in rows if (getattr(r, field) is None) == value]
            else:
                rows = [r for r in rows if getattr(r, key) == value]
        return _Rows(rows)

    def order_by(self, *fields):
        return _Rows(sorted(self, key=lambda r: getattr(r, fields[0])))

    def values_list(self, *fields):
        return [tuple(getattr(r, f) for f in fields) for r in self]


class _Manager:
    def __init__(self, rows):
        self._rows = _Rows(rows)

    def filter(self, **kwargs):
        return self._rows.filter(**kwargs)


def _install(monkeypatch, line_items=(), configs=(), scores=(), external_ids=(), blocks=()):
    lti = types.ModuleType("lti_consumer.models")

    class LtiConfiguration:
        objects = _Manager(configs)

    class LtiAgsLineItem:
        objects = _Manager(line_items)

    class LtiAgsScore:
        FULLY_GRADED = "FullyGraded"
        objects = _Manager(scores)

    lti.LtiConfiguration, lti.LtiAgsLineItem, lti.LtiAgsScore = LtiConfiguration, LtiAgsLineItem, LtiAgsScore

    class _ExternalRows(_Rows):
        def filter(self, **kwargs):
            kwargs.pop("external_id_type__name", None)
            users = kwargs.pop("user__in", None)
            rows = _Rows(self).filter(**kwargs)
            if users is not None:
                ids = [u.id for u in users]
                rows = [r for r in rows if r.user_id in ids]
            return _ExternalRows(rows)

        def values_list(self, *fields):
            return [tuple(getattr(r, f) for f in fields) for r in self]

    ext = types.ModuleType("openedx.core.djangoapps.external_user_ids.models")

    class ExternalId:
        objects = SimpleNamespace(filter=lambda **kw: _ExternalRows(external_ids).filter(**kw))

    ext.ExternalId = ExternalId

    store = types.ModuleType("xmodule.modulestore.django")
    store.modulestore = lambda: SimpleNamespace(get_course=lambda key, depth=None: blocks)

    for name, module in (
        ("lti_consumer", types.ModuleType("lti_consumer")),
        ("lti_consumer.models", lti),
        ("openedx.core.djangoapps", types.ModuleType("openedx.core.djangoapps")),
        ("openedx.core.djangoapps.external_user_ids", types.ModuleType("openedx.core.djangoapps.external_user_ids")),
        ("openedx.core.djangoapps.external_user_ids.models", ext),
        ("xmodule", types.ModuleType("xmodule")),
        ("xmodule.modulestore", types.ModuleType("xmodule.modulestore")),
        ("xmodule.modulestore.django", store),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return LtiAgsScore


def _block(category, location, name="", children=()):
    return SimpleNamespace(
        category=category, location=location, display_name=name, get_children=lambda: list(children),
    )


def _item(item_id, config_id, label):
    return SimpleNamespace(id=item_id, lti_configuration_id=config_id, label=label)


def _score(item_id, external_id, given, maximum, minutes=0, progress="FullyGraded"):
    return SimpleNamespace(
        line_item_id=item_id, user_id=str(external_id), score_given=given, score_maximum=maximum,
        grading_progress=progress, timestamp=BASE + timedelta(minutes=minutes),
    )


def test_get_columns_outline_order_and_label_grouping(monkeypatch):
    listen = _block("lti_consumer", "loc-listen", "Listen Actively")
    other = _block("lti_consumer", "loc-other", "Not Muzzy Lane")
    focus = _block("lti_consumer", "loc-focus", "Focus on Solutions")
    course = _block("course", "course", "Course Title", children=[
        _block("chapter", "ch", children=[_block("vertical", "v", children=[focus, other, listen])]),
    ])
    _install(
        monkeypatch,
        blocks=course,
        configs=[
            SimpleNamespace(id=1, location="loc-listen"),
            SimpleNamespace(id=2, location="loc-other"),
            SimpleNamespace(id=3, location="loc-focus"),
        ],
        line_items=[
            _item(10, 1, "Asks clarifying questions"),
            _item(11, 1, "Paraphrases"),
            _item(12, 1, "Asks clarifying questions"),  # same label again (reattempt)
            _item(30, 3, "Identify steps"),
        ],
    )
    # location__in is a field the fake treats as an attribute list, so patch the filter.
    monkeypatch.setattr(
        sys.modules["lti_consumer.models"].LtiConfiguration.objects, "filter",
        lambda **kw: _Rows([
            SimpleNamespace(id=1, location="loc-listen"),
            SimpleNamespace(id=2, location="loc-other"),
            SimpleNamespace(id=3, location="loc-focus"),
        ]),
    )

    columns = data.get_columns("course-key")

    # Outline order: focus first (it comes first in the tree), then listen. "other" has no line items.
    assert [(c["assessment"], c["criterion"]) for c in columns] == [
        ("Focus on Solutions", "Identify steps"),
        ("Listen Actively", "Asks clarifying questions"),
        ("Listen Actively", "Paraphrases"),
    ]
    assert columns[1]["line_item_ids"] == [10, 12]
    assert columns[0]["block_id"] == "loc-focus"
    # The course title is the competency of every column.
    assert {c["competency"] for c in columns} == {"Course Title"}


def test_get_columns_excludes_grade_label_by_default(monkeypatch, settings):
    settings.EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS = ["grade"]
    block = _block("lti_consumer", "loc-a", "Listen Actively")
    only_grade = _block("lti_consumer", "loc-b", "Only Grade")
    course = _block("course", "course", children=[block, only_grade])
    cfgs = _Rows([SimpleNamespace(id=1, location="loc-a"), SimpleNamespace(id=2, location="loc-b")])
    _install(
        monkeypatch,
        blocks=course,
        line_items=[_item(1, 1, "Asks clarifying questions"), _item(2, 1, "Grade "), _item(3, 1, "grade"),
                    _item(4, 2, "grade")],
    )
    monkeypatch.setattr(sys.modules["lti_consumer.models"].LtiConfiguration.objects, "filter", lambda **kw: cfgs)

    columns = data.get_columns("course-key")

    assert [(c["assessment"], c["criterion"]) for c in columns] == [("Listen Actively", "Asks clarifying questions")]


def test_get_columns_exclusion_list_is_configurable(monkeypatch, settings):
    settings.EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS = []
    block = _block("lti_consumer", "loc-a", "Listen Actively")
    course = _block("course", "course", children=[block])
    cfgs = _Rows([SimpleNamespace(id=1, location="loc-a")])
    _install(monkeypatch, blocks=course, line_items=[_item(1, 1, "Asks"), _item(2, 1, "grade")])
    monkeypatch.setattr(sys.modules["lti_consumer.models"].LtiConfiguration.objects, "filter", lambda **kw: cfgs)

    assert [c["criterion"] for c in data.get_columns("course-key")] == ["Asks", "grade"]


def test_get_columns_no_course_or_no_blocks(monkeypatch):
    _install(monkeypatch, blocks=None)
    assert data.get_columns("k") == []
    _install(monkeypatch, blocks=_block("course", "c"))
    assert data.get_columns("k") == []


def _users(*ids):
    return [SimpleNamespace(id=i) for i in ids]


COLUMNS = [
    {"block_id": "b", "assessment": "A", "criterion": "C1", "line_item_ids": [10, 12]},
    {"block_id": "b", "assessment": "A", "criterion": "C2", "line_item_ids": [11]},
]


def test_get_cells_scores_status_and_blanks(monkeypatch):
    ext1, ext2 = uuid.uuid4(), uuid.uuid4()
    _install(
        monkeypatch,
        external_ids=[
            SimpleNamespace(user_id=1, external_user_id=ext1),
            SimpleNamespace(user_id=2, external_user_id=ext2),
        ],
        scores=[
            _score(10, ext1, 87, 100),
            _score(11, ext1, 53, 100),
            _score(11, ext2, 75, 100),
            _score(12, ext2, 10, 100, minutes=0),
            _score(10, ext2, 90, 100, minutes=5),   # later attempt for the same label wins
        ],
    )
    cells, _dates = data.get_cells(COLUMNS, _users(1, 2, 3), 75)

    assert cells[1] == [
        {"percent": 87, "status": "demonstrated"},
        {"percent": 53, "status": "not_demonstrated"},
    ]
    assert cells[2][0] == {"percent": 90, "status": "demonstrated"}
    assert cells[2][1] == {"percent": 75, "status": "demonstrated"}
    assert cells[3] == [None, None]   # no ExternalId


def test_get_cells_ignores_ungraded_and_bad_maximum(monkeypatch):
    ext = uuid.uuid4()
    _install(
        monkeypatch,
        external_ids=[SimpleNamespace(user_id=1, external_user_id=ext)],
        scores=[
            _score(10, ext, 80, 100, progress="Pending"),
            _score(11, ext, 5, 0),
        ],
    )
    cells, dates = data.get_cells(COLUMNS, _users(1), 75)
    assert cells[1] == [None, None]
    # The fully graded score with a zero maximum still shows the learner took the assessment.
    assert dates[1] == {"b": BASE}


def test_get_cells_matches_external_id_without_hyphens(monkeypatch):
    ext = uuid.uuid4()
    _install(
        monkeypatch,
        external_ids=[SimpleNamespace(user_id=1, external_user_id=ext)],
        scores=[_score(10, ext.hex, 80, 100)],
    )
    assert data.get_cells(COLUMNS, _users(1), 75)[0][1][0] == {"percent": 80, "status": "demonstrated"}


def test_get_cells_no_columns_or_users(monkeypatch):
    _install(monkeypatch)
    assert data.get_cells([], _users(1), 75) == ({1: []}, {1: {}})
    assert data.get_cells(COLUMNS, [], 75) == ({}, {})


def test_get_cells_without_external_ids_has_empty_dates(monkeypatch):
    _install(monkeypatch, scores=[_score(10, uuid.uuid4(), 80, 100)])
    cells, dates = data.get_cells(COLUMNS, _users(1, 2), 75)
    assert cells == {1: [None, None], 2: [None, None]}
    assert dates == {1: {}, 2: {}}


def test_get_cells_no_scores_has_empty_dates(monkeypatch):
    ext = uuid.uuid4()
    _install(monkeypatch, external_ids=[SimpleNamespace(user_id=1, external_user_id=ext)])
    cells, dates = data.get_cells(COLUMNS, _users(1), 75)
    assert cells[1] == [None, None]
    assert dates == {1: {}}


def test_get_cells_date_is_latest_score_of_the_block(monkeypatch):
    ext = uuid.uuid4()
    _install(
        monkeypatch,
        external_ids=[SimpleNamespace(user_id=1, external_user_id=ext)],
        scores=[
            _score(10, ext, 80, 100, minutes=0),
            _score(11, ext, 60, 100, minutes=7),   # the later of the block's two criteria
        ],
    )
    _cells, dates = data.get_cells(COLUMNS, _users(1), 75)
    assert dates[1] == {"b": BASE + timedelta(minutes=7)}


def test_get_cells_block_not_attempted_has_no_date_key(monkeypatch):
    ext = uuid.uuid4()
    columns = COLUMNS + [{"block_id": "b2", "assessment": "B", "criterion": "C3", "line_item_ids": [20]}]
    _install(
        monkeypatch,
        external_ids=[SimpleNamespace(user_id=1, external_user_id=ext)],
        scores=[_score(10, ext, 80, 100, minutes=3)],
    )
    cells, dates = data.get_cells(columns, _users(1), 75)
    assert cells[1][2] is None
    assert dates[1] == {"b": BASE + timedelta(minutes=3)}
    assert "b2" not in dates[1]


def test_get_cells_date_follows_the_winning_score_of_a_shared_label(monkeypatch):
    ext = uuid.uuid4()
    column = [{"block_id": "b", "assessment": "A", "criterion": "C1", "line_item_ids": [10, 12]}]
    _install(
        monkeypatch,
        external_ids=[SimpleNamespace(user_id=1, external_user_id=ext)],
        scores=[
            _score(10, ext, 40, 100, minutes=0),
            _score(12, ext, 90, 100, minutes=5),   # the retake wins the cell and the date
        ],
    )
    cells, dates = data.get_cells(column, _users(1), 75)
    assert cells[1] == [{"percent": 90, "status": "demonstrated"}]
    assert dates[1] == {"b": BASE + timedelta(minutes=5)}


def test_learner_row_name_fallback():
    with_name = SimpleNamespace(username="u", email="e@x.com", profile=SimpleNamespace(name="Full Name"))
    no_name = SimpleNamespace(username="u2", email="e2@x.com", profile=SimpleNamespace(name=""))
    no_profile = SimpleNamespace(username="u3", email="e3@x.com")
    assert data.learner_row(with_name, [])["name"] == "Full Name"
    assert data.learner_row(no_name, [])["name"] == "u2"
    assert data.learner_row(no_profile, [])["name"] == "u3"


def test_learner_row_formats_dates_as_entries():
    user = SimpleNamespace(username="u", email="e@x.com", profile=SimpleNamespace(name="N"))
    row = data.learner_row(user, [], {"b": datetime(2026, 10, 14, 9, 30)})
    assert row["dates"] == {"b": {"date": "Oct 14, 2026", "note": ""}}
    assert data.learner_row(user, [])["dates"] == {}


def test_learner_row_writes_dates_in_the_browser_zone():
    user = SimpleNamespace(username="u", email="u@x.com", profile=None)
    row = data.learner_row(user, [], {"b": datetime(2026, 10, 15, 3, 30)}, "Pacific/Honolulu")
    assert row["dates"] == {"b": {"date": "Oct 14, 2026", "note": ""}}


@pytest.mark.parametrize("value", [uuid.uuid4(), "not-a-uuid"])
def test_norm_is_stable(value):
    assert data._norm(value) == data._norm(data._norm(value))  # pylint: disable=protected-access


# --- filter_columns -------------------------------------------------------------------------

TWO_BLOCKS = [
    {"block_id": "b1", "assessment": "A", "criterion": "C1", "line_item_ids": [10]},
    {"block_id": "b1", "assessment": "A", "criterion": "C2", "line_item_ids": [11]},
    {"block_id": "b2", "assessment": "B", "criterion": "C3", "line_item_ids": [12]},
]


def test_filter_columns_empty_id_returns_all_columns():
    assert data.filter_columns(TWO_BLOCKS) == TWO_BLOCKS
    assert data.filter_columns(TWO_BLOCKS, "") == TWO_BLOCKS
    assert data.filter_columns(TWO_BLOCKS, None) == TWO_BLOCKS


def test_filter_columns_keeps_only_the_block():
    assert [c["criterion"] for c in data.filter_columns(TWO_BLOCKS, "b1")] == ["C1", "C2"]
    assert [c["criterion"] for c in data.filter_columns(TWO_BLOCKS, "b2")] == ["C3"]


def test_filter_columns_unknown_id_returns_none():
    assert data.filter_columns(TWO_BLOCKS, "nope") == []


# --- get_attempt_counts ---------------------------------------------------------------------

COURSE = "course-v1:Org+C+R"
UID_A, UID_B, UID_C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


class _Counted(list):
    def distinct(self):
        return _Counted(dict.fromkeys(self))


def _install_counts(monkeypatch, enrolled=(), external_ids=(), scores=(), total=None):
    """Install fakes for the three queries of ``get_attempt_counts`` and record their filters."""
    lti_score = _install(monkeypatch)
    calls = {"external": [], "scores": [], "queries": 0}
    enrolled = set(enrolled)

    def ext_filter(**kwargs):
        calls["external"].append(kwargs)
        calls["queries"] += 1
        rows = [r for r in external_ids if r.user_id in enrolled]
        return SimpleNamespace(values_list=lambda *f: [tuple(getattr(r, x) for x in f) for r in rows])

    sys.modules["openedx.core.djangoapps.external_user_ids.models"].ExternalId.objects = SimpleNamespace(
        filter=ext_filter
    )

    def score_filter(**kwargs):
        calls["scores"].append(kwargs)
        calls["queries"] += 1
        rows = _Rows(scores).filter(**kwargs)
        return SimpleNamespace(values_list=lambda *f: _Counted(rows.values_list(*f)))

    lti_score.objects = SimpleNamespace(filter=score_filter)

    count = len(enrolled) if total is None else total
    monkeypatch.setattr(data, "learners_queryset", lambda key, query=None: SimpleNamespace(count=lambda: count))
    return calls


def _ext(user_id, value):
    return SimpleNamespace(user_id=user_id, external_user_id=value)


def test_attempt_counts_none_attempted(monkeypatch):
    _install_counts(monkeypatch, enrolled=[1, 2], external_ids=[_ext(1, UID_A), _ext(2, UID_B)])
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 0, "b2": 0}, 2)


def test_attempt_counts_one_learner_with_two_criteria_counts_once(monkeypatch):
    _install_counts(
        monkeypatch, enrolled=[1, 2],
        external_ids=[_ext(1, UID_A), _ext(2, UID_B)],
        scores=[_score(10, UID_A, 80, 100), _score(11, UID_A, 90, 100), _score(12, UID_B, 50, 100)],
    )
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 1, "b2": 1}, 2)


def test_attempt_counts_two_learners_in_one_block(monkeypatch):
    _install_counts(
        monkeypatch, enrolled=[1, 2, 3],
        external_ids=[_ext(1, UID_A), _ext(2, UID_B), _ext(3, UID_C)],
        scores=[_score(10, UID_A, 1, 100), _score(11, UID_B, 1, 100)],
    )
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 2, "b2": 0}, 3)


def test_attempt_counts_ignore_scores_of_unenrolled_users(monkeypatch):
    _install_counts(
        monkeypatch, enrolled=[1],
        external_ids=[_ext(1, UID_A), _ext(2, UID_B)],  # user 2 is not enrolled
        scores=[_score(10, UID_A, 80, 100), _score(10, UID_B, 80, 100), _score(10, UID_C, 80, 100)],
    )
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 1, "b2": 0}, 1)


def test_attempt_counts_external_id_query_is_limited_to_active_enrollees_of_the_course(monkeypatch):
    calls = _install_counts(monkeypatch, enrolled=[1], external_ids=[_ext(1, UID_A)])
    data.get_attempt_counts(TWO_BLOCKS, COURSE)
    (kwargs,) = calls["external"]
    assert kwargs["user__courseenrollment__course_id"] == COURSE
    assert kwargs["user__courseenrollment__is_active"] is True
    assert kwargs["external_id_type__name"] == "lti"


def test_attempt_counts_score_query_is_limited_to_the_course_line_items(monkeypatch):
    calls = _install_counts(monkeypatch, enrolled=[1], external_ids=[_ext(1, UID_A)])
    data.get_attempt_counts(TWO_BLOCKS, COURSE)
    (kwargs,) = calls["scores"]
    assert sorted(kwargs["line_item_id__in"]) == [10, 11, 12]
    assert kwargs["grading_progress"] == "FullyGraded"
    assert kwargs["score_given__isnull"] is False


def test_attempt_counts_ignore_scores_of_other_line_items(monkeypatch):
    _install_counts(
        monkeypatch, enrolled=[1], external_ids=[_ext(1, UID_A)],
        scores=[_score(99, UID_A, 80, 100)],  # a line item of another course or an excluded label
    )
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 0, "b2": 0}, 1)


def test_attempt_counts_ignore_scores_not_fully_graded(monkeypatch):
    _install_counts(
        monkeypatch, enrolled=[1], external_ids=[_ext(1, UID_A)],
        scores=[_score(10, UID_A, 80, 100, progress="Pending")],
    )
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 0, "b2": 0}, 1)


def test_attempt_counts_ignore_scores_without_a_given_score(monkeypatch):
    _install_counts(
        monkeypatch, enrolled=[1], external_ids=[_ext(1, UID_A)],
        scores=[_score(10, UID_A, None, 100)],
    )
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 0, "b2": 0}, 1)


@pytest.mark.parametrize("score_id", [str(UID_A), UID_A.hex])
@pytest.mark.parametrize("external_value", [UID_A, str(UID_A), UID_A.hex])
def test_attempt_counts_match_external_ids_with_or_without_hyphens(monkeypatch, external_value, score_id):
    _install_counts(
        monkeypatch, enrolled=[1], external_ids=[_ext(1, external_value)],
        scores=[_score(10, score_id, 80, 100)],
    )
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 1, "b2": 0}, 1)


def test_attempt_counts_no_enrolled_learners_is_total_zero_and_runs_no_more_queries(monkeypatch):
    calls = _install_counts(monkeypatch, enrolled=[], scores=[_score(10, UID_A, 80, 100)])
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 0, "b2": 0}, 0)
    assert calls["queries"] == 0


def test_attempt_counts_no_columns_returns_empty_counts_with_total(monkeypatch):
    calls = _install_counts(monkeypatch, enrolled=[1, 2], external_ids=[_ext(1, UID_A)])
    assert data.get_attempt_counts([], COURSE) == ({}, 2)
    assert calls["queries"] == 0


def test_attempt_counts_enrolled_without_external_ids_skip_the_score_query(monkeypatch):
    calls = _install_counts(monkeypatch, enrolled=[1], external_ids=[], scores=[_score(10, UID_A, 80, 100)])
    assert data.get_attempt_counts(TWO_BLOCKS, COURSE) == ({"b1": 0, "b2": 0}, 1)
    assert calls["scores"] == []


def test_attempt_counts_ignore_the_learner_search_filter(monkeypatch):
    seen = []
    _install_counts(monkeypatch, enrolled=[1], external_ids=[_ext(1, UID_A)])
    monkeypatch.setattr(
        data, "learners_queryset", lambda key, query=None: seen.append(query) or SimpleNamespace(count=lambda: 1)
    )
    data.get_attempt_counts(TWO_BLOCKS, COURSE)
    assert seen == [None]


# --- build_report ---------------------------------------------------------------------------

@pytest.fixture(name="report_calls")
def _report_fixture(monkeypatch):
    calls = {}
    users = _users(1, 2)
    for u in users:
        u.username, u.email, u.profile = "u%d" % u.id, "u%d@x.com" % u.id, None

    monkeypatch.setattr(data, "get_columns", lambda key: TWO_BLOCKS)

    def learners(key, query=None):
        return users

    def cells(columns, page_users, threshold):
        calls["columns"] = columns
        return {u.id: [None] * len(columns) for u in page_users}, {u.id: {} for u in page_users}

    monkeypatch.setattr(data, "learners_queryset", learners)
    monkeypatch.setattr(data, "get_cells", cells)
    return calls


def test_build_report_without_filters_has_every_column_and_learner(report_calls):
    result = data.build_report(COURSE, 75)
    assert result["columns"] == TWO_BLOCKS
    assert [u["username"] for u in result["learners"]] == ["u1", "u2"]
