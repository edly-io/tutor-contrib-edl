"""
Views for the auto assessment scores report.

Access is restricted to course staff, same as the ORA criterion scores plugin.
"""

import csv
from datetime import date

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.utils.text import slugify
from django.views.decorators.cache import cache_control
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from lms.djangoapps.courseware.courses import get_course_with_access

from . import data
from . import report


def _course_key_for_staff(request, course_id):
    """Return the course key, or raise 404 / permission errors for non-staff."""
    try:
        course_key = CourseKey.from_string(course_id)
    except InvalidKeyError as error:
        raise Http404() from error

    # Raises for users without staff-level access to the course.
    get_course_with_access(request.user, "staff", course_key, depth=None)
    return course_key


@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def auto_assessment_scores_csv(request, course_id):
    """Return every auto assessment criterion score for the course as a CSV download."""
    course_key = _course_key_for_staff(request, course_id)
    report_data = data.build_report(course_key, settings.EDL_AUTO_ASSESSMENT_THRESHOLD)

    response = HttpResponse(content_type="text/csv")
    filename = "auto_assessment_scores_{}_{}.csv".format(slugify(str(course_key)), date.today().isoformat())
    response["Content-Disposition"] = 'attachment; filename="{}"'.format(filename)

    writer = csv.writer(response)
    for row in report.build_rows(report_data):
        writer.writerow(row)
    return response
