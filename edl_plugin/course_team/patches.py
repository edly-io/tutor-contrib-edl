"""Install the Studio course team authorization patch."""

import logging
from functools import wraps
from importlib import import_module
from inspect import Signature, signature

from .permissions import org_instructor_may_manage

logger = logging.getLogger(__name__)


def _patch_check_caller_authority():
    auth = import_module("common.djangoapps.student.auth")
    target = auth._check_caller_authority  # pylint: disable=protected-access
    original = signature(target)
    parameters = [parameter.replace(annotation=Signature.empty) for parameter in original.parameters.values()]
    actual = original.replace(parameters=parameters, return_annotation=Signature.empty)
    if str(actual) != "(caller, role)":
        raise ValueError(f"_check_caller_authority{actual} differs from (caller, role)")
    if getattr(target, "_edl_course_team_patch", False):
        return

    @wraps(target)
    def check_caller_authority(caller, role):
        if org_instructor_may_manage(caller, role):
            return None
        return target(caller, role)

    check_caller_authority._edl_course_team_patch = True
    auth._check_caller_authority = check_caller_authority  # pylint: disable=protected-access


def apply_patches():
    """Leave the original authorization intact if patching fails."""
    try:
        _patch_check_caller_authority()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.error("EDLINTERNA-32: could not patch Studio _check_caller_authority", exc_info=True)
