"""Shared fixtures for functional tests against a real OTC tenant.

Tests in this tree skip automatically when ``clouds.yaml`` does not
contain credentials for the configured cloud (``OS_CLOUD``, default
``otc``).

Tests should never refer to existing resources by hardcoded ID;
everything is created during the test, registered with the ``cleanup``
fixture, and deleted on teardown in reverse order.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Generator
from contextlib import ExitStack

import pytest

from sdk.core.config import load_from_yaml
from sdk.core.provider import ProviderClient
from sdk.core.service_client import ServiceClient


# Cloud name in clouds.yaml. Override to point tests at a different
# tenant without editing the file.
DEFAULT_CLOUD = os.environ.get("OS_CLOUD", "otc")


@pytest.fixture(scope="session")
def provider() -> ProviderClient:
    """Authenticated ``ProviderClient`` shared across the test session.

    Skips the session when no usable clouds.yaml is found or the named
    cloud is missing.
    """
    try:
        auth_config = load_from_yaml(DEFAULT_CLOUD)
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"clouds.yaml not usable for cloud '{DEFAULT_CLOUD}': {exc}")

    p = ProviderClient(auth_config)
    p.authenticate()
    return p


@pytest.fixture
def vpc_client(provider) -> ServiceClient:
    """``ServiceClient`` configured for the VPC service."""
    return ServiceClient(provider, service_type="vpc")


@pytest.fixture
def cleanup() -> Generator[Callable[..., None], None, None]:
    """LIFO cleanup registry backed by :class:`contextlib.ExitStack`.

    Tests register teardown callables; they run in reverse registration
    order at fixture teardown. Failures in one callback do not prevent
    later callbacks from running (standard ``ExitStack`` behaviour).

    Usage::

        def test_x(vpc_client, cleanup):
            vpc = vpcs.create(vpc_client, ...)
            cleanup(vpcs.delete, vpc_client, vpc.id)

            subnet = subnets.create(vpc_client, vpc_id=vpc.id, ...)
            cleanup(subnets.delete, vpc_client, subnet.id)
    """
    with ExitStack() as stack:
        yield stack.callback


def unique_name(prefix: str = "sdk-test") -> str:
    """Generate a unique resource name with the SDK test prefix.

    The prefix lets humans (and a future sweep script) recognise leftover
    resources from test runs.
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"