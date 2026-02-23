"""Tests for sdk.core.auth."""

import pytest

from sdk.core.auth import AuthConfig, AuthMode
from sdk.core.exceptions import MissingCredentialsError


class TestAuthModeDetection:
    """AuthConfig should auto-detect strategy from provided fields."""

    def test_password_mode(self):
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            username="user",
            password="pass",
            domain_name="my_domain",
        )
        assert cfg.auth_mode == AuthMode.PASSWORD

    def test_aksk_mode(self):
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            access_key="AK_TEST",
            secret_key="SK_TEST",
            project_id="project123",
        )
        assert cfg.auth_mode == AuthMode.AKSK

    def test_token_mode(self):
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            token_id="gAAAA_test_token",
        )
        assert cfg.auth_mode == AuthMode.TOKEN

    def test_aksk_takes_priority_over_password(self):
        """If both AK/SK and password are provided, AK/SK wins."""
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            access_key="AK",
            secret_key="SK",
            password="pass",
            username="user",
            domain_name="domain",
        )
        assert cfg.auth_mode == AuthMode.AKSK


class TestAuthConfigValidation:
    """AuthConfig should reject invalid credential combinations."""

    def test_no_credentials_raises(self):
        with pytest.raises(MissingCredentialsError, match="Cannot determine auth mode"):
            AuthConfig(
                identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            )

    def test_password_without_username_raises(self):
        with pytest.raises(MissingCredentialsError, match="username or user_id"):
            AuthConfig(
                identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
                password="pass",
            )

    def test_username_without_domain_raises(self):
        with pytest.raises(MissingCredentialsError, match="domain_id or domain_name"):
            AuthConfig(
                identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
                username="user",
                password="pass",
            )

    def test_token_with_username_raises(self):
        with pytest.raises(MissingCredentialsError, match="should not be provided"):
            AuthConfig(
                identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
                token_id="gAAAA_test",
                username="user",
            )

    def test_password_with_user_id_is_valid(self):
        """user_id doesn't require domain."""
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            user_id="user123",
            password="pass",
        )
        assert cfg.auth_mode == AuthMode.PASSWORD

    def test_password_with_domain_id_is_valid(self):
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            username="user",
            password="pass",
            domain_id="domain123",
        )
        assert cfg.auth_mode == AuthMode.PASSWORD


class TestAuthConfigOptionalFields:
    """Optional fields should be preserved."""

    def test_agency_fields(self):
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            access_key="AK",
            secret_key="SK",
            agency_name="my_agency",
            agency_domain_name="agency_domain",
            delegated_project="delegated",
        )
        assert cfg.agency_name == "my_agency"
        assert cfg.agency_domain_name == "agency_domain"
        assert cfg.delegated_project == "delegated"

    def test_temporary_aksk(self):
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            access_key="AK",
            secret_key="SK",
            security_token="temp_token",
        )
        assert cfg.security_token == "temp_token"

    def test_mfa_passcode(self):
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            username="user",
            password="pass",
            domain_name="domain",
            passcode="123456",
        )
        assert cfg.passcode == "123456"
