"""Permission checks for organization instructors."""


def org_instructor_may_manage(caller, role):
    """Allow organization instructors to manage roles on their courses."""
    from common.djangoapps.student.roles import CourseRole, OrgInstructorRole
    from opaque_keys.edx.locator import LibraryLocator

    if not isinstance(role, CourseRole) or isinstance(role.course_key, LibraryLocator):
        return False
    return OrgInstructorRole(org=role.course_key.org).has_user(caller)
