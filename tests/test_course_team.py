"""Test the Studio course team patch without edx-platform."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from django.apps import apps
from django.core.exceptions import PermissionDenied

from edl_plugin.course_team import patches


@pytest.fixture
def platform(monkeypatch):
    """Stub the Ulmo role and authorization interfaces."""
    auth = ModuleType("common.djangoapps.student.auth")
    roles = ModuleType("common.djangoapps.student.roles")
    locator = ModuleType("opaque_keys.edx.locator")
    user_view = ModuleType("cms.djangoapps.contentstore.views.user")
    user_view.last_admin_check = object()
    for module in (auth, roles, locator, user_view):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    class CourseRole:
        def __init__(self, course_key):
            self.course_key = course_key
            self.add_users = Mock()
            self.remove_users = Mock()

    class CourseInstructorRole(CourseRole):
        pass

    class CourseStaffRole(CourseRole):
        pass

    class OrgInstructorRole:
        def __init__(self, org):
            self.org = org

        def has_user(self, user):
            return user.is_authenticated and user.is_active and self.org in user.orgs

    class LibraryLocator:
        org = "OrgA"

    class CourseCreatorRole:
        pass

    class OrgContentCreatorRole:
        pass

    class GlobalStaff:
        pass

    roles.CourseRole = CourseRole
    roles.CourseInstructorRole = CourseInstructorRole
    roles.CourseStaffRole = CourseStaffRole
    roles.OrgInstructorRole = OrgInstructorRole
    roles.CourseCreatorRole = CourseCreatorRole
    roles.OrgContentCreatorRole = OrgContentCreatorRole
    roles.GlobalStaff = GlobalStaff
    locator.LibraryLocator = LibraryLocator

    def original(caller, role):
        if caller.is_staff:
            return "staff"
        raise PermissionDenied

    original_check = Mock(wraps=original)
    # Mock exposes a generic signature, so wrap it in the platform signature.

    def check(caller, role):
        return original_check(caller, role)

    auth._check_caller_authority = check

    def add_users(caller, role, *users):
        auth._check_caller_authority(caller, role)
        role.add_users(*users)

    def remove_users(caller, role, *users):
        if not (len(users) == 1 and caller == users[0]):
            auth._check_caller_authority(caller, role)
        role.remove_users(*users)

    auth.add_users = add_users
    auth.remove_users = remove_users
    return SimpleNamespace(auth=auth, roles=roles, locator=locator, view=user_view, original=original_check)


@pytest.fixture
def instructor():
    """An org instructor with no course role."""
    return SimpleNamespace(is_authenticated=True, is_active=True, is_staff=False, orgs={"OrgA"})


@pytest.mark.parametrize(
    "operation,role_name",
    [("add_users", "CourseStaffRole"), ("add_users", "CourseInstructorRole"),
     ("remove_users", "CourseStaffRole"), ("remove_users", "CourseInstructorRole")],
    ids=["add-staff", "promote-to-instructor", "demote-staff", "remove-instructor"],
)
def test_org_instructor_can_manage_course_roles(platform, instructor, operation, role_name):
    role = getattr(platform.roles, role_name)(SimpleNamespace(org="OrgA"))
    target = object()
    patches.apply_patches()
    getattr(platform.auth, operation)(instructor, role, target)
    getattr(role, operation).assert_called_once_with(target)
    platform.original.assert_not_called()


@pytest.mark.parametrize("case", ["other-org", "no-org", "inactive", "anonymous", "library"])
def test_unchanged_authority_for_other_cases(platform, instructor, case):
    key = SimpleNamespace(org="OrgB" if case == "other-org" else "OrgA")
    if case == "library":
        key = platform.locator.LibraryLocator()
    if case == "no-org":
        instructor.orgs.clear()
    if case == "inactive":
        instructor.is_active = False
    if case == "anonymous":
        instructor.is_authenticated = False
    role = platform.roles.CourseInstructorRole(key)
    patches.apply_patches()
    with pytest.raises(PermissionDenied):
        platform.auth.add_users(instructor, role, object())
    platform.original.assert_called_once_with(instructor, role)
    role.add_users.assert_not_called()


@pytest.mark.parametrize("role_name", ["CourseCreatorRole", "OrgContentCreatorRole", "GlobalStaff"])
def test_creator_and_global_roles_remain_restricted(platform, instructor, role_name):
    role = getattr(platform.roles, role_name)()
    patches.apply_patches()
    with pytest.raises(PermissionDenied):
        platform.auth._check_caller_authority(instructor, role)
    platform.original.assert_called_once_with(instructor, role)


def test_original_return_value_is_preserved(platform, instructor):
    instructor.is_staff = True
    role = platform.roles.CourseCreatorRole()
    patches.apply_patches()
    assert platform.auth._check_caller_authority(instructor, role) == "staff"
    platform.original.assert_called_once_with(instructor, role)


def test_signature_mismatch_leaves_original_in_place(platform, caplog):
    def changed(caller, role, extra):
        pass

    platform.auth._check_caller_authority = changed
    patches.apply_patches()
    assert platform.auth._check_caller_authority is changed
    assert "could not patch Studio _check_caller_authority" in caplog.text


def test_patch_is_idempotent_and_does_not_change_view(platform):
    original_view = vars(platform.view).copy()
    add_users = platform.auth.add_users
    remove_users = platform.auth.remove_users
    patches.apply_patches()
    wrapped = platform.auth._check_caller_authority
    patches.apply_patches()
    assert platform.auth._check_caller_authority is wrapped
    assert platform.auth.add_users is add_users
    assert platform.auth.remove_users is remove_users
    assert vars(platform.view) == original_view


@pytest.mark.parametrize("urlconf,is_studio", [("cms.urls", True), ("lms.urls", False)])
def test_ready_only_patches_studio(settings, monkeypatch, urlconf, is_studio):
    settings.ROOT_URLCONF = urlconf
    apply_patches = Mock()
    monkeypatch.setattr(patches, "apply_patches", apply_patches)
    apps.get_app_config("edl_plugin").ready()
    assert apply_patches.called is is_studio
