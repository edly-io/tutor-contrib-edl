"""Read and change Studio course creator access through platform APIs."""

import logging

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction

from .auth import service_username

log = logging.getLogger(__name__)
SALT = "edl-course-creator-snapshot"
ERRORS = {
    "user_not_found": (404, "User not found."),
    "organizations_required": (400, "Choose at least one organization."),
    "organizations_not_allowed": (400, "Organizations must be empty when org admin is off."),
    "invalid_restore": (
        400, "The previous state could not be restored: the snapshot is missing, expired or not valid."
    ),
    "user_inactive": (409, "This account is not active."),
    "user_is_global_staff": (409, "Global staff already have access to every course."),
    "global_creator_downgrade": (
        409, "This user can create course runs in every organization. Confirm the change to limit or remove that."
    ),
    "service_account_not_set_up": (503, "Service account is not set up."),
}


class CourseCreatorError(Exception):
    """A public API error with its HTTP status."""

    def __init__(self, code, organizations=None):
        self.code = code
        self.organizations = organizations
        if code == "unknown_organizations":
            self.status = 400
            self.message = f"These organizations do not exist: {', '.join(organizations)}."
        else:
            self.status, self.message = ERRORS[code]
        super().__init__(self.message)


def _user(username):
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        raise CourseCreatorError("user_not_found")
    return user


def _service_user():
    user = get_user_model().objects.filter(username=service_username()).first()
    if user is None or not user.is_staff or not user.is_active:
        raise CourseCreatorError("service_account_not_set_up")
    return user


def _org_objects(names):
    from organizations.models import Organization

    names = list(dict.fromkeys(names))
    objects = {obj.short_name: obj for obj in Organization.objects.filter(short_name__in=names)}
    missing = [name for name in names if name not in objects]
    if missing:
        raise CourseCreatorError("unknown_organizations", missing)
    return [objects[name] for name in names]


def _rows(user):
    from common.djangoapps.student.models import CourseAccessRole

    rows = CourseAccessRole.objects.filter(user=user, course_id=None)
    orgs = sorted(rows.filter(role="org_course_creator_group").values_list("org", flat=True))
    global_row = rows.filter(role="course_creator_group", org="").exists()
    return orgs, global_row


def _snapshot(user, record):
    return {
        "username": user.username,
        "state": record.state if record else None,
        "all_organizations": record.all_organizations if record else None,
        "organizations": sorted(record.organizations.values_list("short_name", flat=True)) if record else [],
    }


def get_state(username):
    """Return the current record, access rows and signed restore snapshot."""
    from cms.djangoapps.course_creators.models import CourseCreator

    user = _user(username)
    record = CourseCreator.objects.filter(user=user).first()
    snapshot = _snapshot(user, record)
    orgs, global_row = _rows(user)
    return {**snapshot, "org_creator_rows": orgs, "global_creator_row": global_row,
            "snapshot_token": signing.dumps(snapshot, salt=SALT)}


def _response(user, record, before, before_snapshot, before_global):
    after, after_global = _rows(user)
    snapshot = _snapshot(user, record)
    return {**snapshot, "granted_orgs": sorted(set(after) - set(before)),
            "removed_orgs": sorted(set(before) - set(after)),
            "changed": snapshot != before_snapshot or before != after or before_global != after_global}


def set_state(username, org_admin, organizations, acting_admin, confirm_downgrade=False):
    """Apply the requested creator state and repair organization roles."""
    from cms.djangoapps.course_creators.models import CourseCreator
    from cms.djangoapps.course_creators.views import update_org_content_creator_role

    caller = _service_user()
    user = _user(username)
    if not user.is_active:
        raise CourseCreatorError("user_inactive")
    if user.is_staff:
        raise CourseCreatorError("user_is_global_staff")
    if org_admin and not organizations:
        raise CourseCreatorError("organizations_required")
    if not org_admin and organizations:
        raise CourseCreatorError("organizations_not_allowed")
    org_objects = _org_objects(organizations)
    names = [org.short_name for org in org_objects]
    with transaction.atomic():
        record, _ = CourseCreator.objects.get_or_create(user=user)
        before_snapshot = _snapshot(user, record)
        before, before_global = _rows(user)
        if record.state == CourseCreator.GRANTED and record.all_organizations and not confirm_downgrade:
            raise CourseCreatorError("global_creator_downgrade")
        record.admin = caller
        if org_admin:
            record.state = CourseCreator.GRANTED
            record.all_organizations = False
            record.save()
            record.organizations.set(org_objects)
        else:
            if record.state == CourseCreator.GRANTED:
                record.state = CourseCreator.UNREQUESTED
                record.save()
            record.organizations.clear()
        update_org_content_creator_role(caller, user, names)
        response = _response(user, record, before, before_snapshot, before_global)
    log.info("EDL org admin: %s via %s set %s state=%s orgs=%s", acting_admin, caller.username,
             username, record.state, names)
    return response


def restore_state(username, restore_token, acting_admin):
    """Restore a previously signed snapshot."""
    from cms.djangoapps.course_creators.models import CourseCreator
    from cms.djangoapps.course_creators.views import update_org_content_creator_role

    caller = _service_user()
    user = _user(username)
    try:
        snapshot = signing.loads(restore_token, salt=SALT, max_age=300)
        state = snapshot["state"]
        all_orgs = snapshot["all_organizations"]
        names = snapshot["organizations"]
        if (snapshot["username"] != username or state not in (None, *(s[0] for s in CourseCreator.STATES))
                or (state is None and (all_orgs is not None or names))
                or (state is not None and not isinstance(all_orgs, bool))
                or not isinstance(names, list) or not all(isinstance(n, str) for n in names)):
            raise ValueError
    except (signing.BadSignature, TypeError, KeyError, ValueError):
        raise CourseCreatorError("invalid_restore") from None
    org_objects = _org_objects(names)
    with transaction.atomic():
        record, _ = CourseCreator.objects.get_or_create(user=user)
        before_snapshot = _snapshot(user, record)
        before, before_global = _rows(user)
        record.admin = caller
        record.state = state if state is not None else CourseCreator.UNREQUESTED
        if state is not None:
            record.all_organizations = all_orgs
        record.save()
        record.organizations.set(org_objects)
        desired = names if state == CourseCreator.GRANTED and not all_orgs else []
        update_org_content_creator_role(caller, user, desired)
        response = _response(user, record, before, before_snapshot, before_global)
    log.info("EDL org admin: %s via %s restored %s state=%s orgs=%s", acting_admin, caller.username,
             username, record.state, names)
    return response
