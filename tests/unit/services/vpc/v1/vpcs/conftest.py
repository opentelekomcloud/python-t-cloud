"""VPC-specific fixtures for vpcs unit tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def vpc_payload():
    """Minimal valid VPC payload as returned by the OTC API."""
    return {
        "id": "vpc-id-1",
        "name": "test-vpc",
        "description": "",
        "cidr": "192.168.0.0/16",
        "status": "OK",
        "enterprise_project_id": "0",
        "routes": [],
        "enable_shared_snat": False,
        "tenant_id": "tenant-1",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }


@pytest.fixture
def vpc_response(vpc_payload):
    """Full API response wrapping the VPC payload."""
    return {"vpc": vpc_payload}