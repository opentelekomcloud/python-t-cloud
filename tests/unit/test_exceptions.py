"""Tests for sdk.core.exceptions."""

import pytest

from sdk.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    HttpError,
    NotFoundError,
    SDKError,
    SDKTimeoutError,
    ServiceUnavailableError,
    TooManyRequestsError,
    raise_for_status,
)


class TestHttpErrorHierarchy:
    def test_all_http_errors_inherit_from_sdk_error(self):
        err = BadRequestError(method="POST", url="/test", body="bad")
        assert isinstance(err, SDKError)
        assert isinstance(err, HttpError)

    def test_status_code_on_class(self):
        assert BadRequestError.status_code == 400
        assert AuthenticationError.status_code == 401
        assert NotFoundError.status_code == 404

    def test_default_format(self):
        err = BadRequestError(method="POST", url="/v3/zones", body="invalid json")
        assert "400" in str(err)
        assert "POST" in str(err)
        assert "/v3/zones" in str(err)

    def test_custom_format_not_found(self):
        err = NotFoundError(method="GET", url="/v3/zones/123", body="")
        assert "Resource not found" in str(err)

    def test_custom_format_too_many_requests_without_header(self):
        err = TooManyRequestsError(method="GET", url="/test", body="")
        assert "retry" in str(err).lower()

    def test_custom_format_too_many_requests_with_retry_after(self):
        err = TooManyRequestsError(
            method="GET", url="/test", body="",
            headers={"Retry-After": "30"},
        )
        assert "30" in str(err)
        assert "Retry after" in str(err)

    def test_custom_format_service_unavailable(self):
        err = ServiceUnavailableError(method="GET", url="/test", body="")
        assert "temporarily unavailable" in str(err).lower()


class TestHttpErrorHeaders:
    def test_headers_stored(self):
        err = BadRequestError(
            method="POST", url="/test", body="bad",
            headers={"X-Request-Id": "abc123"},
        )
        assert err.headers["X-Request-Id"] == "abc123"

    def test_headers_default_to_empty_dict(self):
        err = BadRequestError(method="POST", url="/test", body="bad")
        assert err.headers == {}


class TestRaiseForStatus:
    def test_raises_known_status(self):
        with pytest.raises(NotFoundError) as exc_info:
            raise_for_status(404, method="GET", url="/test", body="gone")
        assert exc_info.value.status_code == 404

    def test_raises_generic_for_unknown_status(self):
        with pytest.raises(HttpError) as exc_info:
            raise_for_status(418, method="GET", url="/teapot", body="short and stout")
        assert exc_info.value.status_code == 418

    def test_authentication_error_message(self):
        with pytest.raises(AuthenticationError) as exc_info:
            raise_for_status(401, method="POST", url="/v3/auth/tokens", body="invalid token")
        assert "Authentication failed" in str(exc_info.value)

    def test_passes_headers_through(self):
        with pytest.raises(TooManyRequestsError) as exc_info:
            raise_for_status(
                429, method="GET", url="/test", body="",
                headers={"Retry-After": "60"},
            )
        assert exc_info.value.headers["Retry-After"] == "60"


class TestSDKTimeoutError:
    def test_not_builtin_timeout(self):
        """SDKTimeoutError should not be confused with builtin TimeoutError."""
        err = SDKTimeoutError("operation timed out")
        assert isinstance(err, SDKError)
        assert not isinstance(err, builtins_timeout_error())


def builtins_timeout_error():
    """Return the builtin TimeoutError for isinstance check."""
    return TimeoutError
