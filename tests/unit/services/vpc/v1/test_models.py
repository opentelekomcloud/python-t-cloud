"""Tests for ``sdk.services.vpc.v1.models``."""

from sdk.services.vpc.v1.models import (
    CreateVpcOpts,
    ListVpcsOpts,
    Route,
    UpdateVpcOpts,
    Vpc,
)


# ======================================================================
# Vpc response model
# ======================================================================


class TestVpc:
    """Tests for Vpc model parsing."""

    SAMPLE_RESPONSE = {
        "id": "99d9d709-8478-4b46-9f3f-2206b1023fd3",
        "name": "vpc",
        "description": "test",
        "cidr": "192.168.0.0/16",
        "status": "OK",
        "enterprise_project_id": "0",
        "routes": [],
        "enable_shared_snat": False,
        "tenant_id": "087679f0aa80d32a2f4ec0172f5e902b",
        "created_at": "2022-12-15T02:25:11",
        "updated_at": "2022-12-15T02:25:11",
    }

    def test_parse_full_response(self):
        vpc = Vpc.model_validate(self.SAMPLE_RESPONSE)
        assert vpc.id == "99d9d709-8478-4b46-9f3f-2206b1023fd3"
        assert vpc.name == "vpc"
        assert vpc.description == "test"
        assert vpc.cidr == "192.168.0.0/16"
        assert vpc.status == "OK"
        assert vpc.enterprise_project_id == "0"
        assert vpc.routes == []
        assert vpc.enable_shared_snat is False
        assert vpc.tenant_id == "087679f0aa80d32a2f4ec0172f5e902b"
        assert vpc.created_at == "2022-12-15T02:25:11"
        assert vpc.updated_at == "2022-12-15T02:25:11"

    def test_parse_with_routes(self):
        data = {
            **self.SAMPLE_RESPONSE,
            "routes": [
                {"destination": "10.0.0.0/8", "nexthop": "192.168.0.1"},
                {"destination": "172.16.0.0/12", "nexthop": "192.168.0.2"},
            ],
        }
        vpc = Vpc.model_validate(data)
        assert len(vpc.routes) == 2
        assert vpc.routes[0].destination == "10.0.0.0/8"
        assert vpc.routes[0].nexthop == "192.168.0.1"
        assert vpc.routes[1].destination == "172.16.0.0/12"

    def test_parse_creating_status(self):
        data = {**self.SAMPLE_RESPONSE, "status": "CREATING"}
        vpc = Vpc.model_validate(data)
        assert vpc.status == "CREATING"

    def test_minimal_response(self):
        """API always returns id; other fields have defaults."""
        vpc = Vpc.model_validate({"id": "abc-123"})
        assert vpc.id == "abc-123"
        assert vpc.name == ""
        assert vpc.routes == []
        assert vpc.enable_shared_snat is False


# ======================================================================
# Route model
# ======================================================================


class TestRoute:
    def test_route_defaults(self):
        r = Route()
        assert r.destination == ""
        assert r.nexthop == ""

    def test_route_from_dict(self):
        r = Route.model_validate(
            {"destination": "10.0.0.0/8", "nexthop": "192.168.0.1"}
        )
        assert r.destination == "10.0.0.0/8"
        assert r.nexthop == "192.168.0.1"


# ======================================================================
# CreateVpcOpts
# ======================================================================


class TestCreateVpcOpts:
    def test_full_body(self):
        opts = CreateVpcOpts(
            name="my-vpc",
            description="test vpc",
            cidr="192.168.0.0/16",
            enterprise_project_id="0aad99bc-f5f6-4f78-8404-c598d76b0ed2",
        )
        body = opts.to_request_body()
        assert body == {
            "vpc": {
                "name": "my-vpc",
                "description": "test vpc",
                "cidr": "192.168.0.0/16",
                "enterprise_project_id": "0aad99bc-f5f6-4f78-8404-c598d76b0ed2",
            }
        }

    def test_minimal_body(self):
        """Empty opts => empty vpc dict (all fields optional)."""
        opts = CreateVpcOpts()
        body = opts.to_request_body()
        assert body == {"vpc": {}}

    def test_partial_body(self):
        opts = CreateVpcOpts(name="test", cidr="10.0.0.0/8")
        body = opts.to_request_body()
        assert body == {"vpc": {"name": "test", "cidr": "10.0.0.0/8"}}


# ======================================================================
# UpdateVpcOpts
# ======================================================================


class TestUpdateVpcOpts:
    def test_full_body(self):
        opts = UpdateVpcOpts(
            name="vpc1",
            description="updated",
            cidr="192.168.0.0/16",
            routes=[Route(destination="10.0.0.0/8", nexthop="192.168.0.1")],
        )
        body = opts.to_request_body()
        assert body == {
            "vpc": {
                "name": "vpc1",
                "description": "updated",
                "cidr": "192.168.0.0/16",
                "routes": [
                    {"destination": "10.0.0.0/8", "nexthop": "192.168.0.1"}
                ],
            }
        }

    def test_empty_routes_list(self):
        """Explicitly passing empty list clears routes."""
        opts = UpdateVpcOpts(routes=[])
        body = opts.to_request_body()
        assert body == {"vpc": {"routes": []}}

    def test_none_routes_omitted(self):
        """routes=None means don't update routes."""
        opts = UpdateVpcOpts(name="new-name")
        body = opts.to_request_body()
        assert body == {"vpc": {"name": "new-name"}}
        assert "routes" not in body["vpc"]

    def test_empty_body(self):
        opts = UpdateVpcOpts()
        body = opts.to_request_body()
        assert body == {"vpc": {}}


# ======================================================================
# ListVpcsOpts
# ======================================================================


class TestListVpcsOpts:
    def test_full_params(self):
        opts = ListVpcsOpts(
            id="abc",
            limit=10,
            marker="xyz",
            enterprise_project_id="0",
        )
        params = opts.to_query_params()
        assert params == {
            "id": "abc",
            "limit": "10",
            "marker": "xyz",
            "enterprise_project_id": "0",
        }

    def test_empty_params(self):
        opts = ListVpcsOpts()
        params = opts.to_query_params()
        assert params == {}

    def test_partial_params(self):
        opts = ListVpcsOpts(limit=50)
        params = opts.to_query_params()
        assert params == {"limit": "50"}
