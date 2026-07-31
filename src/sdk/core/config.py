"""Configuration loader for clouds.yaml."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from sdk.core.auth import AuthConfig, AuthMode
from sdk.core.exceptions import InvalidInputError

logger = logging.getLogger(__name__)


def load_from_yaml(cloud_name: str = "otc", file_path: str | Path | None = None) -> AuthConfig:
    """Load authentication configuration from a clouds.yaml file.

    Follows the standard OpenStack search path order if no explicit
    path is provided:
    1. Current directory (./clouds.yaml)
    2. User config (~/.config/openstack/clouds.yaml)
    3. System config (/etc/openstack/clouds.yaml)
    """
    path_to_load = _find_clouds_yaml(file_path)
    logger.debug("Loading cloud config from: %s", path_to_load)

    with open(path_to_load, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise InvalidInputError("clouds.yaml", str(path_to_load)) from e

    clouds = data.get("clouds", {})
    if cloud_name not in clouds:
        raise InvalidInputError("clouds.yaml", str(path_to_load))

    cloud_config = clouds[cloud_name]
    auth_data = cloud_config.get("auth", {})

    logger.debug("Loaded cloud config: '%s'", cloud_name)
    return _map_to_auth_config(cloud_config, auth_data)


def _find_clouds_yaml(explicit_path: str | Path | None) -> Path:
    """Locate the clouds.yaml file in standard locations."""
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Explicit config file not found: {explicit_path}")

    search_paths = [
        Path.cwd() / "clouds.yaml",
        Path.home() / ".config" / "openstack" / "clouds.yaml",
        Path("/etc/openstack/clouds.yaml"),
    ]

    for p in search_paths:
        if p.is_file():
            return p

    raise FileNotFoundError(
        "Could not find 'clouds.yaml' in standard locations "
        "(./, ~/.config/openstack/, /etc/openstack/)."
    )


def _resolve_env(value: Any) -> Any:
    """Resolve ${ENV_VAR} or $ENV_VAR syntax in strings."""
    if isinstance(value, str) and "$" in value:
        # Встроенный метод Python: сам найдет и подставит переменные окружения
        return os.path.expandvars(value)
    return value


def _map_to_auth_config(cloud_config: dict[str, Any], auth_data: dict[str, Any]) -> AuthConfig:
    """Map OpenStack clouds.yaml fields to our AuthConfig Pydantic model."""

    auth = {k: _resolve_env(v) for k, v in auth_data.items()}
    cloud = {k: _resolve_env(v) for k, v in cloud_config.items()}

    if auth.get("password"):
        mode = AuthMode.PASSWORD
    elif any(k in auth for k in ("access_key", "ak", "secret_key", "sk")):
        mode = AuthMode.AKSK
    else:
        mode = AuthMode.TOKEN

    logger.debug("Auth mode resolved: %s", mode)

    raw_url = auth.get("auth_url") or auth.get("identity_endpoint") or ""
    auth_url = raw_url.rstrip("/")
    if auth_url and not auth_url.endswith("/v3"):
        auth_url += "/v3"

    config_kwargs: dict[str, Any] = {
        "auth_mode": mode,
        "identity_endpoint": auth_url,
        "region": cloud.get("region_name", ""),
    }

    config_kwargs["project_name"] = auth.get("project_name") or auth.get("tenant_name")
    config_kwargs["project_id"] = auth.get("project_id") or auth.get("tenant_id")

    config_kwargs["domain_name"] = (
            auth.get("domain_name")
            or auth.get("user_domain_name")
            or auth.get("project_domain_name")
    )
    config_kwargs["domain_id"] = auth.get("domain_id") or auth.get("user_domain_id")

    if mode == AuthMode.AKSK:
        config_kwargs["access_key"] = auth.get("access_key") or auth.get("ak")
        config_kwargs["secret_key"] = auth.get("secret_key") or auth.get("sk")
    else:
        config_kwargs["username"] = auth.get("username")
        config_kwargs["password"] = auth.get("password")

    clean_kwargs = {k: v for k, v in config_kwargs.items() if v}

    return AuthConfig(**clean_kwargs)