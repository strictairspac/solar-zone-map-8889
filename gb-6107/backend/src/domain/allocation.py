"""出货单分板的纯领域逻辑。

这里不关心 HTTP 或数据库事务；调用方负责把已确认占用的板号集合传入。
选板顺序固定为质保批中的物理行次序，从而保证结果可复演、可与逐行基线核对。
"""
from dataclasses import dataclass
import re

from .columnar import build_pages
from .predicate import Predicate

SERIAL_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,32}")


class AllocationError(ValueError):
    """配货输入或状态不合法。"""


class InsufficientStock(AllocationError):
    def __init__(self, *, required, eligible, occupied, available, serials=None, receipt=None):
        self.required = required
        self.eligible = eligible
        self.occupied = occupied
        self.available = available
        self.serials = serials or []
        self.receipt = receipt
        super().__init__(
            f"瓦数范围内可用板件不足：需要 {required} 块，"
            f"符合范围 {eligible} 块，已占用 {occupied} 块，可用 {available} 块"
        )


class AllocationConflict(AllocationError):
    """并发占用冲突，调用方可重试整个事务。"""


@dataclass(frozen=True)
class AllocationPlan:
    serials: tuple[str, ...]
    receipt: dict
    eligible_serials: tuple[str, ...]
    available_serials: tuple[str, ...]


def normalize_records(payload):
    """接受 {"test_records": [...]}，也直接接受记录列表。"""
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("test_records")
    else:
        raise AllocationError("输入需为对象或闪测记录列表")
    if not isinstance(records, list) or not 1 <= len(records) <= 4096:
        raise AllocationError("test_records 需有 1 至 4096 条闪测记录")
    rows = []
    seen = set()
    for row in records:
        if not isinstance(row, dict) or not {"serial", "power_cw"}.issubset(row):
            raise AllocationError("每条闪测记录需要 serial 和 power_cw")
        serial, reading = row["serial"], row["power_cw"]
        if not isinstance(serial, str) or not SERIAL_PATTERN.fullmatch(serial):
            raise AllocationError("板件编号须为 1 至 32 位字母、数字、下划线或连字符")
        if serial in seen:
            raise AllocationError(f"板件重复：{serial}")
        if reading is not None and (type(reading) is not int or not 0 <= reading <= 500000):
            raise AllocationError("功率需为空或在 0 至 500000 之间的整数厘瓦")
        seen.add(serial)
        rows.append((serial, reading))
    return rows


def normalize_range(low, high):
    if type(low) is not int or type(high) is not int or not 0 <= low <= high <= 500000:
        raise AllocationError("需要 0 ≤ low ≤ high ≤ 500000 的整数厘瓦范围")
    return low, high


def plan_allocation(records, *, low, high, quantity, page_size=4, occupied_serials=()):
    """按范围和数量生成整单分配计划；不足时抛出异常且不返回部分分配。"""
    low, high = normalize_range(low, high)
    if type(quantity) is not int or not 1 <= quantity <= 4096:
        raise AllocationError("quantity 需为 1 至 4096 的整数")
    if type(page_size) is not int or not 1 <= page_size <= 256:
        raise AllocationError("page_size 需为 1 至 256 的整数")

    rows = records if records and isinstance(records[0], tuple) else normalize_records(records)
    occupied = set(occupied_serials or ())
    predicate = Predicate("range", low, high)
    pages = build_pages(rows, page_size)

    evidence = []
    eligible = []
    available = []
    selected = []
    skipped = reads = occupied_hits = 0

    for page_index, page in enumerate(pages, 1):
        zone = page.power_zone
        may_match = predicate.page_may_match(zone)
        offsets = predicate.select_offsets(page.power, zone) if may_match else []
        if not may_match:
            skipped += 1
        if may_match:
            reads += zone.valid_mask.bit_count()

        page_matches = [page.serials[offset] for offset in offsets]
        page_occupied = [serial for serial in page_matches if serial in occupied]
        page_available = [serial for serial in page_matches if serial not in occupied]
        page_selected = []
        for serial in page_available:
            if len(selected) < quantity:
                selected.append(serial)
                page_selected.append(serial)
            else:
                break

        eligible.extend(page_matches)
        available.extend(page_available)
        occupied_hits += len(page_occupied)
        evidence.append({
            "页段": page_index,
            "最小厘瓦": zone.minimum,
            "最大厘瓦": zone.maximum,
            "空值行": zone.nulls,
            "有效位图": format(zone.valid_mask, f"0{zone.count}b"),
            "动作": "扫描读数" if may_match else "跳过",
            "命中数": len(page_matches),
            "板件": "、".join(page_matches),
            "已占用板件": "、".join(page_occupied),
            "可配板件": "、".join(page_available),
            "本次分板": "、".join(page_selected),
        })

    baseline = [serial for serial, reading in rows if predicate.matches_row(reading)]
    if eligible != baseline:
        raise AllocationError("裁剪结果与逐行结果不同")

    enough = len(available) >= quantity
    if not enough:
        # 整单原则：即使上面为了生成回执收集了候选，也绝不把 selected 当作有效占用返回。
        selected = []

    receipt = {
        "summary": (
            f"跳过 {skipped}/{len(pages)} 个页段；范围内 {len(eligible)} 块，"
            f"已确认占用 {occupied_hits} 块，可用 {len(available)} 块，"
            + (f"整单分配 {quantity} 块。" if enough else f"不足 {quantity} 块，本单不占板。")
        ),
        "metrics": {
            "跳过页段": skipped,
            "命中试板": len(eligible),
            "已占用板件": occupied_hits,
            "可配板件": len(available),
            "需求数量": quantity,
            "实配数量": quantity if enough else 0,
            "读取读数": reads,
            "基线行数": len(rows),
            "总页段": len(pages),
        },
        "rows": evidence,
        "allocated_serials": selected if enough else [],
        "eligible_serials": eligible,
        "available_serials": available,
        "low_cw": low,
        "high_cw": high,
        "page_size": page_size,
    }
    if not enough:
        error = InsufficientStock(
            required=quantity,
            eligible=len(eligible),
            occupied=occupied_hits,
            available=len(available),
            serials=available,
            receipt=receipt,
        )
        raise error

    return AllocationPlan(tuple(selected), receipt, tuple(eligible), tuple(available))


# 常见业务命名别名。
allocate_panels = plan_allocation
allocate_boards = plan_allocation
plan_shipment = plan_allocation


def allocation_receipt_for_snapshot(*, low, high, quantity, page_size, allocated_serials, records=None):
    """构造/补全已分配单的冻结回执；正常配货时优先使用 plan_allocation 的结果。"""
    selected = list(allocated_serials or [])
    return {
        "summary": f"本单当时整单分到 {len(selected)} 块板件；撤销状态以单据状态为准。",
        "metrics": {"实配数量": len(selected), "需求数量": quantity},
        "rows": [],
        "allocated_serials": selected,
        "low_cw": low,
        "high_cw": high,
        "page_size": page_size,
    }
