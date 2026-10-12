"""
Plugin settings.

Does two things, both idempotent because ``plugin_settings`` runs once per
settings type:

* wires the ``AddAutoAssessmentsTab`` step into the instructor-dashboard render
  filter without clobbering pipeline steps other plugins registered for it;
* makes the plugin's Mako template directory findable by the dashboard.
"""

import os

INSTRUCTOR_DASHBOARD_RENDER_FILTER = "org.openedx.learning.instructor.dashboard.render.started.v1"
PIPELINE_STEP = "edl_plugin.auto_assessment_scores.pipeline.AddAutoAssessmentsTab"

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")


def _add_mako_dir(settings):
    """
    Add the plugin's template directory to the LMS Mako settings.

    The dashboard includes ``${template_path_prefix}${section_key}.html`` through
    the Mako lookup named ``main``, which is built from the Mako backend's
    ``DIRS``. In ``lms/envs/production.py`` those DIRS are derived before plugin
    settings run, so ``MAKO_TEMPLATE_DIRS_BASE`` alone is not enough: append to
    both lists, in place.
    """
    base = getattr(settings, "MAKO_TEMPLATE_DIRS_BASE", None)
    if isinstance(base, list) and TEMPLATE_DIR not in [str(d) for d in base]:
        base.append(TEMPLATE_DIR)

    for backend in getattr(settings, "TEMPLATES", []):
        if "edxmako" not in backend.get("BACKEND", ""):
            continue
        dirs = backend.get("DIRS")
        if isinstance(dirs, list) and TEMPLATE_DIR not in [str(d) for d in dirs]:
            dirs.append(TEMPLATE_DIR)


def plugin_settings(settings):
    """Register the render-filter pipeline step and template dir (idempotent, merge-safe)."""
    filters_config = dict(getattr(settings, "OPEN_EDX_FILTERS_CONFIG", {}) or {})
    existing = dict(filters_config.get(INSTRUCTOR_DASHBOARD_RENDER_FILTER, {}))

    pipeline = list(existing.get("pipeline", []))
    if PIPELINE_STEP not in pipeline:
        pipeline.append(PIPELINE_STEP)

    filters_config[INSTRUCTOR_DASHBOARD_RENDER_FILTER] = {
        "fail_silently": existing.get("fail_silently", True),
        "pipeline": pipeline,
    }
    settings.OPEN_EDX_FILTERS_CONFIG = filters_config

    _add_mako_dir(settings)

    # Percent at or above which a criterion counts as Demonstrated.
    settings.EDL_AUTO_ASSESSMENT_THRESHOLD = getattr(settings, "EDL_AUTO_ASSESSMENT_THRESHOLD", 75)

    # Line item labels left out of the report. "grade" is the overall line item
    # some launch paths add next to the per-criterion ones, and would show up as
    # an extra column. Compared case-insensitively against the whole label.
    settings.EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS = getattr(
        settings, "EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS", ["grade"]
    )
