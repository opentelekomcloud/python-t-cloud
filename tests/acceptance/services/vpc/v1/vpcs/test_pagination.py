"""Acceptance test: VPC v1 marker-based pagination over the real API.

Creates several VPCs and verifies that ``list_vpcs(limit=2)`` walks
through every page and returns all of them. Robust against other VPCs
that may already exist in the tenant: the test only checks that its
own resources are present in the result, not the total count.
"""

from __future__ import annotations

from sdk.services.vpc.v1.vpcs import ListVpcsOpts, list as list_vpcs

from tests.acceptance.conftest import unique_name


NUM_VPCS = 3
PAGE_SIZE = 2


def test_pagination_walks_all_pages(vpc_client, created_vpc):
    created = [
        created_vpc(
            name=unique_name("sdk-pagination-test"),
            cidr=f"192.168.{i}.0/24",
        )
        for i in range(NUM_VPCS)
    ]
    expected_ids = {vpc.id for vpc in created}

    all_vpcs = list(list_vpcs(vpc_client, ListVpcsOpts(limit=PAGE_SIZE)))
    found_ids = {vpc.id for vpc in all_vpcs}

    missing = expected_ids - found_ids
    assert not missing, (
        f"pagination dropped {len(missing)} of {NUM_VPCS} created VPCs; "
        f"got {len(found_ids)} total, missing ids: {sorted(missing)}"
    )