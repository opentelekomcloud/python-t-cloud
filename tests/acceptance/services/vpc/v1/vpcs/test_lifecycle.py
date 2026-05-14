"""Acceptance test: VPC v1 full lifecycle against a real OTC tenant.

Covers create -> get -> list -> update -> delete -> get-after-delete.
Skipped automatically when ``clouds.yaml`` does not provide credentials
for the configured cloud (``OS_CLOUD``, default ``otc``).
"""

from __future__ import annotations

import pytest

from sdk.core.exceptions import HttpError
from sdk.services.vpc.v1.vpcs import (
    UpdateVpcOpts,
    delete,
    get,
    list as list_vpcs,
    update,
)

from tests.acceptance.conftest import unique_name


def test_full_lifecycle(vpc_client, created_vpc):
    initial_cidr = "192.168.0.0/16"
    vpc = created_vpc(description="initial", cidr=initial_cidr)

    # --- Create result ---
    assert vpc.id, "server must return an id"
    assert vpc.cidr == initial_cidr
    assert vpc.description == "initial"
    # Status right after create is typically CREATING or OK depending
    # on backend; both are valid, just verify it was set.
    assert vpc.status, "status must be populated"

    # --- Get ---
    fetched = get(vpc_client, vpc.id)
    assert fetched.id == vpc.id
    assert fetched.name == vpc.name
    assert fetched.cidr == initial_cidr
    assert fetched.description == "initial"

    # --- List: the new VPC must appear ---
    found = next(
        (v for v in list_vpcs(vpc_client) if v.id == vpc.id),
        None,
    )
    assert found is not None, "newly created VPC missing from list"
    assert found.name == vpc.name

    # --- Update: rename and change description ---
    new_name = unique_name("sdk-test-vpc-renamed")
    updated = update(
        vpc_client,
        vpc.id,
        UpdateVpcOpts(name=new_name, description="updated"),
    )
    assert updated.id == vpc.id
    assert updated.name == new_name
    assert updated.description == "updated"

    # Re-fetch to confirm the change was persisted, not just echoed back.
    refetched = get(vpc_client, vpc.id)
    assert refetched.name == new_name
    assert refetched.description == "updated"

    # --- Delete ---
    delete(vpc_client, vpc.id)

    # --- Get-after-delete: must 404 ---
    with pytest.raises(HttpError) as exc_info:
        get(vpc_client, vpc.id)
    assert exc_info.value.status_code == 404
