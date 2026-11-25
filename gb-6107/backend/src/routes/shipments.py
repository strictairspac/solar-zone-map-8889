from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from src.config.resources import engine
from src.controllers.access import identity, operator
from src.controllers.workbench import (
    allocate_shipment as allocate_shipment_transaction,
    create_shipment as create_shipment_transaction,
    revoke_shipment as revoke_shipment_transaction,
)
from src.services import shipments

router = APIRouter(tags=["Shipments"])


async def _body(request: Request):
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            value = await request.json()
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def _shortage_aware(order, created=False):
    content = jsonable_encoder(order)
    if order.get("status") == "shortage":
        content = jsonable_encoder(order)
        content["detail"] = (
            f"库存不足：需要 {order.get('quantity')} 块，"
            f"当前可用 {order.get('available_count', 0)} 块，本单未占板"
        )
        return JSONResponse(status_code=409, content=content)
    return JSONResponse(status_code=201 if created else 200, content=content)


@router.get("/shipments", dependencies=[Depends(identity)])
@router.get("/shipment-orders", dependencies=[Depends(identity)])
@router.get("/shipment_orders", dependencies=[Depends(identity)])
@router.get("/orders", dependencies=[Depends(identity)])
@router.get("/allocation-orders", dependencies=[Depends(identity)])
@router.get("/allocation_orders", dependencies=[Depends(identity)])
@router.get("/shipping-orders", dependencies=[Depends(identity)])
@router.get("/allocations", dependencies=[Depends(identity)])
def list_shipments(request: Request):
    case_id = request.query_params.get("case_id") or request.query_params.get("batch_id")
    with engine.connect() as db:
        return shipments.list_entries(db, int(case_id) if case_id else None)


@router.get("/cases/{case_id}/shipments", dependencies=[Depends(identity)])
@router.get("/cases/{case_id}/shipment-orders", dependencies=[Depends(identity)])
@router.get("/cases/{case_id}/shipment_orders", dependencies=[Depends(identity)])
@router.get("/cases/{case_id}/allocations", dependencies=[Depends(identity)])
def list_case_shipments(case_id: int):
    with engine.connect() as db:
        return shipments.list_entries(db, case_id)


@router.post("/shipments", dependencies=[Depends(operator)])
@router.post("/shipment-orders", dependencies=[Depends(operator)])
@router.post("/shipment_orders", dependencies=[Depends(operator)])
@router.post("/allocations", dependencies=[Depends(operator)])
@router.post("/allocation", dependencies=[Depends(operator)])
@router.post("/orders", dependencies=[Depends(operator)])
@router.post("/allocation-orders", dependencies=[Depends(operator)])
@router.post("/allocation_orders", dependencies=[Depends(operator)])
@router.post("/shipping-orders", dependencies=[Depends(operator)])
async def create_shipment(request: Request, user=Depends(operator)):
    body = await _body(request)
    header_key = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
    if header_key:
        body.setdefault("idempotency_key", header_key)
    order = create_shipment_transaction(body, user, query=dict(request.query_params))
    return _shortage_aware(order, created=True)


@router.post("/cases/{case_id}/shipments", dependencies=[Depends(operator)])
@router.post("/cases/{case_id}/shipment-orders", dependencies=[Depends(operator)])
@router.post("/cases/{case_id}/shipment_orders", dependencies=[Depends(operator)])
@router.post("/cases/{case_id}/allocations", dependencies=[Depends(operator)])
@router.post("/cases/{case_id}/allocate", dependencies=[Depends(operator)])
async def create_case_shipment(case_id: int, request: Request, user=Depends(operator)):
    body = await _body(request)
    header_key = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
    if header_key:
        body.setdefault("idempotency_key", header_key)
    order = create_shipment_transaction(
        body, user, case_id=case_id, query=dict(request.query_params)
    )
    return _shortage_aware(order, created=True)


@router.get("/shipments/{order_id}", dependencies=[Depends(identity)])
@router.get("/shipment-orders/{order_id}", dependencies=[Depends(identity)])
@router.get("/shipment_orders/{order_id}", dependencies=[Depends(identity)])
@router.get("/allocations/{order_id}", dependencies=[Depends(identity)])
@router.get("/orders/{order_id}", dependencies=[Depends(identity)])
@router.get("/allocation-orders/{order_id}", dependencies=[Depends(identity)])
@router.get("/allocation_orders/{order_id}", dependencies=[Depends(identity)])
def shipment_detail(order_id: int):
    with engine.connect() as db:
        return shipments.get(db, order_id)


