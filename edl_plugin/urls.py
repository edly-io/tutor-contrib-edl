"""URL routing for the auto assessment scores report (mounted at the site root)."""

from django.urls import re_path

from openedx.core.constants import COURSE_ID_PATTERN

from edl_plugin.auto_assessment_scores import views

app_name = "edl_plugin"

urlpatterns = [
    re_path(
        r"^courses/{course_id}/instructor/auto_assessments/csv$".format(course_id=COURSE_ID_PATTERN),
        views.auto_assessment_scores_csv,
        name="auto_assessment_scores_csv",
    ),
    re_path(
        r"^courses/{course_id}/instructor/auto_assessments/data$".format(course_id=COURSE_ID_PATTERN),
        views.auto_assessment_scores_data,
        name="auto_assessment_scores_data",
    ),
]
