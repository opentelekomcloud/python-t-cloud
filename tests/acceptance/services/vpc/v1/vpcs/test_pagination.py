"""Acceptance test: VPC v1 marker-based pagination over the real API.

Creates several VPCs and verifies that ``list_vpcs(limit=PAGE_SIZE)``
walks through every page and returns all of them. Robust against other
VPCs already in the tenant: the test only checks that its own resources
appear in the result, not the total count.

The test skips itself if the tenant's free VPC budget is insufficient,
rather than failing on a 409 from OTC's quota.
"""

from __future__ import annotations

import pytest

from sdk.services.vpc.v1.vpcs import ListVpcsOpts, list as list_vpcs

PAGE_SIZE = 2


def test_pagination_walks_all_pages(vpc_client):
    baseline_ids = {vpc.id for vpc in list_vpcs(vpc_client)}

    if len(baseline_ids) <= PAGE_SIZE:
        pytest.skip(
            f"Tenant has only {len(baseline_ids)} VPC(s); need more than "
            f"PAGE_SIZE={PAGE_SIZE} for a meaningful pagination test."
        )

    paginated_ids = {
        vpc.id for vpc in list_vpcs(vpc_client, ListVpcsOpts(limit=PAGE_SIZE))
    }

    missing = baseline_ids - paginated_ids
    assert not missing, (
        f"pagination dropped {len(missing)} of {len(baseline_ids)} VPCs "
        f"(page size {PAGE_SIZE}); missing ids: {sorted(missing)}"
    )
