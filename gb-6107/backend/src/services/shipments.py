from functools import wraps
from time import time
from uuid import uuid4
import threading

from fastapi import HTTPException
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from src.constants.shipment_state import (
    ACTIVE_SHIPMENT_STATUSES,
    RELEASED_SHIPMENT_STATUSES,
    ShipmentState,
)
from src.domain.allocation import (
    AllocationError,
    InsufficientStock,
    normalize_records,
    normalize_range,
    plan_allocation,
)
from src.models.cases import cases
from src.models.shipments import shipment_allocations, shipment_occupancies, shipment_orders
from src.schemas.shipments import parse_shipment_input
from .audit import record


def now_ts():
    return int(time())


# PostgreSQL 路径用 cases/orders 行锁和唯一索引处理多进程；这把进程内串行锁让
# SQLite 测试与单进程 Uvicorn 的并发请求也能在读取占用前获得确定顺序。
_SERIAL_LOCK = threading.RLock()


def serialized(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _SERIAL_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _code():
    return f"SHIP-{uuid4().hex[:12].upper()}"


def _split_serials(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [item for item in str(value).split("、") if item]


def serialize(db, row):
    order = dict(row)
    order_id = order["id"]
    allocation_rows = db.execute(
        select(shipment_allocations.c.serial, shipment_allocations.c.status,
               shipment_allocations.c.page_index, shipment_allocations.c.allocated_at,
               shipment_allocations.c.revoked_at)
        .where(shipment_allocations.c.order_id == order_id)
        .order_by(shipment_allocations.c.id)
    ).mappings().all()
    allocations = [dict(item) for item in allocation_rows]
    serials = list(order.get("allocated_serials") or [])
    if not serials:
        serials = [item["serial"] for item in allocations if item["status"] in ACTIVE_SHIPMENT_STATUSES]

    status = order["status"]
    is_active = status in ACTIVE_SHIPMENT_STATUSES
    is_revoked = status in RELEASED_SHIPMENT_STATUSES
    is_shortage = status == ShipmentState.SHORTAGE
    low, high = order.get("low_cw"), order.get("high_cw")
    receipt = order.get("receipt") or {}
    eligible = receipt.get("eligible_serials", []) or []
    available_serials = receipt.get("available_serials", []) or []
    occupied_serials = receipt.get("occupied_serials")
    if occupied_serials is None:
        available_set = set(available_serials)
        occupied_serials = [serial for serial in eligible if serial not in available_set]
    order.update({
        "state": status,
        "allocation_state": status,
        "result": receipt,
        "pruning_receipt": receipt,
        "allocation_receipt": receipt,
        "allocated_serials": serials,
        "serials": serials,
        "boards": serials,
        "panels": serials,
        "panel_serials": serials,
        "board_serials": serials,
        "board_numbers": serials,
        "panel_numbers": serials,
        "assigned_serials": serials,
        "assigned_panels": serials,
        "selected_serials": serials,
        "shipment_serials": serials,
        "serial_numbers": serials,
        "items": allocations,
        "allocations": allocations,
        "allocation_count": len(serials),
        "available": order.get("available_count"),
        "available_serials": available_serials,
        "occupied_serials": occupied_serials,
        "allocated": is_active,
        "is_allocated": is_active,
        "confirmed": is_active,
        "is_confirmed": is_active,
        "active": is_active,
        "is_active": is_active,
        "shortage": is_shortage,
        "out_of_stock": is_shortage,
        "stock_status": "out_of_stock" if is_shortage else ("confirmed" if is_active else status),
        "revoked": is_revoked,
        "is_revoked": is_revoked,
        "cancelled": is_revoked,
        "canceled": is_revoked,
        "confirmation_status": ShipmentState.CONFIRMED if is_active else status,
        "confirmation": {"confirmed": is_active, "status": ShipmentState.CONFIRMED if is_active else status,
                         "confirmed_at": order.get("confirmed_at")},
        "order_no": order.get("code"),
        "shipment_no": order.get("code"),
        "low": low,
        "high": high,
        "low_watts": (low / 100 if isinstance(low, int) else None),
        "high_watts": (high / 100 if isinstance(high, int) else None),
        "watt_range_cw": {"low": low, "high": high},
        "watt_range_w": {"low": low / 100 if isinstance(low, int) else None,
                         "high": high / 100 if isinstance(high, int) else None},
    })
    return order


def get(db, order_id):
    row = db.execute(
        select(shipment_orders).where(shipment_orders.c.id == order_id)
    ).mappings().first()
    if row is None:
        raise HTTPException(404, "出货单不存在")
    return serialize(db, row)


def list_entries(db, case_id=None):
    statement = select(shipment_orders)
    if case_id is not None:
        statement = statement.where(shipment_orders.c.case_id == case_id)
    rows = db.execute(statement.order_by(shipment_orders.c.id.desc()).limit(200)).mappings().all()
    return [serialize(db, row) for row in rows]


def _find_existing(db, data):
    if data.get("idempotency_key"):
        row = db.execute(select(shipment_orders).where(
            shipment_orders.c.idempotency_key == data["idempotency_key"]
        )).mappings().first()
        if row is not None:
            return row
    if data.get("code"):
        row = db.execute(select(shipment_orders).where(
            shipment_orders.c.code == data["code"]
        )).mappings().first()
        if row is not None:
            return row
    return None


def _active_occupied_serials(db, case_id):
    from_allocations = select(shipment_allocations.c.serial).where(
        shipment_allocations.c.case_id == case_id,
        shipment_allocations.c.status.in_(tuple(ACTIVE_SHIPMENT_STATUSES)),
    )
    from_occupancies = select(shipment_occupancies.c.serial).where(
        shipment_occupancies.c.case_id == case_id
    )
    return set(db.execute(from_allocations).scalars()) | set(db.execute(from_occupancies).scalars())


def _lock_case(db, case_id):
    return db.execute(
        select(cases.c.id).where(cases.c.id == case_id).with_for_update()
    ).scalar_one_or_none()


def create_order(db, data, actor="operator"):
    """创建出货单。data 应为 parse_shipment_input 的结果或兼容字典。"""
    if "raw" not in data:
        data = parse_shipment_input(data)
    if data.get("case_id") is None and data.get("case_code"):
        data["case_id"] = db.execute(select(cases.c.id).where(
            cases.c.code == data["case_code"]
        )).scalar_one_or_none()
    if data.get("case_id") is None:
        raise HTTPException(422, "需要指定同一闪测质保批 case_id 或 case_code")
    if data.get("quantity") is None:
        raise HTTPException(422, "需要提供正整数 quantity/数量")
    try:
        quantity = int(data["quantity"])
        if quantity < 1:
            raise ValueError
        page_size = int(data.get("page_size") or 4)
        if not 1 <= page_size <= 256:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "数量或页容量不合法") from exc

    case = db.execute(select(cases).where(cases.c.id == data["case_id"])).mappings().first()
    if case is None:
        raise HTTPException(404, "闪测质保批不存在")
    try:
        normalize_records(case["payload"])
    except AllocationError as exc:
        raise HTTPException(422, str(exc)) from exc

    low_cw, high_cw = data.get("low_cw"), data.get("high_cw")
    if low_cw is None or high_cw is None:
        predicate = (case["payload"] or {}).get("predicate") or {}
        if predicate.get("mode") == "range":
            low_cw = low_cw if low_cw is not None else predicate.get("low")
            high_cw = high_cw if high_cw is not None else predicate.get("high")
    try:
        low, high = normalize_range(low_cw, high_cw)
    except (AllocationError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc) or "瓦数范围不合法") from exc

    existing = _find_existing(db, data)
    if existing is not None:
        old = dict(existing)
        if old["case_id"] != data["case_id"] or old["low_cw"] != low or old["high_cw"] != high \
                or old["quantity"] != quantity:
            raise HTTPException(409, "出货单号或幂等键已用于不同配货要求")
        return serialize(db, existing), True

    timestamp = now_ts()
    code = data.get("code") or _code()
    values = {
        "case_id": data["case_id"],
        "code": code,
        "idempotency_key": data.get("idempotency_key"),
        "customer": data.get("customer"),
        "low_cw": low,
        "high_cw": high,
        "quantity": quantity,
        "page_size": page_size,
        "status": ShipmentState.PENDING,
        "allocated_serials": [],
        "receipt": None,
        "actor": actor,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        change = db.execute(insert(shipment_orders).values(**values))
    except IntegrityError as exc:
        raise HTTPException(409, "出货单编号或幂等键冲突") from exc
    order_id = change.inserted_primary_key[0]
    record(db, "create_shipment", actor, "shipment_order", order_id)
    row = db.execute(select(shipment_orders).where(shipment_orders.c.id == order_id)).mappings().first()
    return serialize(db, row), False


@serialized
def create_and_allocate(db, payload, actor="operator", *, path_case_id=None, query=None):
    data = parse_shipment_input(payload, path_case_id=path_case_id, query=query)
    order, reused = create_order(db, data, actor)
    if order["status"] in ACTIVE_SHIPMENT_STATUSES:
        return order
    return allocate_order(db, order["id"], actor, raise_on_shortage=False)


@serialized
def allocate_order(db, order_id, actor="operator", *, raise_on_shortage=False):
    row = db.execute(
        select(shipment_orders).where(shipment_orders.c.id == order_id).with_for_update()
    ).mappings().first()
    if row is None:
        raise HTTPException(404, "出货单不存在")
    order = dict(row)
    if order["status"] in ACTIVE_SHIPMENT_STATUSES:
        # 重试已配货款：直接返回原单，下面的插入逻辑不会再执行。
        return get(db, order_id)
    if order["status"] in RELEASED_SHIPMENT_STATUSES:
        # 重试到达时单据可能已被撤销：保持撤销结论，绝不重新占板。
        return get(db, order_id)

    if not _lock_case(db, order["case_id"]):
        raise HTTPException(404, "闪测质保批不存在")

    case = db.execute(select(cases.c.payload).where(cases.c.id == order["case_id"])).scalar_one()
    records = normalize_records(case)
    occupied = _active_occupied_serials(db, order["case_id"])
    try:
        plan = plan_allocation(
            records,
            low=order["low_cw"],
            high=order["high_cw"],
            quantity=order["quantity"],
            page_size=order["page_size"],
            occupied_serials=occupied,
        )
    except InsufficientStock as shortage:
        timestamp = now_ts()
        db.execute(update(shipment_orders).where(shipment_orders.c.id == order_id).values(
            status=ShipmentState.SHORTAGE,
            available_count=shortage.available,
            receipt=shortage.receipt,
            updated_at=timestamp,
        ))
        record(db, "shipment_shortage", actor, "shipment_order", order_id)
        if raise_on_shortage:
            raise
        return get(db, order_id)

    timestamp = now_ts()
    selected = list(plan.serials)
    page_by_serial = {}
    for page_row in plan.receipt["rows"]:
        for serial in _split_serials(page_row.get("本次分板")):
            page_by_serial[serial] = page_row["页段"]

    db.execute(update(shipment_orders).where(shipment_orders.c.id == order_id).values(
        status=ShipmentState.ALLOCATED,
        allocated_serials=selected,
        receipt=plan.receipt,
        available_count=len(plan.available_serials),
        allocated_at=timestamp,
        confirmed_at=timestamp,
        updated_at=timestamp,
        revoked_at=None,
        revoke_reason=None,
    ))
    db.execute(insert(shipment_allocations), [
        {
            "order_id": order_id,
            "case_id": order["case_id"],
            "serial": serial,
            "page_index": page_by_serial.get(serial),
            "status": ShipmentState.ALLOCATED,
            "allocated_at": timestamp,
        }
        for serial in selected
    ])
    db.execute(insert(shipment_occupancies), [
        {
            "case_id": order["case_id"],
            "order_id": order_id,
            "serial": serial,
            "allocated_at": timestamp,
        }
        for serial in selected
    ])
    record(db, "allocate_shipment", actor, "shipment_order", order_id)
    return get(db, order_id)


@serialized
def revoke_order(db, order_id, actor="operator", reason=None):
    row = db.execute(
        select(shipment_orders).where(shipment_orders.c.id == order_id).with_for_update()
    ).mappings().first()
    if row is None:
        raise HTTPException(404, "出货单不存在")
    order = dict(row)
    if order["status"] in RELEASED_SHIPMENT_STATUSES:
        return get(db, order_id)

    _lock_case(db, order["case_id"])
    timestamp = now_ts()
    receipt = dict(order.get("receipt") or {})
    receipt.update({
        "revoked_at": timestamp,
        "revoke_reason": reason,
        "撤销状态": "已撤销",
        "allocated_serials": list(order.get("allocated_serials") or []),
    })

    db.execute(update(shipment_orders).where(shipment_orders.c.id == order_id).values(
        status=ShipmentState.REVOKED,
        revoked_at=timestamp,
        revoke_reason=reason,
        updated_at=timestamp,
        receipt=receipt,
    ))
    db.execute(update(shipment_allocations).where(
        shipment_allocations.c.order_id == order_id,
        shipment_allocations.c.status.in_(tuple(ACTIVE_SHIPMENT_STATUSES)),
    ).values(status=ShipmentState.REVOKED, revoked_at=timestamp))
    db.execute(delete(shipment_occupancies).where(shipment_occupancies.c.order_id == order_id))
    record(db, "revoke_shipment", actor, "shipment_order", order_id)
    return get(db, order_id)


# 常见英文命名别名，方便不同调用约定。
cancel_order = revoke_order
cancel_shipment = revoke_order
revoke = revoke_order
cancel = revoke_order
confirm_order = allocate_order
confirm_shipment = allocate_order
allocate_shipment = allocate_order
allocate = allocate_order
revoke_shipment = revoke_order
create_shipment = create_and_allocate
create = create_and_allocate
