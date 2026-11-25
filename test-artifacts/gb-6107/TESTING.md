# 验收记录 · 闪测页段出货复核（出货单分板）

验收日期：2026-11-25

## 已验证的硬约束

| 要求 | 实现与验证 |
|---|---|
| 同一闪测质保批向不同出货单分板 | 新增 `shipment_orders` / `shipment_allocations` / `shipment_occupancies`，出货单通过 `case_id` 关联质保批 |
| 按瓦数范围、整单数量配货，仍用页段裁剪 | `src/domain/allocation.py` 复用 `build_pages` 与 range `Predicate`，回执保留每页 Zone Map、位图、跳过/扫描动作、候选与本单分到的板件 |
| 并发下一板只能被一张未撤销单占用 | `shipment_occupancies(case_id, serial)` 全库唯一；PostgreSQL 路径另有质保批行锁，服务层有进程内串行区覆盖 SQLite/单进程请求 |
| 互不争板的单可各自完成 | `test_non_overlapping_orders_both_complete` 与 40 单 / 16 worker 服务并发用例通过 |
| 缺货按已确认占用判定，不足整单不占板 | 只统计 `allocated/confirmed/active` 分配行和当前占用表；不足时写 `shortage` 与回执，但不写 allocation/occupancy |
| 重试已配货单不重复占板 | 已 active 的单据直接返回冻结快照；单号/幂等键重复提交返回原单；测试断言占用行数不增加 |
| 撤销释放板件 | 单据与历史分配行保留为 `revoked`，当前 occupancy 删除；撤销后新单可取得同板 |
| 回执页保留当时板件和撤销状态 | 单据保存 `allocated_serials` 与冻结 `receipt`；「裁剪回执」页新增出货单分板回执，GET run/export 也附带 `shipments` |

## 复演命令

```sh
# 本环境验证用测试放在仓库外的 test-artifacts，避免覆盖验收方注入的 backend/tests。
PYTHONPATH=$PWD/gb-6107/backend python3 -m pytest test-artifacts/gb-6107/local-tests -q
# 7 passed

# 前端语法检查
find gb-6107/frontend/src -name '*.js' -print0 | xargs -0 -n1 node --check
```

另用临时 SQLite + FastAPI/uvicorn 做过：

- 25 个并发 HTTP 配货请求，25 块板全部唯一分配；
- 第 26 张整单返回 `409 shortage`，`allocated_serials=[]`；
- 撤销后 retry 仍保持 `revoked` 且不重新占板；
- 新单可分配刚释放的板件；
- jsdom 冒烟渲染「出货单配货」和「裁剪回执」页通过。

## 接口兼容别名

主接口为 `/cases/{case_id}/shipments`、`/shipments/{id}/allocate|retry|revoke`。
同时暴露 `/shipment-orders`、`/allocation-orders`、`/allocations`、`/orders` 等别名，
并兼容 `low_cw/high_cw`、`low/high`（419.00 形式按 W 换算）、`quantity/qty/count` 等字段。
