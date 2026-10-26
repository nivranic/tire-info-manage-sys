# R115：默认 app 惰性导出与完整工厂受限验证

2026-10-21。默认 `app` 惰性导出已落地；Root 唯一 v4 受限批次在固定私库中完成真实 FastAPI 工厂、lifespan 与六条进程内 ASGI 请求，Root、独立 verifier 和 reviewer 终核接受该限定范围。v1/v2/v3 三批失败证据独立保留，不拼接阶段结果；旧三批共 12 个源、pins 和 receipts 当前保持，1394 个 v4 live 输入零漂移。

## 代码与行为边界

[`main.py`](../../../apps/api/tire_api/main.py) 把模块底部的默认 `app=create_app()` 改为 PEP 562 `__getattr__('app')`：首次属性访问在 `threading.Lock` 内调用原有 `create_app()` 并缓存真实 FastAPI；失败不缓存，后续访问可重试，同线程递归访问及时报错；显式 `create_app(...)` 的签名和主体未改。改动前[原字节](../../../.artifacts/lazy-app-verification-20261021/implementation-v1/main.before.py)为 27235B，SHA-256 `f14bdfffcf9f98926e645fe57aace8ca93a0bbfd8a8d73758b012bae96017efd`；当前 `main.py` 为 27905B，SHA-256 `57545ed00e1d9f90024adab1b4242143a4426360b9f54a068adffe9624f2365f`。普通导入不再构造默认 app，但仍会执行顶层依赖导入与平台探测，不能描述为完全无副作用；访问 `app` 或显式调用工厂仍可能创建资源，lifespan 会初始化所选数据库并执行迁移。

## 独立失败批

| 批次 | 固定输入与退出 | 已观察结果 |
| --- | --- | --- |
| v1 | [1388 pins](../../../.artifacts/lazy-app-verification-20261021/key-pins-v1.json) SHA-256 `04849a825049ddb8255509b7cb26235bbef8fecacb1ab521c8fba969a1f57385`；[回执](../../../.artifacts/lazy-app-verification-20261021/run-7982e8c634234eeda3ad11909f9ca96d/receipt.json) 940B、SHA-256 `ad2b719687833464229141473499ae7a4beb284cf24f5d963eea499f1c9643e9` | `launcher_failed`；child 自然 exit1、stdout/stderr 0，没有可用 child 诊断；整批失败。 |
| v2 | [1390 pins](../../../.artifacts/lazy-app-verification-20261021/key-pins-v2.json) SHA-256 `f5081be0c444992e86a8abaacd911b098462bc25e637baaa6ae0d19aeb916134`；[回执](../../../.artifacts/lazy-app-verification-20261021/run-117543d04cb446d782f138c4e0e0d08d/receipt.json) 1427B、SHA-256 `99e62550d24a735e4718005379e2787fa8928ce9ed30d467aa165365baea317f` | import/lazy/factory 通过，runtime `OperationalError/other`；诊断不足以定位 SQL/FTS。child 自然 exit1、stderr0；整批失败。 |
| v3 | [1392 pins](../../../.artifacts/lazy-app-verification-20261021/key-pins-v3.json) SHA-256 `8922262e01db8bc3eb7200ab71120b4b9fbe99571a6a4164fe3ac1c6477a0c7f`；[回执](../../../.artifacts/lazy-app-verification-20261021/run-27076503fa6841f59cffde440b5ee6be/receipt.json) 4177B、SHA-256 `af85686842b74fda827c4bfa8b1fe1b1003d442506b483547d588e3654529140` | import/lazy/factory 通过；runtime 在 `lifespan_enter` 的 `knowledge_models.py:42` FTS5 `CREATE VIRTUAL TABLE` 失败，SQLite 错误码14 `SQLITE_CANTOPEN`。Guard SQLite denied0、DBAPI connect/close 各1、关闭探针未运行、HTTP请求0；child 自然 exit1、stdout4363B/stderr0，整批失败。 |

