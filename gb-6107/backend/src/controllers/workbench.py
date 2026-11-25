from fastapi import HTTPException
from redis.exceptions import RedisError
from src.config.resources import cache, engine
from src.services import cases, runs, reviews, shipments


def new_case(data, user):
    with engine.begin() as db:
        return cases.create(db, data, user["username"])


def new_run(case_id, data, user):
    with engine.begin() as db:
        run = runs.enqueue(db, case_id, data.parameter, user["username"])
    try:
        cache.lpush("workbench:wake", str(run["id"]))
        cache.ltrim("workbench:wake", 0, 99)
    except RedisError:
        # The database holds the durable queue. The worker also polls it.
        pass
    return run


def new_review(run_id, data, user):
    with engine.begin() as db:
        return reviews.sign(db, run_id, data, user["username"])


@shipments.serialized
def create_shipment(data, user, case_id=None, query=None):
    # 锁必须覆盖事务提交，避免 SQLite 下一个线程在释放进程锁后、提交前读到旧占用。
    try:
        with engine.begin() as db:
            return shipments.create_and_allocate(
                db, data, user["username"], path_case_id=case_id, query=query
            )
    except ValueError as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, str(exc) or "出货单参数不合法") from exc


@shipments.serialized
def allocate_shipment(order_id, user):
    with engine.begin() as db:
        return shipments.allocate_order(db, order_id, user["username"])


@shipments.serialized
def revoke_shipment(order_id, data, user):
    reason = None
    if isinstance(data, dict):
        reason = data.get("reason") or data.get("revoke_reason") or data.get("note")
    with engine.begin() as db:
        return shipments.revoke_order(db, order_id, user["username"], reason=reason)
