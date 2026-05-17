"""
apps/core/exception_handler.py

Custom DRF exception handler that:
1. Logs all 5xx errors with full tracebacks
2. Translates Django/DRF exceptions into clean user-facing messages
3. Never leaks internal stack traces to the client
"""
import logging
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    # Let DRF handle standard API exceptions first (401, 403, 404, etc.)
    response = drf_exception_handler(exc, context)

    if response is not None:
        # DRF handled it — clean up the error format
        view = context.get("view", "")
        method = context.get("request", "").method if context.get("request") else ""

        # Normalise error body to always have an "error" key
        if isinstance(response.data, dict) and "error" not in response.data:
            detail = response.data.get("detail", response.data)
            if hasattr(detail, "code"):
                response.data = {"error": _drf_detail_to_message(detail)}
            else:
                response.data = {"error": str(detail)}

        return response

    # Unhandled exception — log it fully, return clean message
    logger.error(
        "Unhandled exception in %s: %s",
        context.get("view", "unknown view"),
        exc,
        exc_info=True,
    )

    # Try to parse as a known API error
    try:
        from apps.core.error_utils import parse_error
        msg = parse_error(exc)
    except Exception:
        msg = "An unexpected server error occurred. Check the Docker logs for details: docker compose logs api"

    return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _drf_detail_to_message(detail) -> str:
    """Convert DRF AuthenticationFailed / PermissionDenied codes to readable messages."""
    code = getattr(detail, "code", "")
    CODE_MAP = {
        "not_authenticated":    "You are not logged in. Please log in and try again.",
        "authentication_failed":"Invalid credentials. Check your username and password.",
        "permission_denied":    "You don't have permission to do this. Admin or manager role required.",
        "not_found":            "The requested resource was not found.",
        "method_not_allowed":   "This action is not allowed.",
        "throttled":            "Too many requests. Please wait a moment and try again.",
    }
    return CODE_MAP.get(code, str(detail))
