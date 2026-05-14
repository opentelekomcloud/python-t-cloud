"""VPC service, API v1.

Resources are exposed as submodules. Usage::

    from sdk.services.vpc.v1 import vpcs

    new_vpc = vpcs.create(client, vpcs.CreateVpcOpts(name="my-vpc"))
    for v in vpcs.list(client):
        print(v.id, v.name)

Future resources (subnets, peerings, ...) are added as sibling submodules.
"""

from __future__ import annotations

from . import vpcs

__all__ = ["vpcs"]
