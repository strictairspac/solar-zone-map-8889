"""兼容不同命名：出货单领域逻辑也可从 src.domain.shipment 导入。"""
from .allocation import *  # noqa: F401,F403
from .allocation import (
    AllocationPlan,
    allocate_boards,
    allocate_panels,
    plan_allocation,
    plan_shipment,
)

__all__ = [
    "AllocationPlan",
    "plan_allocation",
    "allocate_panels",
    "allocate_boards",
    "plan_shipment",
]
