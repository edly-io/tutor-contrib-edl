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
    course = _block("course", "course", children=[
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
    cells = data.get_cells(COLUMNS, _users(1, 2, 3), 75)

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
    assert data.get_cells(COLUMNS, _users(1), 75)[1] == [None, None]


def test_get_cells_matches_external_id_without_hyphens(monkeypatch):
    ext = uuid.uuid4()
    _install(
        monkeypatch,
        external_ids=[SimpleNamespace(user_id=1, external_user_id=ext)],
        scores=[_score(10, ext.hex, 80, 100)],
    )
    assert data.get_cells(COLUMNS, _users(1), 75)[1][0] == {"percent": 80, "status": "demonstrated"}


def test_get_cells_no_columns_or_users(monkeypatch):
    _install(monkeypatch)
    assert data.get_cells([], _users(1), 75) == {1: []}
    assert data.get_cells(COLUMNS, [], 75) == {}


def test_learner_row_name_fallback():
    with_name = SimpleNamespace(username="u", email="e@x.com", profile=SimpleNamespace(name="Full Name"))
    no_name = SimpleNamespace(username="u2", email="e2@x.com", profile=SimpleNamespace(name=""))
    no_profile = SimpleNamespace(username="u3", email="e3@x.com")
    assert data.learner_row(with_name, [])["name"] == "Full Name"
    assert data.learner_row(no_name, [])["name"] == "u2"
    assert data.learner_row(no_profile, [])["name"] == "u3"


@pytest.mark.parametrize("value", [uuid.uuid4(), "not-a-uuid"])
def test_norm_is_stable(value):
    assert data._norm(value) == data._norm(data._norm(value))  # pylint: disable=protected-access
