import re

from .columnar import build_pages
from .fixtures import FIXTURES
from .predicate import Predicate


CONFIG = {
    "title": "炙川光伏·闪测页段出货复核",
    "team": "炙川光伏 10 人闪测质保与出货验收班",
    "description": "用页段瓦数范围和空值位图抽检待出货序号，交班时说明跳过哪些数据页。",
    "direction": "列式页段裁剪与谓词下推",
    "mechanism": "精确整数瓦数列、Zone Map 极值和空值位图裁剪，结果与逐行基线核对。",
    "modules": ["闪测交班", "试板质保批", "谓词试跑", "裁剪回执"],
    "unit": "闪测质保批",
    "max_parameter": 256,
    "parameter_label": "每页闪测条数（1–256）",
    "default_parameter": 4,
    "facts": ["跳过页段", "命中试板", "读取读数"],
    "palette": 7,
    "fixture": "SL-D3-1124 / 419.00–421.00 W",
}


def normalize(payload):
    if not isinstance(payload, dict):
        raise ValueError("输入需为对象")
    records = payload.get("test_records")
    if not isinstance(records, list) or not 1 <= len(records) <= 4096:
        raise ValueError("test_records 需有 1 至 4096 条闪测记录")
    rows = []
    seen = set()
    for row in records:
        if not isinstance(row, dict) or not {"serial", "power_cw"}.issubset(row):
            raise ValueError("每条闪测记录需要 serial 和 power_cw")
        serial, reading = row["serial"], row["power_cw"]
        if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", serial):
            raise ValueError("板件编号须为 1 至 32 位字母、数字、下划线或连字符")
        if serial in seen:
            raise ValueError(f"板件重复：{serial}")
        if reading is not None and (type(reading) is not int or not 0 <= reading <= 500000):
            raise ValueError("功率需为空或在 0 至 500000 之间的整数厘瓦")
        seen.add(serial)
        rows.append((serial, reading))
    config = payload.get("predicate")
    if not isinstance(config, dict) or config.get("mode") not in ("range", "null"):
        raise ValueError("predicate.mode 需要 range 或 null")
    if config["mode"] == "null":
        return rows, Predicate("null")
    low, high = config.get("low"), config.get("high")
    if type(low) is not int or type(high) is not int or not 0 <= low <= high <= 500000:
        raise ValueError("需要 0 ≤ low ≤ high ≤ 500000 的整数厘瓦范围")
    return rows, Predicate("range", low, high)


def validate(payload):
    normalize(payload)


def run(payload, parameter, db):
    records, predicate = normalize(payload)
    pages = build_pages(records, parameter)
    evidence = []
    matches = []
    skipped = reads = 0
    for page_index, page in enumerate(pages, 1):
        zone = page.power_zone
        may_match = predicate.page_may_match(zone)
        offsets = predicate.select_offsets(page.power, zone) if may_match else []
        if not may_match:
            skipped += 1
        if may_match and predicate.mode == "range":
            reads += zone.valid_mask.bit_count()
        serials = [page.serials[offset] for offset in offsets]
        matches.extend(serials)
        evidence.append({
            "页段": page_index, "最小厘瓦": zone.minimum, "最大厘瓦": zone.maximum,
            "空值行": zone.nulls, "有效位图": format(zone.valid_mask, f"0{zone.count}b"),
            "动作": ("扫描读数" if predicate.mode == "range" else "扫描位图") if may_match else "跳过",
            "命中数": len(offsets), "板件": "、".join(serials),
        })
    baseline = [serial for serial, reading in records if predicate.matches_row(reading)]
    if matches != baseline:
        raise RuntimeError("裁剪结果与逐行结果不同")
    return {
        "summary": f"跳过 {skipped}/{len(pages)} 个页段，命中 {len(matches)} 块试板，与逐行校核一致。",
        "metrics": {"跳过页段": skipped, "命中试板": len(matches), "读取读数": reads,
                    "基线行数": len(records), "总页段": len(pages)},
        "rows": evidence,
    }
