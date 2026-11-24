def _batch(powers, line):
    return [
        {"serial": f"{line}-{index:04}", "power_cw": power}
        for index, power in enumerate(powers, 101)
    ]


FIXTURES = [
    {
        "code": "SL-D3-1124",
        "title": "D3 线出货瓦数抽检",
        "description": "调取 419.00–421.00 W 出货窗口，保留命中序号和未读取的页段。",
        "payload": {
            "test_records": _batch(
                [40500, 40750, None, 40900, 41900, 42025, 42100, 42101,
                 None, None, None, None, 42400, 42500, 42520, 42600,
                 41899, 41999, None, 42410], "D3"
            ),
            "predicate": {"mode": "range", "low": 41900, "high": 42100},
        },
    },
    {
        "code": "SL-A2-1124",
        "title": "A2 重测任务漏录追踪",
        "description": "沿空值位图找回没有闪测读数的板件；零读数作为实测值保留。",
        "payload": {
            "test_records": _batch([40001, 42122, 0, 42000, None, 41820, None, 42000], "A2"),
            "predicate": {"mode": "null"},
        },
    },
]
