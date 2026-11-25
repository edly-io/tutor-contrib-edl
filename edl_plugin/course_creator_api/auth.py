"""Authentication and permissions for the portal service account."""

from django.conf import settings
from rest_framework.permissions import BasePermission


def service_username():
    """Return the configured service account username."""
    return getattr(settings, "ADMIN_PORTAL_SERVICE_USER", "edl_portal_service")


def get_authentication_classes():
    """Use JWT authentication when the platform package is installed."""
    try:
        from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
    except ImportError:
        return []
    return [JwtAuthentication]


class IsPortalServiceAccount(BasePermission):
    """Restrict access to the configured service account."""

    message = "Only the portal service account may call this endpoint."
    code = "not_service_account"

    def has_permission(self, request, view):
        """Check the authenticated identity."""
        return bool(request.user and request.user.is_authenticated and request.user.username == service_username())
