"""出货单分板：页段裁剪、整单不足、幂等重试、并发唯一占用和撤销释放。"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

try:  # HTTP 测试依赖 httpx；缺少该测试依赖时不应影响纯服务层用例收集。
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None

from src.constants.roles import Role
from src.domain.allocation import InsufficientStock, plan_allocation
from src.domain.fixtures import FIXTURES
from src.models.shipments import shipment_occupancies, shipment_orders
from src.services import cases as case_service
from src.services import shipments as shipment_service
from src.schemas.cases import CaseInput


def _case(db, payload=None):
    return case_service.create(db, CaseInput(
        title="出货分板测试批", payload=payload or FIXTURES[0]["payload"]
    ), "operator")


def _order(db, case_id, **overrides):
    body = {"case_id": case_id, "low_cw": 41900, "high_cw": 42100, "quantity": 2, "page_size": 4}
    body.update(overrides)
    return shipment_service.create_and_allocate(db, body, "operator")


def test_plan_uses_zone_pruning_and_physical_order():
    records = [(row["serial"], row["power_cw"]) for row in FIXTURES[0]["payload"]["test_records"]]
    plan = plan_allocation(records, low=41900, high=42100, quantity=4, page_size=4)
    assert plan.serials == ("D3-0105", "D3-0106", "D3-0107", "D3-0118")
    assert plan.receipt["metrics"]["跳过页段"] >= 1
    assert plan.receipt["metrics"]["命中试板"] == 4
    assert all("动作" in row and "有效位图" in row for row in plan.receipt["rows"])


def test_whole_order_shortage_does_not_occupy(db):
    case_id = _case(db)["id"]
    order = _order(db, case_id, quantity=5)
    assert order["status"] == "shortage"
    assert order["allocated_serials"] == []
    assert db.scalar(select(func.count()).select_from(shipment_occupancies)) == 0
    with pytest.raises(InsufficientStock):
        records = [(r["serial"], r["power_cw"]) for r in FIXTURES[0]["payload"]["test_records"]]
        plan_allocation(records, low=41900, high=42100, quantity=5)


def test_retry_allocated_order_is_idempotent(db):
    case_id = _case(db)["id"]
    first = _order(db, case_id, code="SHIP-RETRY")
    second = shipment_service.allocate_order(db, first["id"], "operator")
    by_code = _order(db, case_id, code="SHIP-RETRY")

    assert first["status"] == "allocated"
    assert second["allocated_serials"] == first["allocated_serials"]
    assert by_code["id"] == first["id"]
    assert db.scalar(select(func.count()).select_from(shipment_occupancies)) == 2
    assert db.scalar(select(func.count()).select_from(shipment_orders)) == 1


def test_overlapping_orders_share_confirmed_occupancy_and_revoke_frees(db):
    case_id = _case(db)["id"]
    first = _order(db, case_id, quantity=3)
    second = _order(db, case_id, quantity=1)
    assert first["allocated_serials"] == ["D3-0105", "D3-0106", "D3-0107"]
    assert second["allocated_serials"] == ["D3-0118"]

    shortage = _order(db, case_id, quantity=1)
    assert shortage["status"] == "shortage"

    revoked = shipment_service.revoke_order(db, first["id"], "operator", reason="客户改期")
    assert revoked["status"] == "revoked"
    assert revoked["allocated_serials"] == ["D3-0105", "D3-0106", "D3-0107"]
    assert revoked["revoked"] is True

    replacement = _order(db, case_id, quantity=3)
    assert replacement["allocated_serials"] == ["D3-0105", "D3-0106", "D3-0107"]
    # 撤销单的历史分配行仍在，新单有自己的分配行。
    assert db.scalar(select(func.count()).select_from(shipment_orders)) >= 3


def test_non_overlapping_orders_both_complete(db):
    case_id = _case(db)["id"]
    low_range = _order(db, case_id, low_cw=40500, high_cw=40900, quantity=2)
    high_range = _order(db, case_id, low_cw=41900, high_cw=42100, quantity=2)
    assert low_range["status"] == high_range["status"] == "allocated"
    assert set(low_range["serials"]).isdisjoint(high_range["serials"])
    assert low_range["serials"] == ["D3-0101", "D3-0102"]
    assert high_range["serials"] == ["D3-0105", "D3-0106"]


def test_concurrent_orders_never_double_occupy(engine):
    payload = {
        "test_records": [{"serial": f"P-{i:03d}", "power_cw": 42000} for i in range(40)],
        "predicate": {"mode": "range", "low": 41900, "high": 42100},
    }
    with engine.begin() as db:
        case_id = case_service.create(db, CaseInput(title="并发", payload=payload), "op")["id"]

    from src.controllers.workbench import create_shipment as create_shipment_tx

    def allocate(index):
        order = create_shipment_tx({
            "case_id": case_id, "low_cw": 41900, "high_cw": 42100,
            "quantity": 1, "page_size": 4, "code": f"CONC-{index}",
        }, {"username": "operator"})
        return order["status"], order["serials"][0] if order["serials"] else None

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(allocate, range(40)))

    assert all(status == "allocated" for status, _ in results)
    serials = [serial for _, serial in results]
    assert len(serials) == 40 and len(set(serials)) == 40
    with engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(shipment_occupancies)) == 40


class _DummyRedis:
    def lpush(self, *args, **kwargs):
        return 1

    def ltrim(self, *args, **kwargs):
        return True

    def ping(self):
        return True


@pytest.fixture()
def client(engine, monkeypatch):
    if TestClient is None:
        pytest.skip("缺少 fastapi.testclient/httpx 测试依赖")
    monkeypatch.setattr("src.controllers.workbench.cache", _DummyRedis())
    monkeypatch.setattr("src.routes.system.cache", _DummyRedis())
    from src.models.users import users
    from src.utils.passwords import hash_password

    with engine.begin() as db:
        db.execute(users.insert().values(
            username="operator", role=Role.OPERATOR, password_hash=hash_password("pw-2026")))

    from src.main import app
    with TestClient(app) as test_client:
        yield test_client


def _token(client):
    response = client.post("/auth/login", json={"username": "operator", "password": "pw-2026"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_http_create_retry_revoke_and_receipt(client):
    headers = _token(client)
    case = client.post("/cases", headers=headers, json={
        "title": "HTTP 出货批", "payload": FIXTURES[0]["payload"],
    })
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]

    created = client.post(f"/cases/{case_id}/allocate", headers=headers, json={
        "low": 419, "high": 421, "quantity": 2,
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "allocated"
    assert body["allocated_serials"] == ["D3-0105", "D3-0106"]

    retried = client.post(f"/allocations/{body['id']}/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["allocated_serials"] == body["allocated_serials"]

    listed = client.get(f"/cases/{case_id}/shipments", headers=headers)
    assert listed.status_code == 200 and len(listed.json()) == 1

    revoked = client.post(f"/shipments/{body['id']}/cancel", headers=headers, json={"reason": "x"})
    assert revoked.status_code == 200 and revoked.json()["revoked"] is True
    assert revoked.json()["allocated_serials"] == ["D3-0105", "D3-0106"]

    receipt = client.get(f"/shipments/{body['id']}/receipt", headers=headers)
    assert receipt.status_code == 200
    assert receipt.json()["revoked"] is True
    assert receipt.json()["allocated_serials"] == ["D3-0105", "D3-0106"]

    # 撤销释放后，新单可以取得同样板件。
    next_order = client.post("/shipment-orders", headers=headers, json={
        "case_id": case_id, "low_cw": 41900, "high_cw": 42100, "quantity": 2,
    })
    assert next_order.status_code == 201
    assert next_order.json()["allocated_serials"] == ["D3-0105", "D3-0106"]
