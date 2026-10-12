"""Tests for the plugin settings hook."""

import types

from edl_plugin.settings import common

STEP = common.PIPELINE_STEP
FILTER = common.INSTRUCTOR_DASHBOARD_RENDER_FILTER


def _settings(**extra):
    return types.SimpleNamespace(**extra)


def test_registers_pipeline_step_idempotently():
    settings = _settings()
    common.plugin_settings(settings)
    common.plugin_settings(settings)
    assert settings.OPEN_EDX_FILTERS_CONFIG[FILTER]["pipeline"] == [STEP]
    assert settings.OPEN_EDX_FILTERS_CONFIG[FILTER]["fail_silently"] is True


def test_keeps_other_pipeline_steps():
    settings = _settings(OPEN_EDX_FILTERS_CONFIG={FILTER: {"fail_silently": False, "pipeline": ["other.Step"]}})
    common.plugin_settings(settings)
    assert settings.OPEN_EDX_FILTERS_CONFIG[FILTER]["pipeline"] == ["other.Step", STEP]
    assert settings.OPEN_EDX_FILTERS_CONFIG[FILTER]["fail_silently"] is False


def test_adds_template_dir_to_both_mako_lists_once():
    base = ["/a"]
    mako_dirs = ["/a"]
    settings = _settings(
        MAKO_TEMPLATE_DIRS_BASE=base,
        TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": []},
                   {"BACKEND": "common.djangoapps.edxmako.backend.Mako", "DIRS": mako_dirs}],
    )
    common.plugin_settings(settings)
    common.plugin_settings(settings)
    assert base.count(common.TEMPLATE_DIR) == 1
    assert mako_dirs.count(common.TEMPLATE_DIR) == 1
    assert settings.TEMPLATES[0]["DIRS"] == []


def test_threshold_default_and_override():
    settings = _settings()
    common.plugin_settings(settings)
    assert settings.EDL_AUTO_ASSESSMENT_THRESHOLD == 75

    settings = _settings(EDL_AUTO_ASSESSMENT_THRESHOLD=80)
    common.plugin_settings(settings)
    assert settings.EDL_AUTO_ASSESSMENT_THRESHOLD == 80


def test_excluded_labels_default_and_override():
    settings = _settings()
    common.plugin_settings(settings)
    assert settings.EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS == ["grade"]

    settings = _settings(EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS=["grade", "total"])
    common.plugin_settings(settings)
    assert settings.EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS == ["grade", "total"]
