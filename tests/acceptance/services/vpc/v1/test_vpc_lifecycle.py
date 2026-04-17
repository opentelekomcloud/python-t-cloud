"""VPC v1 acceptance test — full lifecycle against real OTC.

Runs: create → get → list → update → delete

Requirements:
    - A valid clouds.yaml file (in ./, ~/.config/openstack/, or /etc/openstack/)
    - Network access to OTC API

Usage::

    # Default cloud name is 'otc', but you can override it:
    export OS_CLOUD="my-dev-env"

    # Run the tests with output (-s):
    uv run pytest tests/acceptance/services/vpc/ -v -s
"""

from __future__ import annotations

import os
import uuid
import logging
import pytest
from collections.abc import Iterator
from sdk.core.config import load_from_yaml
from sdk.core.exceptions import HttpError
from sdk.core.provider import ProviderClient
from sdk.core.service_client import ServiceClient
from sdk.core.waiter import wait_for, wait_for_delete
from sdk.services.vpc.v1 import requests as vpc
from sdk.services.vpc.v1.models import CreateVpcOpts, ListVpcsOpts, UpdateVpcOpts


logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def vpc_client() -> Iterator[ServiceClient]:
    cloud_name = os.environ.get("OS_CLOUD", "otc")
    config = load_from_yaml(cloud_name)

    provider = ProviderClient(config)
    provider.authenticate()
    yield ServiceClient(provider, service_type="vpc")
    provider.close()


def test_vpc_lifecycle(vpc_client: ServiceClient) -> None:
    """Full CRUD lifecycle: create → get → list → update → delete.

    Creates a VPC with a unique name, verifies all operations
    work against the real API, then cleans up.
    """
    unique = uuid.uuid4().hex[:8]
    vpc_name = f"sdk-test-{unique}"
    vpc_id: str | None = None

    try:
        # ── Create ──────────────────────────────────────────
        created = vpc.create(
            vpc_client,
            CreateVpcOpts(
                name=vpc_name,
                cidr="192.168.0.0/16",
                description="acceptance test vpc",
            ),
        )
        vpc_id = created.id

        assert created.id, "VPC must have an ID"
        assert created.name == vpc_name
        assert created.cidr == "192.168.0.0/16"
        assert created.status in ("OK", "CREATING", "PENDING")
        logger.info("Created VPC: %s (%s)", created.id, created.name)

        # ── Get ─────────────────────────────────────────────
        fetched = wait_for(
            func=lambda: vpc.get(vpc_client, vpc_id),
            condition=lambda new_vpc: new_vpc.status == "OK",
            label=f"VPC {vpc_id} to be OK"
        )
        assert fetched.status == "OK"
        assert fetched.id == vpc_id
        assert fetched.name == vpc_name
        assert fetched.cidr == "192.168.0.0/16"
        logger.info("Get VPC: %s, status=%s", fetched.id, fetched.status)

        # ── List ────────────────────────────────────────────
        found = False
        for v in vpc.list(vpc_client, ListVpcsOpts(limit=100)):
            if v.id == vpc_id:
                found = True
                break

        assert found, f"Created VPC {vpc_id} not found in list"
        logger.info("List VPCs: found %s in results", vpc_id)

        # ── Update ──────────────────────────────────────────
        new_name = f"sdk-test-updated-{unique}"
        updated = vpc.update(
            vpc_client,
            vpc_id,
            UpdateVpcOpts(
                name=new_name,
                description="updated by acceptance test",
            ),
        )

        assert updated.id == vpc_id
        assert updated.name == new_name
        assert updated.description == "updated by acceptance test"
        logger.info("Updated VPC: name -> %s", updated.name)

        # ── Verify update via get ───────────────────────────
        refetched = vpc.get(vpc_client, vpc_id)
        assert refetched.name == new_name
        logger.info("Verified update via get")

        # ── Delete ──────────────────────────────────────────
        vpc.delete(vpc_client, vpc_id)
        wait_for_delete(
            get_func=lambda: vpc.get(vpc_client, vpc_id),
            label=f"VPC {vpc_id}"
        )
        vpc_id = None
        with pytest.raises(HttpError) as exc_info:
            vpc.get(vpc_client, created.id)

        assert exc_info.value.status_code == 404
        logger.info("Confirmed VPC is gone (404)")

    finally:
        if vpc_id is not None:
            try:
                vpc.delete(vpc_client, vpc_id)
                logger.warning("Cleanup: deleted left-over VPC %s", vpc_id)
            except Exception as exc:
                logger.error("Cleanup failed: %s", exc)