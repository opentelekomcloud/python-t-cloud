"""Authentication-related exceptions.

Corresponds to Go SDK's ``ErrUnableToReauthenticate`` and
``ErrErrorAfterReauthentication``.
"""

from __future__ import annotations

from .base import SDKError


class AuthError(SDKError):
    """Authentication-related error."""


class MissingCredentialsError(AuthError):
    """Required credentials were not provided.

    Raised when ``AuthConfig`` cannot determine an auth strategy
    from the provided fields.
    """


class ReauthError(AuthError):
    """Re-authentication failed.

    Corresponds to Go SDK's ``ErrUnableToReauthenticate``.

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


class PostReauthError(AuthError):
    """Request failed after successful re-authentication.

    Corresponds to Go SDK's ``ErrErrorAfterReauthentication``.
    Raised when the token was refreshed successfully, but the
    subsequent request still failed (usually an HTTP error).

    Args:
        original: The underlying exception from the failed request.
    """

    def __init__(self, original: Exception | None = None) -> None:
        self.original = original
        msg = (
            f"Successfully re-authenticated, but got error "
            f"executing request: {original}"
            if original
            else "Successfully re-authenticated, but got error executing request"
        )
        super().__init__(msg)