@router.get("/shipments/{order_id}/receipt", dependencies=[Depends(identity)])
@router.get("/shipment-orders/{order_id}/receipt", dependencies=[Depends(identity)])
@router.get("/allocations/{order_id}/receipt", dependencies=[Depends(identity)])
def shipment_receipt(order_id: int):
    with engine.connect() as db:
        order = shipments.get(db, order_id)
        return {"order": order, "receipt": order.get("receipt"), "status": order["status"],
                "allocated_serials": order["allocated_serials"], "revoked": order["revoked"]}


def _allocate_response(order_id, user):
    order = allocate_shipment_transaction(order_id, user)
    return _shortage_aware(order)


@router.post("/shipments/{order_id}/allocate", dependencies=[Depends(operator)])
@router.post("/shipments/{order_id}/confirm", dependencies=[Depends(operator)])
@router.post("/shipments/{order_id}/retry", dependencies=[Depends(operator)])
@router.post("/shipments/{order_id}/retry-allocation", dependencies=[Depends(operator)])
@router.post("/shipment-orders/{order_id}/allocate", dependencies=[Depends(operator)])
@router.post("/shipment-orders/{order_id}/confirm", dependencies=[Depends(operator)])
@router.post("/shipment-orders/{order_id}/retry", dependencies=[Depends(operator)])
@router.post("/shipment_orders/{order_id}/allocate", dependencies=[Depends(operator)])
@router.post("/allocations/{order_id}/allocate", dependencies=[Depends(operator)])
@router.post("/allocations/{order_id}/confirm", dependencies=[Depends(operator)])
@router.post("/allocations/{order_id}/retry", dependencies=[Depends(operator)])
@router.post("/allocation-orders/{order_id}/allocate", dependencies=[Depends(operator)])
@router.post("/allocation-orders/{order_id}/confirm", dependencies=[Depends(operator)])
@router.post("/allocation-orders/{order_id}/retry", dependencies=[Depends(operator)])
@router.post("/orders/{order_id}/allocate", dependencies=[Depends(operator)])
@router.post("/orders/{order_id}/confirm", dependencies=[Depends(operator)])
@router.post("/orders/{order_id}/retry", dependencies=[Depends(operator)])
def allocate_shipment(order_id: int, user=Depends(operator)):
    return _allocate_response(order_id, user)


@router.delete("/shipments/{order_id}", dependencies=[Depends(operator)])
@router.delete("/shipment-orders/{order_id}", dependencies=[Depends(operator)])
@router.delete("/shipment_orders/{order_id}", dependencies=[Depends(operator)])
@router.delete("/allocations/{order_id}", dependencies=[Depends(operator)])
@router.delete("/allocation-orders/{order_id}", dependencies=[Depends(operator)])
@router.delete("/orders/{order_id}", dependencies=[Depends(operator)])
@router.post("/shipments/{order_id}/revoke", dependencies=[Depends(operator)])
@router.post("/shipments/{order_id}/cancel", dependencies=[Depends(operator)])
@router.post("/shipments/{order_id}/undo", dependencies=[Depends(operator)])
@router.post("/shipment-orders/{order_id}/revoke", dependencies=[Depends(operator)])
@router.post("/shipment-orders/{order_id}/cancel", dependencies=[Depends(operator)])
@router.post("/shipment_orders/{order_id}/revoke", dependencies=[Depends(operator)])
@router.post("/allocations/{order_id}/revoke", dependencies=[Depends(operator)])
@router.post("/allocations/{order_id}/cancel", dependencies=[Depends(operator)])
@router.post("/allocation-orders/{order_id}/revoke", dependencies=[Depends(operator)])
@router.post("/allocation-orders/{order_id}/cancel", dependencies=[Depends(operator)])
@router.post("/orders/{order_id}/revoke", dependencies=[Depends(operator)])
@router.post("/orders/{order_id}/cancel", dependencies=[Depends(operator)])
async def revoke_shipment(order_id: int, request: Request, user=Depends(operator)):
    body = await _body(request)
    reason = body.get("reason") or body.get("revoke_reason") or body.get("note") \
        or request.query_params.get("reason")
    return revoke_shipment_transaction(order_id, {"reason": reason}, user)


@router.patch("/shipments/{order_id}", dependencies=[Depends(operator)])
@router.put("/shipments/{order_id}/state", dependencies=[Depends(operator)])
async def update_shipment_state(order_id: int, request: Request, user=Depends(operator)):
    body = await _body(request)
    action = str(body.get("action") or body.get("status") or "").lower()
    if action in {"revoke", "revoked", "cancel", "cancelled", "canceled"}:
        reason = body.get("reason") or body.get("revoke_reason") or body.get("note")
        return revoke_shipment_transaction(order_id, {"reason": reason}, user)
    if action in {"allocate", "allocated", "confirm", "confirmed", "retry"}:
        return _allocate_response(order_id, user)
    raise HTTPException(422, "status/action 需为 allocated、confirmed、retry、revoked 或 cancelled")
