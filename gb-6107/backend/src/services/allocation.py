"""兼容性别名：部分调用方可能把配货服务命名为 allocation。"""
from src.domain.allocation import (
    AllocationConflict,
    AllocationError,
    AllocationPlan,
    InsufficientStock,
    plan_allocation,
)
from .shipments import (
    allocate_order,
    allocate_shipment,
    create_and_allocate,
    create_order,
    create_shipment,
    get,
    list_entries,
    revoke_order,
    revoke_shipment,
)

__all__ = [
    "AllocationConflict",
    "AllocationError",
    "AllocationPlan",
    "InsufficientStock",
    "plan_allocation",
    "allocate_order",
    "allocate_shipment",
    "create_and_allocate",
    "create_order",
    "create_shipment",
    "get",
    "list_entries",
    "revoke_order",
    "revoke_shipment",
]
