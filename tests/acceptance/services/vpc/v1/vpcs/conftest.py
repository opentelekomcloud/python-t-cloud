"""Shared fixtures for VPC functional tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sdk.core.exceptions import HttpError
from sdk.services.vpc.v1.vpcs import CreateVpcOpts, Vpc, create, delete

from tests.acceptance.conftest import unique_name


def _safe_delete(client, vpc_id: str) -> None:
    """Idempotent delete used by cleanup hooks.

    A test may delete the VPC explicitly as part of its assertions; the
    cleanup hook fires afterwards, so a 404 here is expected and ignored.
    Any other error surfaces as a real cleanup failure.
    """
    try:
        delete(client, vpc_id)
    except HttpError as exc:
        if exc.status_code != 404:
            raise


@pytest.fixture
def created_vpc(vpc_client, cleanup) -> Callable[..., Vpc]:
    """Factory fixture: create a test VPC and auto-register its cleanup.

    Returns a callable. Each call creates a new VPC, registers its
    deletion with the session ``cleanup`` hook, and returns the created
    resource. Override any field of :class:`CreateVpcOpts` via kwargs.

    Usage::

        def test_x(created_vpc):
            vpc = created_vpc()                      # default name and CIDR
            big = created_vpc(cidr="10.0.0.0/8")     # second VPC
            # No cleanup code in the test - factory took care of it.
    """

    def _factory(**overrides) -> Vpc:
        defaults = {
            "name": unique_name("sdk-test-vpc"),
            "cidr": "192.168.0.0/16",
        }
        opts = CreateVpcOpts(**{**defaults, **overrides})
        vpc = create(vpc_client, opts)
        cleanup(_safe_delete, vpc_client, vpc.id)
        return vpc

    return _factory
