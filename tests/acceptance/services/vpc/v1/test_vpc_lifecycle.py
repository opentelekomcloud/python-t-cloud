"""VPC v1 acceptance test — full lifecycle against real OTC.

Runs: create → get → list → update → delete

Requirements:
    - Real OTC credentials via environment variables
    - Network access to OTC API

Usage::

    # Set credentials (pick ONE auth method):

    # Option A: Password auth
    export OS_IDENTITY_ENDPOINT="https://iam.eu-de.otc.t-systems.com/v3"
    export OS_USERNAME="your_user"
    export OS_PASSWORD="your_pass"
    export OS_DOMAIN_NAME="your_domain"
    export OS_TENANT_NAME="eu-de"
    export OS_REGION="eu-de"

    # Option B: AK/SK auth
    export OS_IDENTITY_ENDPOINT="https://iam.eu-de.otc.t-systems.com/v3"
    export OS_ACCESS_KEY="AK..."
    export OS_SECRET_KEY="SK..."
    export OS_PROJECT_ID="..."
    export OS_REGION="eu-de"

    # Run:
    uv run pytest tests/acceptance/services/vpc/ -v -s
"""

from __future__ import annotations

import os
import uuid

import pytest

from sdk.core.auth import AuthConfig
from sdk.core.provider import ProviderClient
from sdk.core.service_client import ServiceClient
from sdk.services.vpc.v1 import requests as vpc
from sdk.services.vpc.v1.models import CreateVpcOpts, ListVpcsOpts, UpdateVpcOpts


def _auth_config_from_env() -> AuthConfig:
    """Build AuthConfig from OS_* environment variables.

    Supports both password and AK/SK auth — AuthConfig
    auto-detects based on which variables are set.
    """
    kwargs: dict = {
        "identity_endpoint": os.environ["OS_IDENTITY_ENDPOINT"],
    }

    # Password auth fields
    if os.environ.get("OS_USERNAME"):
        kwargs["username"] = os.environ["OS_USERNAME"]
    if os.environ.get("OS_PASSWORD"):
        kwargs["password"] = os.environ["OS_PASSWORD"]
    if os.environ.get("OS_DOMAIN_NAME"):
        kwargs["domain_name"] = os.environ["OS_DOMAIN_NAME"]
    if os.environ.get("OS_TENANT_NAME"):
        kwargs["tenant_name"] = os.environ["OS_TENANT_NAME"]

    # AK/SK auth fields
    if os.environ.get("OS_ACCESS_KEY"):
        kwargs["access_key"] = os.environ["OS_ACCESS_KEY"]
    if os.environ.get("OS_SECRET_KEY"):
        kwargs["secret_key"] = os.environ["OS_SECRET_KEY"]

    # Common fields
    if os.environ.get("OS_PROJECT_ID"):
        kwargs["project_id"] = os.environ["OS_PROJECT_ID"]
    if os.environ.get("OS_REGION"):
        kwargs["region"] = os.environ["OS_REGION"]

    return AuthConfig(**kwargs)


def _skip_if_no_credentials() -> None:
    """Skip test if no OTC credentials are configured."""
    if not os.environ.get("OS_IDENTITY_ENDPOINT"):
        pytest.skip("OS_IDENTITY_ENDPOINT not set — skipping acceptance tests")

    has_password = bool(os.environ.get("OS_PASSWORD"))
    has_aksk = bool(
        os.environ.get("OS_ACCESS_KEY") and os.environ.get("OS_SECRET_KEY")
    )
    if not has_password and not has_aksk:
        pytest.skip("No OTC credentials — set OS_PASSWORD or OS_ACCESS_KEY+OS_SECRET_KEY")


@pytest.fixture(scope="module")
def vpc_client() -> ServiceClient:
    """Authenticate and return a VPC ServiceClient."""
    _skip_if_no_credentials()

    config = _auth_config_from_env()
    provider = ProviderClient(config)
    provider.authenticate()

    return ServiceClient(provider, service_type="vpc")


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
        assert created.status in ("OK", "CREATING")
        print(f"  ✓ Created VPC: {created.id} ({created.name})")

        # ── Get ─────────────────────────────────────────────
        fetched = vpc.get(vpc_client, vpc_id)

        assert fetched.id == vpc_id
        assert fetched.name == vpc_name
        assert fetched.cidr == "192.168.0.0/16"
        print(f"  ✓ Get VPC: {fetched.id}, status={fetched.status}")

        # ── List ────────────────────────────────────────────
        found = False
        for v in vpc.list(vpc_client, ListVpcsOpts(limit=100)):
            if v.id == vpc_id:
                found = True
                break

        assert found, f"Created VPC {vpc_id} not found in list"
        print(f"  ✓ List VPCs: found {vpc_id} in results")

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
        print(f"  ✓ Updated VPC: name → {updated.name}")

        # ── Verify update via get ───────────────────────────
        refetched = vpc.get(vpc_client, vpc_id)
        assert refetched.name == new_name
        print(f"  ✓ Verified update via get")

        # ── Delete ──────────────────────────────────────────
        vpc.delete(vpc_client, vpc_id)
        print(f"  ✓ Deleted VPC: {vpc_id}")
        vpc_id = None  # mark as cleaned up

        # ── Verify deletion ─────────────────────────────────
        # Get should raise 404
        with pytest.raises(Exception):
            vpc.get(vpc_client, created.id)
        print(f"  ✓ Confirmed VPC is gone (404)")

    finally:
        # Cleanup: delete VPC if test failed mid-way
        if vpc_id is not None:
            try:
                vpc.delete(vpc_client, vpc_id)
                print(f"  ⚠ Cleanup: deleted VPC {vpc_id}")
            except Exception as exc:
                print(f"  ⚠ Cleanup failed: {exc}")
