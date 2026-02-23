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

from enum import StrEnum

from pydantic import BaseModel, model_validator, SecretStr

from sdk.core.exceptions import MissingCredentialsError


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

    Args:
        cfg: Auth configuration to validate.
    """


def _validate_password(cfg: AuthConfig) -> None:
    """Validate password auth fields.

    Requires either ``username`` + (``domain_id`` | ``domain_name``)
    or ``user_id`` alone. Mirrors Go SDK's ``ToTokenV3CreateMap``
    validation logic.

    Args:
        cfg: Auth configuration to validate.

    Raises:
        MissingCredentialsError: If required fields are missing.
    """
    if not cfg.username and not cfg.user_id:
        raise MissingCredentialsError(
            "Password auth requires username or user_id"
        )
    if cfg.username and not cfg.domain_id and not cfg.domain_name:
        raise MissingCredentialsError(
            "Username auth requires domain_id or domain_name"
        )


def _validate_token(cfg: AuthConfig) -> None:
    """Validate token reuse fields.

    Token auth should not be mixed with password-based fields
    (``username`` / ``user_id``). Mirrors Go SDK's
    ``ErrUsernameWithToken`` / ``ErrUserIDWithToken`` checks.

    Args:
        cfg: Auth configuration to validate.

    Raises:
        MissingCredentialsError: If incompatible fields are present.
    """
    if cfg.username or cfg.user_id:
        raise MissingCredentialsError(
            "Username/user_id should not be provided with token auth"
        )


_STRATEGY_VALIDATORS = {
    AuthMode.AKSK: _validate_aksk,
    AuthMode.PASSWORD: _validate_password,
    AuthMode.TOKEN: _validate_token,
}


class AuthConfig(BaseModel):
    """Single auth config for all authentication strategies.

    All fields are optional except ``identity_endpoint``. The
    ``auth_mode`` property inspects which fields are set and selects
    the appropriate strategy. Validation is performed at construction
    time via pydantic's ``model_validator``.

    Attributes:
        identity_endpoint: IAM endpoint URL (``OS_AUTH_URL``).
        username: Keystone username (V3 password auth).
        user_id: Keystone user ID (alternative to ``username``).
        password: Keystone password.
        token_id: Existing token for re-authentication.
        domain_id: Domain ID (required with ``username``).
        domain_name: Domain name (alternative to ``domain_id``).
        tenant_id: Project ID for scoping (alias: ``project_id``).
        tenant_name: Project name for scoping.
        allow_reauth: Whether the SDK may cache and refresh tokens.
        passcode: MFA TOTP verification code.
        access_key: AK/SK access key.
        secret_key: AK/SK secret key.
        security_token: Temporary security token (temporary AK/SK).
        project_id: Project ID (common across strategies).
        project_name: Project name.
        region: Target region (e.g. ``eu-de``).
        agency_name: Agency name for delegated access.
        agency_domain_name: Domain that owns the agency.
        delegated_project: Project delegated via agency.
    """

    # Required for all strategies
    identity_endpoint: str

    # --- Token/Password auth fields ---
    username: str | None = None
    user_id: str | None = None
    password: SecretStr | None = None
    token_id: str | None = None
    domain_id: str | None = None
    domain_name: str | None = None
    tenant_id: str | None = None
    tenant_name: str | None = None
    allow_reauth: bool = False
    passcode: str | None = None

    # --- AK/SK auth fields ---
    access_key: str | None = None
    secret_key: SecretStr | None = None
    security_token: str | None = None

    # --- Common fields ---
    project_id: str | None = None
    project_name: str | None = None
    region: str | None = None

    # --- Agency delegation ---
    agency_name: str | None = None
    agency_domain_name: str | None = None
    delegated_project: str | None = None

    @property
    def auth_mode(self) -> AuthMode:
        """Auto-detect auth strategy from provided fields.

        Detection priority: AK/SK > password > token.

        Returns:
            Detected authentication mode.

        Raises:
            MissingCredentialsError: If no known credential
                combination is present.
        """
        if self.access_key and self.secret_key:
            return AuthMode.AKSK
        if self.password:
            return AuthMode.PASSWORD
        if self.token_id:
            return AuthMode.TOKEN
        raise MissingCredentialsError(
            "Cannot determine auth mode: "
            "provide access_key+secret_key, password, or token_id"
        )

    @model_validator(mode="after")
    def _validate_credentials(self) -> AuthConfig:
        """Detect mode and delegate to the appropriate strategy validator."""
        mode = self.auth_mode
        _STRATEGY_VALIDATORS[mode](self)
        return self
