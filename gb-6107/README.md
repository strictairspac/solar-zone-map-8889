# 炙川光伏·闪测页段出货复核

用页段瓦数范围和空值位图抽检待出货序号，交班时说明跳过哪些数据页。

## 业务流程

1. 闪测交班
2. 试板质保批
3. 谓词试跑
4. 裁剪回执

精确整数瓦数列、Zone Map 极值和空值位图裁剪，结果与逐行基线核对。

炙川光伏的 10 人闪测质保与出货验收班每天按仪器日志追查试板序号。全表筛选耗时，缺测和零实际读数容易被混淆，出货抽检无法说明跳过了哪些页。上游是 D3 闪测仪的批次读数，下游是出货复核员与复测班。

09:00 从 D3 仪器取出 SL-D3-1124，09:10 确认板件连续序号，09:15 选择 419.00–421.00 W 质保窗口，09:18 以每页 4 条运行，09:20 抽验 419.00 W 和 421.00 W 两个边界，09:25 下载 4 个命中编号及裁剪回执，09:35 另跑 A2 的空读数清单。

读数列使用整数厘瓦，每页记录最小值、最大值和有效位置位图。范围与页元数据无交集时跳过，筛选空值时直接读位图。结果按物理行次序与逐行基线比较。读取读数统计检查的非空数值，不含生成元数据或基线验证的开销。PostgreSQL 持久化批单与结果，Python 构建教学用内存列页，未改动 PostgreSQL 的执行器。

## 启动

```sh
cp -n .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
```

打开 <http://localhost:18256>。OpenAPI 在 <http://localhost:19256/docs>，数据库映射到本机 17756。所有暴露端口只绑定回环地址。Compose 启动 frontend、backend、worker、db、redis，各自通过健康探针检查。数据库、Redis 和共享产物目录各有命名卷；任务状态及导出内容以数据库中的证据为准。

首次启动时幂等载入演示数据。手动载入可运行 `docker compose exec -T backend python -m scripts.seed_demo`。常规停止可用 `docker compose down`。验收环境清理才加 `-v`，它会删除本项目的数据卷。

## 角色与交接

演示账号共用口令 `Demo-DbWorkbench-2026`。

| 登录名 | 角色 | 可执行操作 |
|---|---|---|
| operator | 资料操作员 | 登记业务资料、设置「每页闪测条数（1–256）」、提交、查看和下载结果 |
| reviewer | 业务复核员 | 查看执行证据、签署单次复核、下载交接单 |
| viewer | 只读观察员 | 查看资料、执行结果及审计，下载证据 |

选用「SL-D3-1124 / 419.00–421.00 W」对应的演示资料，保存一份复演资料，再以默认参数 4 提交。worker 保存结果摘要、业务明细和 SHA-256。复核员登录后在「裁剪回执」签署。

## 开发说明

| 部分 | 实现 |
|---|---|
| 前端 | 原生 HTML、CSS、JavaScript ES Modules、Nginx |
| 后端 | Python 3.11、FastAPI、SQLAlchemy、JWT |
| 数据库 | PostgreSQL 16 |
| 后台执行 | Redis 通知、数据库持久任务队列和行锁、Python worker |

从 `backend/src/domain/scenario.py` 修改业务入口和演示口径，运行 `docker compose up -d --build --wait` 查看变更。数据库表结构在 `backend/src/models` 和 `backend/migrations`，输入模型在 `backend/src/schemas`。业务页和请求接口在 `frontend/src/pages`、`frontend/src/api`。资料、执行、复核三个工作流实体各有独立表和 API；场景输入及结果保留在所属资料和批次中。

角色枚举在 `backend/src/constants/roles.py`、`frontend/src/constants/roles.js`，用于服务端访问控制、账号初始化、前端导航与签署。批次状态在 `backend/src/constants/job_state.py`、`frontend/src/constants/states.js`，用于队列、状态 API、状态标记与轮询。登记、提交、完成和签署事件写入审计表。

`COMPOSE_PROJECT_NAME` 设置栈名，`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT` 设置端口。通过 `DB_PASSWORD`、`JWT_SECRET`、`DEMO_PASSWORD` 配置本地凭据。设置 `SEED_DEMO=false` 可关闭演示数据载入，此时数据库初始没有演示账号。数据库密码调整后，已有数据卷需在数据库内同步修改用户密码。

## 出货单分板

同一闪测质保批可创建多张出货单。每张单独立给出瓦数范围、整单数量和页容量；配货仍经过 Zone Map / 空值位图同一套页段裁剪，并在单据回执中保留逐页动作、候选板件和本单分到的板件。

- `POST /cases/{case_id}/shipments`：创建出货单并同步整单配货；也兼容 `/shipment-orders`、`/allocations` 等路径和 `low_cw/high_cw`、`low/high`（419.00 形式按 W 换算）等字段别名。
- `POST /shipments/{id}/allocate|confirm|retry`：重试已配货单直接返回原板件，不重复写入占用。
- `POST /shipments/{id}/revoke|cancel`：撤销后删除当前占用，历史分配行和单据上的 `allocated_serials` 快照保留，裁剪回执页显示“已撤销”。
- 配货在同一质保批的行锁/进程串行区中判定已确认占用，`shipment_occupancies(case_id, serial)` 唯一约束是最终并发防线；候选不足整单时单据为 `shortage`，不写任何占用。

前端新增「出货单配货」页；「裁剪回执」页按质保批汇总每单当时分到的板件与当前撤销状态，导出的 run 证据也附带 `shipments`。

## 验收范围

使用等条数的内存列页段和单个闪测谓词。报告记录读取数和跳过数。 当前界面用 JSON 编辑业务资料，以 JSON 下载证据。过程和截图保存在批次的 [验收记录](../../test-artifacts/gb-6107/TESTING.md)。

[MIT License](LICENSE)
