"""Tests for the Studio rerun permission patches without edx-platform."""

import sys
from functools import wraps
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.urls import re_path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from edl_plugin.course_rerun import patches

COURSE_KEY = SimpleNamespace(org="Partner", course="Training", run="2026")
COURSE_ID = "course-v1:Partner+Training+2026"


@pytest.fixture
def studio(monkeypatch):
    """Provide the same patch targets, aliases, and dependencies as Ulmo.2."""
    contentstore = patches.CONTENTSTORE
    rest_views = patches.REST_VIEWS
    modules = {
        name: ModuleType(name)
        for name in (
            f"{contentstore}.utils",
            f"{contentstore}.views",
            f"{contentstore}.views.course",
            f"{rest_views}.home",
            f"{rest_views}.course_rerun",
            "common.djangoapps.student.auth",
            "common.djangoapps.student.roles",
        )
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    def get_home_context(request, no_course=False):
        return {
            "course_creator_status": request.user.creator_status,
            "rerun_creator_status": request.user.is_staff,
        }

    def get_library_context(request, request_is_json=False):
        return {"libraries": []} if request_is_json else get_home_context(request)

    def course_rerun_handler(request, course_key_string):
        raise PermissionDenied

    def verify_course_exists():
        def decorator(view):
            @wraps(view)
            def wrapped(self, request, **kwargs):
                if kwargs["course_id"] != COURSE_ID:
                    raise Http404
                return view(self, request, **kwargs)
            return wrapped
        return decorator

    class CourseRerunView:
        """Minimal API view with the original signature and schema metadata."""

        @verify_course_exists()
        def get(self, request, course_id: str):
            """Serve the rerun metadata."""
            self.permission_denied(request)

        get.kwargs = {"schema": object()}

        def permission_denied(self, request):
            """Deny access to the view."""
            raise PermissionDenied

    utils = modules[f"{contentstore}.utils"]
    home = modules[f"{rest_views}.home"]
    utils.get_home_context = home.get_home_context = get_home_context
    utils.get_library_context = home.get_library_context = get_library_context

    api = modules[f"{rest_views}.course_rerun"]
    course = modules[f"{contentstore}.views.course"]
    views = modules[f"{contentstore}.views"]
    course.course_rerun_handler = views.course_rerun_handler = course_rerun_handler
    course.login_required = login_required
    course.ensure_csrf_cookie = ensure_csrf_cookie
    course.require_http_methods = require_http_methods
    course.InvalidKeyError = ValueError
    course.PermissionDenied = PermissionDenied
    course.get_course_and_check_access = Mock()
    course.render_to_response = Mock(return_value=HttpResponse())
    api.CourseRerunView = CourseRerunView
    api.verify_course_exists = verify_course_exists
    api.CourseRerunSerializer = lambda context: SimpleNamespace(data=context)
    api.Response = lambda data: data
    api.CourseKey = course.CourseKey = SimpleNamespace(from_string=Mock(return_value=COURSE_KEY))
    api.modulestore = course.modulestore = MagicMock()
    api.get_course_rerun_context = course.get_course_rerun_context = lambda *args: {"display_name": "Training"}

    auth = modules["common.djangoapps.student.auth"]
    auth.is_content_creator = Mock(side_effect=lambda user, org: org in user.granted_orgs)
    auth.has_studio_write_access = Mock(side_effect=lambda user, key: key == COURSE_KEY and user.can_edit)
    roles = modules["common.djangoapps.student.roles"]
    roles.GlobalStaff = lambda: SimpleNamespace(has_user=lambda user: user.is_staff)
    return SimpleNamespace(utils=utils, home=home, api=api, course=course, views=views, auth=auth)


@pytest.mark.parametrize(
    "is_staff,granted_orgs,can_edit,allowed",
    [
        (True, (), False, True),
        (False, ("Partner",), True, True),
        (False, ("Partner",), False, False),
        (False, (), True, False),
        (False, ("OtherOrg",), True, False),
    ],
)
def test_course_rerun_permissions(studio, rf, is_staff, granted_orgs, can_edit, allowed):
    request = rf.get("/")
    request.user = SimpleNamespace(
        is_authenticated=True, is_staff=is_staff, granted_orgs=granted_orgs, can_edit=can_edit
    )
    patches.apply_patches()
    view = studio.api.CourseRerunView()

    if allowed:
        assert view.get(request, course_id=COURSE_ID) == {
            "display_name": "Training", "org": "Partner", "number": "Training", "run": "2026"
        }
        response = studio.views.course_rerun_handler(request, COURSE_ID)
        assert "csrftoken" in response.cookies
        studio.course.get_course_and_check_access.assert_called_once_with(COURSE_KEY, request.user, depth=3)
        studio.course.render_to_response.assert_called_once_with(
            "course-create-rerun.html", {"display_name": "Training"}
        )
    else:
        with pytest.raises(PermissionDenied):
            view.get(request, course_id=COURSE_ID)
        with pytest.raises(PermissionDenied):
            studio.views.course_rerun_handler(request, COURSE_ID)
        studio.course.modulestore.assert_not_called()

    if is_staff:
        studio.auth.is_content_creator.assert_not_called()
        studio.auth.has_studio_write_access.assert_not_called()
    else:
        studio.auth.is_content_creator.assert_called_with(request.user, COURSE_KEY.org)
        if COURSE_KEY.org in granted_orgs:
            studio.auth.has_studio_write_access.assert_called_with(request.user, COURSE_KEY)


@pytest.mark.parametrize(
    "is_staff,creator_status,shown",
    [(True, "unrequested", True), (False, "granted", True), (False, "unrequested", False)],
)
def test_home_context_flags(studio, is_staff, creator_status, shown):
    request = SimpleNamespace(user=SimpleNamespace(is_staff=is_staff, creator_status=creator_status))
    patches.apply_patches()

    assert studio.home.get_home_context is studio.utils.get_home_context
    assert studio.home.get_library_context is studio.utils.get_library_context
    assert studio.home.get_home_context(request, no_course=True)["rerun_creator_status"] is shown
    assert studio.home.get_library_context(request)["rerun_creator_status"] is shown
    assert studio.home.get_library_context(request, request_is_json=True) == {"libraries": []}


def test_legacy_handler_keeps_login_and_get_guards(studio, rf):
    patches.apply_patches()
    request = rf.get("/")
    request.user = SimpleNamespace(is_authenticated=False)
    assert studio.views.course_rerun_handler(request, COURSE_ID).status_code == 302

    request = rf.post("/")
    request.user = SimpleNamespace(is_authenticated=True)
    assert studio.views.course_rerun_handler(request, COURSE_ID).status_code == 405


def test_api_keeps_course_validation_and_schema(studio, rf):
    schema = studio.api.CourseRerunView.get.kwargs["schema"]
    patches.apply_patches()

    with pytest.raises(Http404):
        studio.api.CourseRerunView().get(rf.get("/"), course_id="invalid")
    assert studio.api.CourseRerunView.get.kwargs["schema"] is schema
    studio.auth.is_content_creator.assert_not_called()


def test_missing_and_changed_targets_are_skipped(studio, caplog):
    del studio.api.CourseRerunView.get
    studio.utils.get_home_context = lambda request: {}
    original_home_context = studio.utils.get_home_context
    original_handler = studio.course.course_rerun_handler
    patches.apply_patches()

    assert "could not patch Studio CourseRerunView.get" in caplog.text
    assert "could not patch Studio get_home_context" in caplog.text
    assert studio.utils.get_home_context is original_home_context
    assert studio.course.course_rerun_handler is not original_handler


def test_patches_are_idempotent_and_update_loaded_legacy_route(studio, monkeypatch):
    urls = ModuleType("cms.urls")
    pattern = re_path(r"^course_rerun/", studio.views.course_rerun_handler, name="course_rerun_handler")
    urls.urlpatterns = [pattern]
    monkeypatch.setitem(sys.modules, "cms.urls", urls)
    patches.apply_patches()
    replacements = (
        studio.home.get_home_context, studio.home.get_library_context,
        studio.api.CourseRerunView.get, studio.course.course_rerun_handler,
    )
    patches.apply_patches()

    assert replacements == (
        studio.home.get_home_context, studio.home.get_library_context,
        studio.api.CourseRerunView.get, studio.course.course_rerun_handler,
    )
    assert pattern.resolve("course_rerun/").func is studio.views.course_rerun_handler
    assert studio.views.course_rerun_handler is studio.course.course_rerun_handler


@pytest.mark.parametrize("urlconf,is_studio", [("cms.urls", True), ("lms.urls", False)])
def test_ready_only_patches_studio(settings, monkeypatch, urlconf, is_studio):
    settings.ROOT_URLCONF = urlconf
    apply_patches = Mock()
    monkeypatch.setattr(patches, "apply_patches", apply_patches)

    apps.get_app_config("edl_plugin").ready()

    assert apply_patches.called is is_studio
