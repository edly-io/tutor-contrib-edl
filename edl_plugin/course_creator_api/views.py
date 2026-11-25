"""Studio endpoint for course creator access."""

from rest_framework.response import Response
from rest_framework.views import APIView

from . import service
from .auth import IsPortalServiceAccount, get_authentication_classes


class CourseCreatorAccessView(APIView):
    """Read and update course creator access for the portal."""

    authentication_classes = get_authentication_classes()
    permission_classes = (IsPortalServiceAccount,)

    def finalize_response(self, request, response, *args, **kwargs):
        """Prevent caching, including for error responses."""
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        if response.status_code == 403 and getattr(response.data.get("detail"), "code", None) == "not_service_account":
            response.data = {"code": "not_service_account", "detail": IsPortalServiceAccount.message}
        return response

    def get(self, request, username):
        """Read the current state."""
        try:
            return Response(service.get_state(username))
        except service.CourseCreatorError as exc:
            return self._error(exc)

    def post(self, request, username):
        """Apply a requested state or restore a signed snapshot."""
        data = request.data
        try:
            if "restore_token" in data:
                result = service.restore_state(username, data["restore_token"], data.get("acting_admin", ""))
            else:
                org_admin = data.get("org_admin")
                orgs = data.get("organizations")
                confirm = data.get("confirm_downgrade", False)
                if not isinstance(org_admin, bool) or not isinstance(orgs, list) or not all(
                    isinstance(org, str) for org in orgs
                ) or not isinstance(confirm, bool):
                    return Response({"code": "invalid_request", "detail": "Invalid request."}, status=400)
                result = service.set_state(username, org_admin, orgs, data.get("acting_admin", ""), confirm)
            return Response(result)
        except service.CourseCreatorError as exc:
            return self._error(exc)

    @staticmethod
    def _error(exc):
        body = {"code": exc.code, "detail": exc.message}
        if exc.organizations is not None:
            body["organizations"] = exc.organizations
        return Response(body, status=exc.status)
