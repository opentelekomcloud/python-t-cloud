"""Exception hierarchy for the SDK.

Mirrors the Go SDK error types but uses Python exception inheritance
instead of Go's struct embedding pattern.

Hierarchy::

    SDKError
    ├── AuthError
    │   ├── MissingCredentialsError
    │   └── ReauthError
    ├── EndpointError
    │   ├── ServiceNotFoundError
    │   └── EndpointNotFoundError
    ├── HttpError
    │   ├── BadRequestError          (400)
    │   ├── AuthenticationError      (401)
    │   ├── ForbiddenError           (403)
    │   ├── NotFoundError            (404)
    │   ├── MethodNotAllowedError    (405)
    │   ├── ConflictError            (409)
    │   ├── RequestTimeoutError      (408)
    │   ├── TooManyRequestsError     (429)
    │   ├── InternalServerError      (500)
    │   └── ServiceUnavailableError  (503)
    └── SDKTimeoutError
"""

from __future__ import annotations

from typing import Any


class SDKError(Exception):
    """Base exception for all SDK errors."""


# --- Auth errors ---


class AuthError(SDKError):
    """Authentication-related error."""


class MissingCredentialsError(AuthError):
    """Required credentials were not provided.

    Raised when ``AuthConfig`` cannot determine an auth strategy
    from the provided fields.
    """


class ReauthError(AuthError):
    """Re-authentication failed.

    Args:
        original: The underlying exception that caused the failure.
    """

    def __init__(self, original: Exception | None = None) -> None:
        self.original = original
        msg = (
            f"Unable to re-authenticate: {original}"
            if original
            else "Unable to re-authenticate"
        )
        super().__init__(msg)


# --- Endpoint errors ---


class EndpointError(SDKError):
    """Endpoint discovery error."""


class ServiceNotFoundError(EndpointError):
    """No matching service found in the service catalog.

    Args:
        service: Name of the service that was not found.
    """

    def __init__(self, service: str = "") -> None:
        self.service = service
        msg = (
            f"No suitable service could be found: {service}"
            if service
            else "No suitable service could be found in the service catalog"
        )
        super().__init__(msg)


class EndpointNotFoundError(EndpointError):
    """No matching endpoint found for the service.

    Args:
        service: Name of the service.
        region: Region where the endpoint was expected.
    """

    def __init__(self, service: str = "", region: str = "") -> None:
        self.service = service
        self.region = region
        parts = ["No suitable endpoint could be found"]
        if service:
            parts.append(f"for service '{service}'")
        if region:
            parts.append(f"in region '{region}'")
        super().__init__(" ".join(parts))


# --- HTTP errors ---


class HttpError(SDKError):
    """HTTP response error.

    Corresponds to Go SDK's ``ErrUnexpectedResponseCode``.
    All request context fields are required for debuggability.
    Response headers are preserved for retry logic (e.g. ``Retry-After``).

    Args:
        method: HTTP method (GET, POST, etc.).
        url: Request URL.
        body: Response body text.
        headers: Response headers. Useful for extracting ``Retry-After``
            and ``X-Request-Id``.
        status_code: HTTP status code. Overrides the class-level default
            when constructing a generic ``HttpError``.

    Attributes:
        status_code: HTTP status code. Set as a class variable on subclasses
            (e.g. ``BadRequestError.status_code == 400``).
    """

    status_code: int = 0

    def __init__(
        self,
        *,
        method: str,
        url: str,
        body: str,
        headers: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self.body = body
        self.headers = headers or {}
        self.request_id: str = self.headers.get("x-request-id", "")
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        return (
            f"HTTP {self.status_code}: "
            f"[{self.method} {self.url}] "
            f"{self.body}"
        )


class BadRequestError(HttpError):
    """400 Bad Request."""

    status_code = 400


class AuthenticationError(HttpError):
    """401 Unauthorized."""

    status_code = 401

    def _format_message(self) -> str:
        return f"Authentication failed: {self.body}" if self.body else "Authentication failed"


class ForbiddenError(HttpError):
    """403 Forbidden."""

    status_code = 403

    def _format_message(self) -> str:
        return f"Action forbidden: {self.body}" if self.body else "Action forbidden"


class NotFoundError(HttpError):
    """404 Not Found."""

    status_code = 404

    def _format_message(self) -> str:
        return f"Resource not found: [{self.method} {self.url}]"


class MethodNotAllowedError(HttpError):
    """405 Method Not Allowed."""

    status_code = 405


class RequestTimeoutError(HttpError):
    """408 Request Timeout."""

    status_code = 408


class ConflictError(HttpError):
    """409 Conflict."""

    status_code = 409


class TooManyRequestsError(HttpError):
    """429 Too Many Requests.

    Checks the ``Retry-After`` response header and includes it
    in the error message when present.
    """

    status_code = 429

    def _format_message(self) -> str:
        retry_after = self.headers.get("Retry-After", "")
        msg = "Too many requests."
        if retry_after:
            msg += f" Retry after {retry_after}s."
        else:
            msg += " Pause and retry after a short wait."
        return msg


class InternalServerError(HttpError):
    """500 Internal Server Error."""

    status_code = 500


class ServiceUnavailableError(HttpError):
    """503 Service Unavailable."""

    status_code = 503

    def _format_message(self) -> str:
        return "Service temporarily unavailable. Try again later."


# --- Mapping from status code to exception class ---

HTTP_ERROR_MAP: dict[int, type[HttpError]] = {
    400: BadRequestError,
    401: AuthenticationError,
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
        headers: Response headers.

    Raises:
        HttpError: Always raised (specific subclass when possible).
    """
    exc_class = HTTP_ERROR_MAP.get(status_code, HttpError)
    raise exc_class(
        method=method, url=url, body=body, headers=headers, status_code=status_code,
    )


# --- Timeout ---


class SDKTimeoutError(SDKError):
    """Client-side operation timeout.

    Distinct from ``RequestTimeoutError`` (HTTP 408) which is a server
    response. This error is raised when the SDK's own timeout is exceeded,
    e.g. waiting for a resource to become active.
    """
