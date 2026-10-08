"""
Instructor-dashboard render filter step.

Adds an "Auto Assessments" tab to the legacy LMS instructor dashboard. Implemented
as an ``InstructorDashboardRenderStarted`` pipeline step so it needs no changes to
edx-platform: it appends a section with its own Mako template and attaches the
tab's JavaScript and CSS through a fragment, which the dashboard template emits.
"""

import logging
from importlib.resources import files

from django.conf import settings
from django.urls import reverse
from openedx_filters import PipelineStep
from web_fragments.fragment import Fragment

from .constants import (
    DEFAULT_THRESHOLD,
    SECTION_DISPLAY_NAME,
    SECTION_KEY,
    STAFF_ONLY_SECTION_KEY,
    TEMPLATE_PREFIX,
)

log = logging.getLogger(__name__)


def _read_static(name):
    """Return the text of a packaged static file."""
    return files("edl_plugin.auto_assessment_scores").joinpath("static", name).read_text(encoding="utf-8")


def _course_has_lti_blocks(course_key):
    """Return True if the course contains at least one ``lti_consumer`` block."""
    from xmodule.modulestore.django import modulestore  # pylint: disable=import-outside-toplevel
    return bool(modulestore().get_items(course_key, qualifiers={"category": "lti_consumer"}))


class AddAutoAssessmentsTab(PipelineStep):
    """Append the Auto Assessments section for users with course staff access."""

    def run_filter(self, context, template_name):  # pylint: disable=arguments-differ
        try:
            self._add(context)
        except Exception:  # pylint: disable=broad-except
            # Never let this break the instructor dashboard.
            log.exception("Failed to add the Auto Assessments tab")
        return {"context": context, "template_name": template_name}

    def _add(self, context):
        sections = context.get("sections")
        course = context.get("course")
        if not sections or course is None:
            return

        # The LMS only adds Course Info for users with course staff access, and
        # this filter step receives no request, so use it to gate the tab.
        staff_section = next((s for s in sections if s.get("section_key") == STAFF_ONLY_SECTION_KEY), None)
        if staff_section is None:
            return
        if any(s.get("section_key") == SECTION_KEY for s in sections):
            return

        # Like the Open Responses tab, only show the tab for courses that have the content.
        if not _course_has_lti_blocks(course.id):
            return

        # If the template cannot be found, adding the section would break the
        # whole dashboard. This raises instead, and run_filter skips the tab.
        from common.djangoapps.edxmako.paths import lookup_template  # pylint: disable=import-outside-toplevel
        lookup_template("main", TEMPLATE_PREFIX + SECTION_KEY + ".html")

        course_id = str(course.id)
        fragment = Fragment()
        fragment.add_css(_read_static("auto_assessments.css"))
        fragment.add_javascript(_read_static("auto_assessments.js"))

        sections.append({
            "section_key": SECTION_KEY,
            "section_display_name": SECTION_DISPLAY_NAME,
            "template_path_prefix": TEMPLATE_PREFIX,
            "access": staff_section.get("access", {}),
            "course_id": course_id,
            "threshold": getattr(settings, "EDL_AUTO_ASSESSMENT_THRESHOLD", DEFAULT_THRESHOLD),
            "csv_url": reverse("edl_plugin:auto_assessment_scores_csv", kwargs={"course_id": course_id}),
            "data_url": reverse("edl_plugin:auto_assessment_scores_data", kwargs={"course_id": course_id}),
            "fragment": fragment,
        })
