"""VPCs resource (VPC service, v1)."""

from __future__ import annotations

from .common import Route, Vpc
from .create import CreateVpcOpts, create
from .delete import delete
from .get import get
from .list import ListVpcsOpts, list
from .update import UpdateVpcOpts, update

__all__ = [
    "CreateVpcOpts",
    "ListVpcsOpts",
    "Route",
    "UpdateVpcOpts",
    "Vpc",
    "create",
    "delete",
    "get",
    "list",
    "update",
]
