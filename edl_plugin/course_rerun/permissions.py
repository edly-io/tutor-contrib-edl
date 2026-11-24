"""Permission checks for Studio course reruns."""


def can_rerun_course(user, course_key):
    """Allow global staff or a course editor with a matching creation grant."""
    from common.djangoapps.student.auth import has_studio_write_access, is_content_creator
    from common.djangoapps.student.roles import GlobalStaff

    return GlobalStaff().has_user(user) or (
        is_content_creator(user, course_key.org) and has_studio_write_access(user, course_key)
    )


def can_show_rerun(is_global_staff, course_creator_status):
    """Return the home page flag when Studio has no single course to check."""
    return is_global_staff or course_creator_status == "granted"
