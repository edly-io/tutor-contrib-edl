"""Install the EDLINTERNA-32 patches for Studio on Open edX Ulmo.2."""

import logging
import sys
from functools import wraps
from importlib import import_module
from inspect import Signature, signature

from .permissions import can_rerun_course, can_show_rerun

logger = logging.getLogger(__name__)
CONTENTSTORE = "cms.djangoapps.contentstore"
REST_VIEWS = f"{CONTENTSTORE}.rest_api.v1.views"


def _checked_target(owner, name, expected_signature):
    target = getattr(owner, name)
    original_signature = signature(target)
    parameters = [parameter.replace(annotation=Signature.empty) for parameter in original_signature.parameters.values()]
    actual = original_signature.replace(parameters=parameters, return_annotation=Signature.empty)
    if str(actual) != expected_signature:
        raise ValueError(f"{name}{actual} differs from {name}{expected_signature}")
    return target


def _check_alias(owner, name, target):
    if getattr(owner, name) is not target:
        raise ValueError(f"{owner.__name__}.{name} does not reference the expected function")


def _patch_context(name, expected_signature):
    utils = import_module(f"{CONTENTSTORE}.utils")
    target = _checked_target(utils, name, expected_signature)
    if getattr(target, "_edl_rerun_patch", False):
        return
    home = import_module(f"{REST_VIEWS}.home")
    _check_alias(home, name, target)

    @wraps(target)
    def context_with_rerun_flag(*args, **kwargs):
        context = target(*args, **kwargs)
        if "rerun_creator_status" in context:
            # The original context already called Studio's _get_course_creator_status.
            context["rerun_creator_status"] = can_show_rerun(
                context["rerun_creator_status"], context["course_creator_status"]
            )
        return context

    context_with_rerun_flag._edl_rerun_patch = True
    setattr(utils, name, context_with_rerun_flag)
    setattr(home, name, context_with_rerun_flag)


def _patch_rerun_api():
    api = import_module(f"{REST_VIEWS}.course_rerun")
    target = _checked_target(api.CourseRerunView, "get", "(self, request, course_id)")
    if getattr(target, "_edl_rerun_patch", False):
        return

    @wraps(target)
    @api.verify_course_exists()
    def get(view, request, course_id):
        course_key = api.CourseKey.from_string(course_id)
        if not can_rerun_course(request.user, course_key):
            view.permission_denied(request)

        with api.modulestore().bulk_operations(course_key):
            course_block = api.modulestore().get_course(course_key)
            context = api.get_course_rerun_context(course_key, course_block, request.user)
            context.update(org=course_key.org, number=course_key.course, run=course_key.run)
            return api.Response(api.CourseRerunSerializer(context).data)

    get._edl_rerun_patch = True
    api.CourseRerunView.get = get


def _patch_rerun_handler():
    course = import_module(f"{CONTENTSTORE}.views.course")
    name = "course_rerun_handler"
    target = _checked_target(course, name, "(request, course_key_string)")
    if getattr(target, "_edl_rerun_patch", False):
        return
    views = import_module(f"{CONTENTSTORE}.views")
    _check_alias(views, name, target)

    # Django normally loads cms.urls after AppConfig.ready(). Update the callback
    # too if earlier startup code already loaded the URL configuration.
    urls = sys.modules.get("cms.urls")
    pattern = None
    if urls is not None:
        pattern = next((item for item in urls.urlpatterns if getattr(item, "name", None) == name), None)
        if getattr(pattern, "callback", None) is not target:
            raise ValueError(f"cms.urls does not route {name} to the expected function")

    @wraps(target)
    @course.login_required
    @course.ensure_csrf_cookie
    @course.require_http_methods(["GET"])
    def handler(request, course_key_string):
        try:
            course_key = course.CourseKey.from_string(course_key_string)
        except course.InvalidKeyError:
            return target(request, course_key_string)
        if not can_rerun_course(request.user, course_key):
            raise course.PermissionDenied()

        with course.modulestore().bulk_operations(course_key):
            course_block = course.get_course_and_check_access(course_key, request.user, depth=3)
            context = course.get_course_rerun_context(course_key, course_block, request.user)
            return course.render_to_response("course-create-rerun.html", context)

    handler._edl_rerun_patch = True
    course.course_rerun_handler = handler
    views.course_rerun_handler = handler
    if pattern is not None:
        pattern.callback = handler


def apply_patches():
    """Apply each rerun patch independently and leave incompatible targets alone."""
    patches = (
        ("get_home_context", _patch_context, ("get_home_context", "(request, no_course=False)")),
        ("get_library_context", _patch_context, ("get_library_context", "(request, request_is_json=False)")),
        ("CourseRerunView.get", _patch_rerun_api, ()),
        ("course_rerun_handler", _patch_rerun_handler, ()),
    )
    for name, install, args in patches:
        try:
            install(*args)
        except Exception:
            logger.error("EDLINTERNA-32: could not patch Studio %s", name, exc_info=True)
