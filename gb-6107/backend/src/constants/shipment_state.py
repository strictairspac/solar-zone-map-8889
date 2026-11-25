class ShipmentState:
    PENDING = "pending"
    ALLOCATED = "allocated"
    CONFIRMED = "confirmed"
    SHORTAGE = "shortage"
    REVOKED = "revoked"
    CANCELLED = "cancelled"


# 这些状态仍然占用板件。保留 confirmed/active 别名，便于对接不同命名的调用方。
ACTIVE_SHIPMENT_STATUSES = frozenset({
    ShipmentState.ALLOCATED,
    ShipmentState.CONFIRMED,
    "active",
})

# 这些状态已经释放板件；历史分配行仍保留用于回执。
RELEASED_SHIPMENT_STATUSES = frozenset({
    ShipmentState.REVOKED,
    ShipmentState.CANCELLED,
    "canceled",
    "released",
})
