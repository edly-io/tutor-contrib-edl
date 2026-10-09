"""
Data assembly for the auto assessment scores report.

Reads the per-criterion scores Muzzy Lane posted over LTI 1.3 AGS. Each
criterion is one ``LtiAgsLineItem`` of the block's ``LtiConfiguration``, and each
learner's score for it is an ``LtiAgsScore``. Everything is read through
queries, never through the (single, overwritten) block grade.
"""

import uuid

from django.conf import settings
from django.contrib.auth.models import User  # pylint: disable=imported-auth-user
from django.db.models import Q

from . import report


def _norm(value):
    """Normalise an external user id so UUID strings with or without hyphens match."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return str(value)


def _lti_blocks_in_outline_order(course):
    """Return the course's ``lti_consumer`` blocks in outline order (depth first)."""
    blocks = []

    def walk(block):
        if block.category == "lti_consumer":
            blocks.append(block)
        for child in block.get_children():
            walk(child)

    walk(course)
    return blocks


def _excluded_labels():
    """Return the lower-cased labels to leave out, from ``EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS``."""
    labels = getattr(settings, "EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS", ["grade"])
    return {str(label).strip().lower() for label in labels}


def get_columns(course_key):
    """
    Return one column per distinct criterion label of each Muzzy Lane block.

    Blocks are kept only if their ``LtiConfiguration`` has AGS line items.
    Line items whose label is in ``EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS`` are
    ignored, and a block left with none is skipped.
    Line items of one block that share a label share a column. Columns are in
    outline order, then by the smallest line item id of the label.

    Returns ``[{"block_id", "assessment", "criterion", "line_item_ids"}]``.
    """
    # Imported here so the module loads (and unit tests run) outside edx-platform.
    from lti_consumer.models import LtiAgsLineItem, LtiConfiguration  # pylint: disable=import-outside-toplevel
    from xmodule.modulestore.django import modulestore  # pylint: disable=import-outside-toplevel

    course = modulestore().get_course(course_key, depth=None)
    if course is None:
        return []

    blocks = _lti_blocks_in_outline_order(course)
    if not blocks:
        return []

    config_id_by_location = {
        str(cfg.location): cfg.id
        for cfg in LtiConfiguration.objects.filter(location__in=[b.location for b in blocks])
    }
    line_items = LtiAgsLineItem.objects.filter(
        lti_configuration_id__in=list(config_id_by_location.values())
    ).order_by("id")

    excluded = _excluded_labels()
    items_by_config = {}
    for item in line_items:
        if item.label.strip().lower() in excluded:
            continue
        items_by_config.setdefault(item.lti_configuration_id, []).append(item)

    columns = []
    for block in blocks:
        items = items_by_config.get(config_id_by_location.get(str(block.location)), [])
        by_label = {}
        for item in items:  # already ordered by id, so dict order is smallest id first
            by_label.setdefault(item.label, []).append(item.id)
        for label, ids in by_label.items():
            columns.append({
                "block_id": str(block.location),
                "assessment": block.display_name or "",
                "criterion": label,
                "line_item_ids": ids,
            })
    return columns


def learners_queryset(course_key, query=None):
    """Return active enrollees ordered by username, optionally filtered by name, username or email."""
    users = User.objects.filter(
        courseenrollment__course_id=course_key,
        courseenrollment__is_active=True,
    )
    if query:
        users = users.filter(
            Q(username__icontains=query) | Q(email__icontains=query) | Q(profile__name__icontains=query)
        )
    return users.order_by("username").select_related("profile").distinct()


def get_cells(columns, users, threshold):
    """
    Return ``{user.id: [cell | None, ...]}`` with one cell per column.

    Only fully graded scores with a usable maximum count. When several line
    items share a column label, the score with the latest timestamp wins.
    """
    from lti_consumer.models import LtiAgsScore  # pylint: disable=import-outside-toplevel
    from openedx.core.djangoapps.external_user_ids.models import ExternalId  # pylint: disable=import-outside-toplevel

    users = list(users)
    empty = {user.id: [None] * len(columns) for user in users}
    if not columns or not users:
        return empty

    user_by_external = {}
    for user_id, external_user_id in ExternalId.objects.filter(
        external_id_type__name="lti", user__in=users
    ).values_list("user_id", "external_user_id"):
        user_by_external[_norm(external_user_id)] = user_id
    if not user_by_external:
        return empty

    line_item_ids = [i for column in columns for i in column["line_item_ids"]]
    scores = LtiAgsScore.objects.filter(
        line_item_id__in=line_item_ids,
        grading_progress=LtiAgsScore.FULLY_GRADED,
        score_given__isnull=False,
    )

    # Narrow the query to the requested learners. LtiAgsScore.user_id is the
    # external id as stored by the tool, so match on both common spellings.
    wanted = set()
    for external in user_by_external:
        wanted.add(external)
        wanted.add(external.replace("-", ""))
    scores = scores.filter(user_id__in=wanted)

    # Plain tuples instead of model instances keep memory low on large courses.
    latest = {}
    for external_id, line_item_id, given, maximum, timestamp in scores.values_list(
        "user_id", "line_item_id", "score_given", "score_maximum", "timestamp"
    ):
        user_id = user_by_external.get(_norm(external_id))
        if user_id is None:
            continue
        key = (user_id, line_item_id)
        if key not in latest or timestamp > latest[key][2]:
            latest[key] = (given, maximum, timestamp)

    cells = empty
    for index, column in enumerate(columns):
        for user in users:
            candidates = [latest[(user.id, i)] for i in column["line_item_ids"] if (user.id, i) in latest]
            if not candidates:
                continue
            given, maximum, _ = max(candidates, key=lambda s: s[2])
            cells[user.id][index] = report.make_cell(given, maximum, threshold)
    return cells


def learner_row(user, cells):
    """Return the report row for ``user``."""
    profile = getattr(user, "profile", None)
    name = profile.name if profile is not None and profile.name else user.username
    return {"name": name, "username": user.username, "email": user.email, "cells": cells}


def build_report(course_key, threshold):
    """Return ``{"columns": [...], "learners": [...]}`` for every active enrollee."""
    columns = get_columns(course_key)
    users = list(learners_queryset(course_key))
    cells = get_cells(columns, users, threshold)
    return {
        "columns": columns,
        "learners": [learner_row(user, cells[user.id]) for user in users],
    }
