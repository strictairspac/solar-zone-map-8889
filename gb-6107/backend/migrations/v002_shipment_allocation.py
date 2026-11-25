"""出货单分板与当前板件占用。

新增表全部是 additive：旧的 cases/runs/reviews 表不变。v001 的
``metadata.create_all`` 在新库会直接建出最新表；本迁移负责让已存在的 v001
数据库也显式补齐出货单相关表和唯一占用索引。
"""
from src.models import shipments  # noqa: F401  注册表结构
from src.models.base import metadata
from src.models.shipments import (
    shipment_allocations,
    shipment_occupancies,
    shipment_orders,
)


def upgrade(connection):
    metadata.create_all(
        connection,
        tables=[shipment_orders, shipment_allocations, shipment_occupancies],
        checkfirst=True,
    )
