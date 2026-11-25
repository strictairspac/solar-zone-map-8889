from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ShipmentOrderInput(BaseModel):
    """宽松输入模型：HTTP 层主要使用 parse_shipment_input 做多别名归一化。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    case_id: int | None = None
    case_code: str | None = None
    code: str | None = None
    order_no: str | None = None
    shipment_no: str | None = None
    idempotency_key: str | None = None
    customer: str | None = None

    low: int | float | None = None
    high: int | float | None = None
    low_cw: int | None = None
    high_cw: int | None = None
    low_w: int | float | None = None
    high_w: int | float | None = None

    quantity: int | None = Field(default=None, ge=1)
    qty: int | None = Field(default=None, ge=1)
    count: int | None = Field(default=None, ge=1)
    page_size: int | None = Field(default=4, ge=1, le=256)


_LOW_KEYS = (
    "low_cw", "min_cw", "power_low_cw", "low_power_cw", "lower_cw",
    "low", "min", "minimum", "from", "start",
    "power_low", "low_power", "min_power", "minimum_power",
    "low_w", "min_w", "low_watt", "min_watt", "low_watts", "min_watts",
    "watt_min", "watts_min", "min_wattage", "low_wattage",
)
_HIGH_KEYS = (
    "high_cw", "max_cw", "power_high_cw", "high_power_cw", "upper_cw",
    "high", "max", "maximum", "to", "end",
    "power_high", "high_power", "max_power", "maximum_power",
    "high_w", "max_w", "high_watt", "max_watt", "high_watts", "max_watts",
    "watt_max", "watts_max", "max_wattage", "high_wattage",
)
_QUANTITY_KEYS = ("quantity", "qty", "count", "needed", "need", "board_count", "panels", "panel_count", "amount")
_PAGE_KEYS = ("page_size", "page_capacity", "page_rows", "parameter", "capacity")
_CODE_KEYS = ("code", "order_code", "order_no", "shipment_code", "shipment_no", "shipment_order_no", "external_id")
_IDEMPOTENCY_KEYS = ("idempotency_key", "idempotency-key", "request_id", "client_request_id", "retry_key")


def _lookup(data: dict[str, Any], keys):
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] is not None:
            return lowered[key.lower()]
    return None


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return None
    return None


def _to_cw(value, *, explicit_watts=False):
    number = _number(value)
    if number is None:
        return None
    if explicit_watts:
        return round(number * 100)
    # 兼容直接传 419.00–421.00 W 的调用；厘瓦整数通常远大于 1000。
    if isinstance(value, float) or number <= 1000:
        return round(number * 100)
    return int(number)


def _range_from_container(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return value[0], value[1]
    if isinstance(value, dict):
        low = _lookup(value, ("low", "min", "minimum", "from", "lower", "start", "low_w", "min_w", "low_cw"))
        high = _lookup(value, ("high", "max", "maximum", "to", "upper", "end", "high_w", "max_w", "high_cw"))
        return low, high
    return None, None


def key_endswith_w(key):
    return key.endswith("_w") or key in {"w", "min_w", "max_w"}


def parse_shipment_input(payload: dict[str, Any] | None, *, path_case_id=None, query: dict[str, Any] | None = None):
    data: dict[str, Any] = {}
    for source in (payload or {}, query or {}):
        if isinstance(source, dict):
            data.update(source)
    # 兼容 {"shipment_order": {...}} / {"order": {...}} 的请求包装。
    for wrapper_key in ("shipment_order", "shipment", "order", "data"):
        wrapper = data.get(wrapper_key)
        if isinstance(wrapper, dict):
            for key, value in wrapper.items():
                data.setdefault(key, value)

    case_ref = _lookup(data, ("case_id", "batch_id", "warranty_batch_id", "case", "batch"))
    if isinstance(case_ref, dict):
        case_ref = case_ref.get("id") or case_ref.get("code")
    case_code = _lookup(data, ("case_code", "batch_code", "warranty_batch_code", "case_no", "batch_no"))
    if path_case_id is not None:
        case_id = path_case_id
    elif isinstance(case_ref, str) and not case_ref.isdigit():
        case_code = case_code or case_ref
        case_id = None
    else:
        case_id = case_ref
    try:
        case_id = int(case_id) if case_id is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError("case_id 需为整数") from exc

    low = _lookup(data, _LOW_KEYS)
    high = _lookup(data, _HIGH_KEYS)
    for container_key in ("watt_range", "power_range", "range", "watts", "wattage", "window"):
        container = data.get(container_key)
        if container is not None and (low is None or high is None):
            container_low, container_high = _range_from_container(container)
            low = low if low is not None else container_low
            high = high if high is not None else container_high

    low_key = next((key for key in _LOW_KEYS if _lookup(data, (key,)) is not None), "")
    high_key = next((key for key in _HIGH_KEYS if _lookup(data, (key,)) is not None), "")
    low_cw = _to_cw(low, explicit_watts=("watt" in low_key or key_endswith_w(low_key)))
    high_cw = _to_cw(high, explicit_watts=("watt" in high_key or key_endswith_w(high_key)))

    quantity = _number(_lookup(data, _QUANTITY_KEYS))
    page_size_number = _number(_lookup(data, _PAGE_KEYS))
    if quantity is not None:
        quantity = int(quantity)
    page_size = int(page_size_number) if page_size_number is not None else 4

    code = _lookup(data, _CODE_KEYS)
    idempotency_key = _lookup(data, _IDEMPOTENCY_KEYS)
    customer = _lookup(data, ("customer", "customer_name", "destination", "consignee"))
    reason = _lookup(data, ("reason", "revoke_reason", "cancel_reason", "note"))

    return {
        "case_id": case_id,
        "case_code": str(case_code).strip() if case_code is not None else None,
        "low_cw": low_cw,
        "high_cw": high_cw,
        "quantity": quantity,
        "page_size": page_size,
        "code": str(code).strip() if code is not None else None,
        "idempotency_key": str(idempotency_key).strip() if idempotency_key is not None else None,
        "customer": str(customer).strip() if customer is not None else None,
        "reason": str(reason).strip() if reason is not None else None,
        "raw": data,
    }
