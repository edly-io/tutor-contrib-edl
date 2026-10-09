"""
Test bootstrap.

The plugin imports edx-platform modules (``lti_consumer``, ``xmodule``,
``lms``, ``common.djangoapps.edxmako``) that only exist inside the LMS. When
they are absent (running the suite standalone) install minimal stubs so the
modules import and their logic can be exercised with monkeypatched
dependencies. In the platform test environment the real modules are present and
the stubs are never used.
"""

import sys
import types


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    parent, _, child = name.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], child, module)
    return module


def _install_platform_stubs():
    try:
        import lms.djangoapps.courseware.courses  # noqa: F401  pylint: disable=unused-import
        return
    except Exception:  # pylint: disable=broad-except
        pass

    for name in (
        "lms", "lms.djangoapps", "lms.djangoapps.courseware",
        "common", "common.djangoapps", "common.djangoapps.edxmako",
        "openedx", "openedx.core",
    ):
        _stub(name)

    _stub(
        "lms.djangoapps.courseware.courses",
        get_course_with_access=lambda *args, **kwargs: None,
    )
    _stub("common.djangoapps.edxmako.paths", lookup_template=lambda namespace, name: None)
    _stub("openedx.core.constants", COURSE_ID_PATTERN=r"(?P<course_id>[^/+]+(/|\+)[^/+]+(/|\+)[^/?]+)")


_install_platform_stubs()
