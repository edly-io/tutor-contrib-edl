"""
Tests for the instructor-dashboard render-filter step.

The step's dependencies (``reverse``, the Mako lookup, the static reader) are
monkeypatched, so no LMS or database is needed.
"""

import sys

import pytest

pipeline = pytest.importorskip(
    "edl_plugin.auto_assessment_scores.pipeline",
    reason="requires Django, openedx-filters and web-fragments",
)


class _Course:
    id = "course-v1:Org+C+R"


def _run(context):
    step = pipeline.AddAutoAssessmentsTab(
        filter_type="org.openedx.learning.instructor.dashboard.render.started.v1",
        running_pipeline=[],
    )
    return step.run_filter(context=context, template_name="tpl.html")


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(pipeline, "reverse", lambda name, kwargs=None: "/csv/" + kwargs["course_id"])
    monkeypatch.setattr(pipeline, "_read_static", lambda name: "/* {} */".format(name))


def _staff_context():
    return {"course": _Course(), "sections": [{"section_key": "course_info", "access": {"staff": True}}]}


def test_adds_section_for_staff():
    context = _staff_context()
    result = _run(context)

    assert result["template_name"] == "tpl.html"
    keys = [s["section_key"] for s in context["sections"]]
    assert keys == ["course_info", "auto_assessments"]
    section = context["sections"][-1]
    assert section["section_display_name"] == "Auto Assessments"
    assert section["template_path_prefix"] == "/edl_plugin/"
    assert section["csv_url"] == "/csv/course-v1:Org+C+R"
    assert section["access"] == {"staff": True}
    assert "auto_assessments.js" in section["fragment"].foot_html()


def test_not_added_without_course_info_section():
    context = {"course": _Course(), "sections": [{"section_key": "data_download"}]}
    _run(context)
    assert [s["section_key"] for s in context["sections"]] == ["data_download"]


def test_not_added_twice():
    context = _staff_context()
    _run(context)
    _run(context)
    assert [s["section_key"] for s in context["sections"]].count("auto_assessments") == 1


def test_noop_without_course():
    context = {"sections": [{"section_key": "course_info"}]}
    result = _run(context)
    assert result["context"] is context
    assert len(context["sections"]) == 1


def test_never_raises_when_template_missing(monkeypatch):
    def _missing(namespace, name):
        raise RuntimeError("template not found")
    monkeypatch.setattr(sys.modules["common.djangoapps.edxmako.paths"], "lookup_template", _missing)

    context = _staff_context()
    result = _run(context)  # must not raise
    assert result["context"] is context
    assert len(context["sections"]) == 1


def test_never_raises_when_reverse_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("no url")
    monkeypatch.setattr(pipeline, "reverse", _boom)

    context = _staff_context()
    _run(context)  # must not raise
    assert len(context["sections"]) == 1
