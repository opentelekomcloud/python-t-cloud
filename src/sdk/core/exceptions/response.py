"""HTTP response exceptions.

Corresponds to Go SDK's ``ErrUnexpectedResponseCode`` and all
``ErrDefaultNNN`` types.
"""

from __future__ import annotations

from typing import Any

from .base import SDKError


class HttpError(SDKError):
    """HTTP response error.

    Corresponds to Go SDK's ``ErrUnexpectedResponseCode``.
    Stores full request context for debuggability.

    Args:
        method: HTTP method (GET, POST, etc.).
        url: Request URL.
        body: Response body text.
        expected: List of expected HTTP status codes.
        headers: Response headers.
        status_code: HTTP status code. Overrides the class-level
            default when constructing a generic ``HttpError``.

    Attributes:
        status_code: HTTP status code. Set as a class variable
            on subclasses (e.g. ``BadRequestError.status_code == 400``).
        request_id: Value of the ``X-Request-Id`` response header,
            extracted automatically for OTC request tracing.
    """

    status_code: int = 0

    def __init__(
        self,
        *,
        method: str,
        url: str,
        body: str,
        expected: list[int] | None = None,
        headers: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self.body = body
        self.expected = expected or []
        self.headers = headers or {}
        self.request_id: str = self.headers.get("x-request-id", "")
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        msg = (
            f"Expected HTTP response code {self.expected} when accessing "
            f"[{self.method} {self.url}], but got {self.status_code} instead"
        )
        if self.body:
            msg += f"\n{self.body}"
        return msg


# --- Status-code specific errors ---


class BadRequestError(HttpError):
    """400 Bad Request.

    Corresponds to Go SDK's ``ErrDefault400``.
    """

    status_code = 400

    def _format_message(self) -> str:
        return (
            f"Bad request with: [{self.method} {self.url}], "
            f"error message: {self.body}"
        )


class UnauthorizedError(HttpError):
    """401 Unauthorized.

    Corresponds to Go SDK's ``ErrDefault401``.
    """

    status_code = 401

    def _format_message(self) -> str:
        return f"Authentication failed, error message: {self.body}"


class ForbiddenError(HttpError):
    """403 Forbidden.

    Corresponds to Go SDK's ``ErrDefault403``.
    """

    status_code = 403

    def _format_message(self) -> str:
        return f"Action forbidden, error message: {self.body}"


class NotFoundError(HttpError):
    """404 Not Found.

    Corresponds to Go SDK's ``ErrDefault404``.
    """

    status_code = 404

    def _format_message(self) -> str:
        return (
            f"Resource not found: [{self.method} {self.url}], "
            f"error message: {self.body}"
        )


class MethodNotAllowedError(HttpError):
    """405 Method Not Allowed.

    Corresponds to Go SDK's ``ErrDefault405``.
    """

    status_code = 405

    def _format_message(self) -> str:
        return "Method not allowed"


class RequestTimeoutError(HttpError):
    """408 Request Timeout.

    Corresponds to Go SDK's ``ErrDefault408``.
    """

    status_code = 408

    def _format_message(self) -> str:
        return "The server timed out waiting for the request"


class ConflictError(HttpError):
    """409 Conflict.

    Corresponds to Go SDK's ``ErrDefault409``.
    """

    status_code = 409


class TooManyRequestsError(HttpError):
    """429 Too Many Requests.

    Corresponds to Go SDK's ``ErrDefault429``.
    Checks ``Retry-After`` response header when present.
    """

    status_code = 429

    def _format_message(self) -> str:
        retry_after = self.headers.get("Retry-After", "")
        msg = (
            "Too many requests have been sent in a given amount of time."
        )
        if retry_after:
            msg += f" Retry after {retry_after}s."
        else:
            msg += " Pause requests, wait up to one minute, and try again."
        return msg


class InternalServerError(HttpError):
    """500 Internal Server Error.

    Corresponds to Go SDK's ``ErrDefault500``.
    """

    status_code = 500

    def _format_message(self) -> str:
        return "Internal Server Error"


class ServiceUnavailableError(HttpError):
    """503 Service Unavailable.

    Corresponds to Go SDK's ``ErrDefault503``.
    """

    status_code = 503

    def _format_message(self) -> str:
        return (
            "The service is currently unable to handle the request due to "
            "a temporary overloading or maintenance. This is a temporary "
            "condition. Try again later."
        )


# --- Mapping from status code to exception class ---

HTTP_ERROR_MAP: dict[int, type[HttpError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    405: MethodNotAllowedError,
    408: RequestTimeoutError,
    409: ConflictError,
    429: TooManyRequestsError,
    500: InternalServerError,
    503: ServiceUnavailableError,
}


def raise_for_status(
    status_code: int,
    *,
    method: str,
    url: str,
    body: str,
    expected: list[int] | None = None,
    headers: dict[str, Any] | None = None,
) -> None:
    """Raise the appropriate ``HttpError`` for a non-2xx status code.

    Looks up the status code in ``HTTP_ERROR_MAP`` and raises the
    matching exception. Falls back to a generic ``HttpError`` for
    unmapped codes.

    Args:
        status_code: HTTP response status code.
        method: HTTP method (GET, POST, etc.).
        url: Request URL.
        body: Response body text.
        expected: List of expected HTTP status codes.
        headers: Response headers.

    Raises:
        HttpError: Always raised (specific subclass when possible).
    """
    exc_class = HTTP_ERROR_MAP.get(status_code, HttpError)
    raise exc_class(
        method=method,
        url=url,
        body=body,
        expected=expected,
        headers=headers,
        status_code=status_code,
    )
