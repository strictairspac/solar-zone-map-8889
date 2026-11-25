from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)

from .base import metadata

shipment_orders = Table(
    "shipment_orders", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("code", String(64), unique=True, nullable=False),
    Column("idempotency_key", String(96), unique=True, nullable=True),
    Column("customer", String(120), nullable=True),
    Column("low_cw", Integer, nullable=False),
    Column("high_cw", Integer, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("page_size", Integer, nullable=False, default=4),
    Column("status", String(20), nullable=False, index=True),
    Column("allocated_serials", JSON, nullable=False, default=list),
    Column("receipt", JSON(none_as_null=True), nullable=True),
    Column("available_count", Integer, nullable=True),
    Column("revoke_reason", String(320), nullable=True),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("allocated_at", BigInteger, nullable=True),
    Column("confirmed_at", BigInteger, nullable=True),
    Column("revoked_at", BigInteger, nullable=True),
)

# 分配历史：撤销只改状态，不删除行，供裁剪回执保留“当时分到的板件”。
shipment_allocations = Table(
    "shipment_allocations", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", ForeignKey("shipment_orders.id"), nullable=False, index=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("serial", String(32), nullable=False),
    Column("page_index", Integer, nullable=True),
    Column("status", String(20), nullable=False, index=True),
    Column("allocated_at", BigInteger, nullable=False),
    Column("revoked_at", BigInteger, nullable=True),
    UniqueConstraint("order_id", "serial", name="uq_shipment_allocation_order_serial"),
)

# 当前有效占用。整表 (case_id, serial) 唯一，是并发下“一板只能被一张未撤销单占用”的最终防线。
shipment_occupancies = Table(
    "shipment_occupancies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False),
    Column("order_id", ForeignKey("shipment_orders.id"), nullable=False, index=True),
    Column("serial", String(32), nullable=False),
    Column("allocated_at", BigInteger, nullable=False),
    UniqueConstraint("case_id", "serial", name="uq_shipment_occupancy_case_serial"),
)

Index(
    "ix_shipment_allocations_case_status",
    shipment_allocations.c.case_id,
    shipment_allocations.c.status,
)
Index(
    "ux_shipment_allocations_active_case_serial",
    shipment_allocations.c.case_id,
    shipment_allocations.c.serial,
    unique=True,
    sqlite_where=(shipment_allocations.c.status.in_(["allocated", "confirmed", "active"])),
    postgresql_where=(shipment_allocations.c.status.in_(["allocated", "confirmed", "active"])),
)
