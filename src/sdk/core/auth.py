"""Authentication configuration.

Combines Go SDK's ``AuthOptions`` and ``AKSKAuthOptions`` into a single
``AuthConfig`` model. The provider auto-detects the auth strategy
based on which fields are populated:

- ``access_key`` + ``secret_key`` → AK/SK (AWS Signature V4)
- ``password`` → Token (Keystone V3 password)
- ``token_id`` → Token (Keystone V3 token reuse)

The user never picks a strategy class — they just pass credentials.
Validation is delegated to per-strategy validator functions.

Example::

    from sdk.core.auth import AuthConfig

    # Password — detected automatically
    cfg = AuthConfig(
        identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
        username="user",
        password="secret",
        domain_name="my_domain",
    )
    cfg.auth_mode  # AuthMode.PASSWORD

    # AK/SK — same class, different fields
    cfg = AuthConfig(
        identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
        access_key="AK...",
        secret_key="SK...",
    )
    cfg.auth_mode  # AuthMode.AKSK
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import (BaseModel, SecretStr, model_validator,
                      computed_field, ConfigDict)

from sdk.core.exceptions import MissingCredentialsError

from typing import Any


class AuthMode(StrEnum):
    """Authentication strategy identifier.

    Used by ``ProviderClient`` to select the correct auth flow.
    """

    AKSK = "aksk"
    PASSWORD = "password"
    TOKEN = "token"


# --- Strategy validators ---
def _validate_aksk(cfg: AuthConfig) -> None:
    """Validate AK/SK auth fields.

    AK/SK only requires ``access_key`` and ``secret_key``,
    which are already guaranteed present by mode detection.
    """
    if cfg.access_key is None or cfg.secret_key is None:
        raise MissingCredentialsError(
            "AK/SK auth requires BOTH access_key and secret_key"
        )

def _validate_password(cfg: AuthConfig) -> None:
    """Validate password auth fields.

    - Exactly one of ``username`` or ``user_id`` must be provided.
    - If ``username`` is provided, exactly one of ``domain_id`` or
      ``domain_name`` is required.

    Raises:
        MissingCredentialsError: If required fields are missing
            or incompatible fields are present.
    """
    if cfg.password is None:
        raise MissingCredentialsError(
            "Password is required for password authentication"
        )

    # Corresponds to Go: ErrUsernameOrUserID
    if not cfg.username and not cfg.user_id:
        raise MissingCredentialsError(
            "Password auth requires username or user_id"
        )

    # Corresponds to Go: ErrUsernameOrUserID (second check)
    if cfg.username and cfg.user_id:
        raise MissingCredentialsError(
            "Provide either username or user_id, not both"
        )

    if cfg.username:
        # Corresponds to Go: ErrDomainIDOrDomainName
        if not cfg.domain_id and not cfg.domain_name:
            raise MissingCredentialsError(
                "Username auth requires domain_id or domain_name"
            )
        if cfg.domain_id and cfg.domain_name:
            raise MissingCredentialsError(
                "Provide either domain_id or domain_name, not both"
            )

def _validate_token(cfg: AuthConfig) -> None:
    """Validate token reuse fields.

    Token auth should not be mixed with password-based fields.
    Mirrors Go SDK's ``ErrUsernameWithToken`` / ``ErrUserIDWithToken``.

    Raises:
        MissingCredentialsError: If incompatible fields are present.
    """
    if not cfg.token_id:
        raise MissingCredentialsError("token_id is required")


_STRATEGY_VALIDATORS: dict[AuthMode, Callable[[AuthConfig], None]] = {
    AuthMode.AKSK: _validate_aksk,
    AuthMode.PASSWORD: _validate_password,
    AuthMode.TOKEN: _validate_token,
}


class AuthConfig(BaseModel):
    """Single auth config for all authentication strategies.

    This model provides a unified interface for all authentication strategies.
    The SDK automatically detects the correct authentication mode (AK/SK,
    Password, or Token) based on the provided fields. The model is frozen
    after instantiation to guarantee consistency between the credentials and
    the detected ``auth_mode``.

    Attributes:
        identity_endpoint: IAM endpoint URL (e.g., ``OS_AUTH_URL``).
        username: Keystone username (used for V3 password auth).
        user_id: Keystone user ID (alternative to ``username``).
        password: Keystone password (stored securely as ``SecretStr``).
        passcode: MFA TOTP verification code.
        token_id: Existing Keystone token for direct authentication.
        access_key: AK/SK access key (AWS Signature V4).
        secret_key: AK/SK secret key (stored securely as ``SecretStr``).
        domain_id: Domain ID (required when using ``username``).
        domain_name: Domain name (alternative to ``domain_id``).
        project_id: Project ID for scoping (common across all strategies).
        project_name: Project name for scoping.
        region: Target region for endpoint discovery (e.g., ``eu-de``).
        tenant_id: Project ID for scoping (alias: ``project_id``).
        tenant_name: Project name for scoping.
        security_token: Temporary security token (STS) used with temporary AK/SK.
        allow_reauth: Whether the SDK should cache and automatically refresh tokens.
        agency_name: Agency name for cross-account delegated access.
        agency_domain_name: Domain name that owns the target agency.
        delegated_project: Specific project to access via the agency delegation.
        auth_mode: The strictly detected authentication strategy. Computed
            automatically based on the provided credentials.
    """
    model_config = ConfigDict(frozen=True)
    identity_endpoint: str

    # --- Credentials ---
    username: str | None = None
    user_id: str | None = None
    password: SecretStr | None = None
    passcode: str | None = None
    token_id: str | None = None
    access_key: str | None = None
    secret_key: SecretStr | None = None

    # --- Context / Scoping ---
    domain_id: str | None = None
    domain_name: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    region: str | None = None
    tenant_id: str | None = None
    tenant_name: str | None = None

    # --- Advanced ---
    security_token: str | None = None
    allow_reauth: bool = False
    agency_name: str | None = None
    agency_domain_name: str | None = None
    delegated_project: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _sync_tenant_and_project(cls, data: dict[str, Any]) -> dict[str, Any]:
        if isinstance(data, dict):
            if "tenant_id" in data and "project_id" not in data:
                data["project_id"] = data["tenant_id"]
            if "tenant_name" in data and "project_name" not in data:
                data["project_name"] = data["tenant_name"]
        return data

    @computed_field
    @property
    def auth_mode(self) -> AuthMode:
        """Determines auth strategy based on populated fields.

        Strictly enforces that only one credential type is provided.
        """
        if self.token_id is not None:
            return AuthMode.TOKEN
        if self.access_key is not None or self.secret_key is not None:
            return AuthMode.AKSK
        if self.password is not None or self.passcode is not None:
            return AuthMode.PASSWORD

        raise MissingCredentialsError(
            "Incomplete credentials: provide AK/SK, password, or token_id"
        )

    @model_validator(mode="after")
    def _validate_credentials(self) -> AuthConfig:
        """Detect mode and delegate to the appropriate strategy validator."""
        mode = self.auth_mode
        _STRATEGY_VALIDATORS[mode](self)
        return self
