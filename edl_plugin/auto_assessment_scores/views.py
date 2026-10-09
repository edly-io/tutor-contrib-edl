"""
Views for the auto assessment scores report.

Access is restricted to course staff, same as the ORA criterion scores plugin.
"""

import csv
from datetime import date

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
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

    # Raises for users without staff-level access to the course. No children are
    # loaded here because get_columns loads the full course tree itself.
    get_course_with_access(request.user, "staff", course_key)
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


DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


def _int_param(request, name, default, minimum=1, maximum=None):
    """Return an integer query param, clamped to ``[minimum, maximum]``, or ``default`` if invalid."""
    try:
        value = int(request.GET.get(name, default))
    except (TypeError, ValueError):
        return default
    value = max(value, minimum)
    return min(value, maximum) if maximum else value


@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def auto_assessment_scores_data(request, course_id):
    """
    Return one page of learners and their scores as JSON.

    Query params: ``page`` (default 1), ``page_size`` (default 10, max 100),
    ``q`` (name, username or email) and ``assessment`` (a block id, limits the columns).
    """
    course_key = _course_key_for_staff(request, course_id)
    threshold = settings.EDL_AUTO_ASSESSMENT_THRESHOLD

    page_size = _int_param(request, "page_size", DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE)
    page = _int_param(request, "page", 1)
    query = request.GET.get("q", "").strip()
    assessment = request.GET.get("assessment", "").strip()

    all_columns = data.get_columns(course_key)
    assessments = []
    for column in all_columns:
        if column["block_id"] not in [a["id"] for a in assessments]:
            assessments.append({"id": column["block_id"], "name": column["assessment"]})
    columns = [c for c in all_columns if c["block_id"] == assessment] if assessment else all_columns

    learners = data.learners_queryset(course_key, query)
    total = learners.count()
    num_pages = max(1, -(-total // page_size))
    page = min(page, num_pages)
    page_users = list(learners[(page - 1) * page_size:page * page_size])
    cells = data.get_cells(columns, page_users, threshold)

    return JsonResponse({
        "assessments": assessments,
        "columns": [
            {"block_id": c["block_id"], "assessment": c["assessment"], "criterion": c["criterion"]}
            for c in columns
        ],
        "learners": [data.learner_row(user, cells[user.id]) for user in page_users],
        "page": page,
        "page_size": page_size,
        "total": total,
        "num_pages": num_pages,
        "threshold": threshold,
    })