三批各自的 pins 在原批次首尾无漂移，不能把阶段通过合并成完整工厂验收。v3 清理无已报告问题，但工厂在 lifespan 内失败时，不能把未执行的 DBAPI 固定关闭探针记为通过。v3 的七键子环境缺 `TEMP`/`TMP`；[SQLite 临时文件说明](https://www.sqlite.org/tempfiles.html#temporary_file_storage_locations)与 [Windows GetTempPathW 说明](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-gettemppathw)支持把原生临时路径回退视为可检验假设。v4 与 v3 的结果差异支持该方向，但未直接观察 SQLite 的 native 临时路径，不能写成已证根因。

## v4 私有临时目录独立成功批

v4 只在清空继承环境后的原七键上增加 `TEMP`、`TMP`，两者均指向新私槽 `tmp`；Guard 配置后，产品和依赖导入前在该目录做固定写/读/删探针。子进程清理前只报告 `tmp` 顶层条目数量，结束时清理并见证目录移除；launcher 在 child 退出后独立检查目录不存在。旧 Guard、产品 SQL、stdlib 和 SQLite PRAGMA 均未改。[v4 合同](../../../.artifacts/lazy-app-verification-20261021/CONTRACT-v4.md) SHA-256 `0190733df0abc04699e5f00d76abc1e2596903e61c7a17cbc5d3ff84a7c561e4`；固定 CPython 3.14.8、R114 依赖、154 个产品 Python 源文件与四个新验证源，仍非完整传递 import closure。

Root 唯一 cea8dd/session63170→a8b0fc exit0；[v4 pins](../../../.artifacts/lazy-app-verification-20261021/key-pins-v4.json) 456022B、1394 唯一项、SHA-256 `cb3f6c6c49fee780c232c865bf9ca1630e23488f22b1e9ed038fd28a0b5f98c2`，Root57badf 核对首尾/live 零漂移、独核 ACCEPT。[正式回执](../../../.artifacts/lazy-app-verification-20261021/run-78c38dc7e1d84e09a02e7c436e55ad06/receipt.json) 4628B、SHA-256 `9e0eccb8d9f605a6e34d17f40af245f5cfec54fb621ce240d2c0e3bb787d4182`；child 自然 exit0，stdout2392B/stderr0，无 timeout/forced。现场私槽仅 `receipt.json` 4628B；`private_temp_probe_passed=true`、`private_temp_residue_count=0`、`private_temp_removed=true`，launcher 独立检查 `private_temp_absent_after_child=true`。

import/lazy/factory/runtime 四阶段全 pass，issues/failure 均空。import 在受控依赖 bootstrap 下默认 factory/Database/Telemetry 构造调用均0、`main.__dict__` 无默认 app 缓存；lazy 段临时替换为计数 stub，仅验证导出语义：首次解析及 `from import` 身份一致，8 线程只构造1次、失败不缓存后重试2次，同线程递归与未知属性拒绝。真实 factory 另在后续阶段构造运行：真实 FastAPI、显式私有 SQLite、空 fact mapping、私有文件对象根、空材料/webhook目录、禁用 telemetry，251 routes/5 middleware。真实 lifespan 初始化私库与 AI supervisor 并关闭；所跟踪 DBAPI 对象 1 open=1 close=1 fixed probe confirmed，engine pool 替换、telemetry 关闭。六次进程内 ASGI requests=responses：observability200无Cookie、health200含 SQLite Cookie、sources200空、外来源403、跨站403、外部无 Bearer401，各检查为 true。

Guard 七个合成环境探针各1，预期 files denied4、network/child/sqlite/imports/registry/startup denied均0，SQLite guard connection1。已审 selfpipe 实际为一次 `stdlib_loopback_fallback`，window1/new socket2/bind1/connect1，pair/listener/window 关闭及五项 diagnostics 为 true。回执字段 `external_provider_or_tcp_listener_used=false` 不能按“所有 TCP 监听皆无”字面解释：该内部窗口确有一次临时 loopback listener；可据此字段及执行矩阵确认的是未调用外部 Provider、未启动或验收 HTTP/Uvicorn TCP 服务。

## 能力、限制与后续

七个环境探针仍为合成受控探针，R105 的自然 WMI 冷导入回退未证明修复。v4 仅证明固定环境中所选真实工厂、私库 lifespan 与进程内完整 ASGI 路径；已审 asyncio selfpipe 窗口内有临时 loopback listener，未启动或验收 HTTP/Uvicorn TCP 服务。固定依赖缺 `uvicorn`/`click`/`h11`；正常数据库及迁移、实际 PostgreSQL、真实材料及许可、真实 Provider、浏览器、设备和完整 V1 均未验收。R112 v2 `service.transport_cache` 的 `OperationalError` 根因未知且未修。本轮 Python hook 不是 OS sandbox，native/cached 导入盲点及 launcher 捕获无硬内存上限保留。DBAPI 固定关闭探针只覆盖这次受 SQLAlchemy 事件跟踪的1个对象，不证明系统所有句柄。R114 原分页证据按其当时 pins 和回执成立，不能因本轮 `main.py` 新哈希声称其旧全 pins 当前无漂移。

已只读确认 `apps/api/tests` 目前没有默认 app 惰性、并发及失败重试的常规回归；这些性质本轮只由冻结工装验证。后续可在拦截 Database 构造的 fresh 模块隔离下集中加入 `test_main_lazy_app.py`；该测试尚未编写或执行。

`docs/HANDOFF.md` 原文 127986B、SHA-256 `c7bd7334f549bd9637547e6268988e9a8017edeedf853b1ac0f462ba2a08dbe1` 完整保留为新前缀后的原字节尾文；`docs/EXTERNAL-FACT-API.md` 只更正默认 app 惰性构造的旧描述。候选应用须校验原文、候选和 File.Replace 生成的真实非空 backup。V1 仍 active，provider/export=false；本轮不代表 commit/push。
