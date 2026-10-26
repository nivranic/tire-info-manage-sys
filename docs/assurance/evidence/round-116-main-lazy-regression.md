# R116：默认 app 惰性导出七项持久回归通过

2026-10-21。新增标准 `unittest.TestCase` 文件，在独立受限 runner 中完成七项回归，Root 正式运行及独立回读均通过。本轮没有再改产品 `main.py`，也没有重跑真实工厂、lifespan 或 ASGI；这些证据仍引用 [R115](round-115-lazy-app-factory.md) 的独立成功批次。

## 测试与实际覆盖

[`test_main_lazy_app.py`](../../../apps/api/tests/test_main_lazy_app.py) SHA-256 为 `3cc6df586235b1c2b1e768dacff430805b97b9f25df603ceff92bdaf2710bcc9`。每例读取当前 `main.py` 原字节，在独立包内别名执行；执行前拦截真实 Database/TelemetryRuntime 构造，解析 app 前换成内存计数 stub。结束后恢复真实构造器、sys.modules 和包内别名。真实 main 仍为 27905B、SHA `57545ed00e1d9f90024adab1b4242143a4426360b9f54a068adffe9624f2365f`。

| 固定用例 | 验证点 |
| --- | --- |
| import_does_not_construct_default_app | 导入后无 app 缓存、无默认 DB/TLM 构造 |
| first_attribute_access_creates_and_caches_once | 首次 getattr 构造一次，后续身份相同 |
| first_from_import_uses_the_same_cache | 独立新模块的首次 from-import 使用同一缓存 |
| concurrent_access_calls_factory_once | 八线程同时访问，只调用一次 stub |
| failed_factory_is_not_cached_and_can_retry | 首次失败不缓存，第二次可成功 |
| same_thread_recursion_is_bounded_and_rejected | 同线程递归返回 RuntimeError |
| unknown_attribute_is_rejected_without_factory_call | 未知属性返回 AttributeError，不调用工厂 |

表内名称均有 `test_` 前缀，完整 ID 和执行顺序固定在 pins 与回执。测试用 BoundedLock 包装原非重入锁，底层仍调用真实 `Lock.acquire(timeout=3)`，超时抛 TimeoutError，与预期递归 RuntimeError 区分；线程使用统一截止时间、finally 中断 barrier 并 join，避免已知递归回归留下永久阻塞线程。这是失败保护，不是生产锁等待时间测量。实际执行使用 unittest loader；没有执行普通 pytest 命令或全仓测试。

## 正式批次与复核

[合同](../../../.artifacts/main-lazy-regression-20261021/CONTRACT.md)限定固定 CPython 3.14.8、九键子环境、私有 TEMP/TMP。runner 仅复用 R115 v4 helper 的 Guard 加载、私有 tmp 探针及受控依赖预热/真实 main 导入三个入口。测试阶段继续以 profile 拒绝真实工厂和 DB/TLM 构造，不调用 v4 的工厂、ASGI 或 lifespan 阶段。

- [1398 项 pins](../../../.artifacts/main-lazy-regression-20261021/key-pins-v1.json)：457387B，SHA `58b46676a51a848a1c06d23a289e8f3f722a5e945bc4104c35c36644962b6768`。1390 个继承输入加 helper、旧证据与本轮新源；唯一项 1398，launcher 首尾及独立逐文件回读均零漂移，非完整传递 import closure。
- [正式回执](../../../.artifacts/main-lazy-regression-20261021/run-034fc3b09fd744298662fa0e5b158ac3/receipt.json)：3566B，SHA `a88fc5adc8777fd95b5185f80336c43377d332fb40e3fa52a7f3d84620d6e196`。launcher `completed`，bootstrap/tests 均 passed；expected/collected/started/completed/success 均为 7，固定 ID 同序，issues/subtests/dropped_issues 均 0，构造器与别名恢复为 true。
- 七个 synthetic 环境探针各 1，files 拒绝 4 均为预期；network/child/sqlite/imports/registry/startup 拒绝均 0。SQLite 连接 0、selfpipe_absent=true；本轮没有创建数据库或 asyncio selfpipe。
- tmp 写读删、残留、移除为 true/0/true；launcher 独立确认 tmp 已不存在，回读私槽仅有 receipt.json。child 自然 exit0，无 timeout/forced，stdout 2019B、stderr0；原始流未落盘。

## 边界与后续

R116 证明当前冻结源码在受控依赖预热、stub 工厂和有界锁适配器下通过七个持久单元回归。R115 报告中“常规回归尚未编写或执行”是历史状态，现由本轮更新；R115 原文、工装、pins 和独立失败/成功批次不改写，也不拼接测试结果。

真实工厂、私库 lifespan 与六条进程内 ASGI 请求仍只由 R115 证明。本轮未启动或验收 Uvicorn/HTTP TCP，也未证明未经预热的自然冷导入、自然 WMI 修复、正常数据库及迁移、实际 PostgreSQL、真实材料/许可、Provider、浏览器、设备或完整 V1。独立 wheel 准备不计入本轮测试成功。Python hook 非 OS sandbox，native/cached 盲点和流捕获无硬内存上限仍在。

后续按独立合同验证真实 `tire_api.main:app` 的 loopback TCP 生命周期。HANDOFF 更新保留原 131751B、SHA `14d2e0cd7c2f8e64f01388983525674394e83460d1a2301ddb1eef9da07c7f8b` 为原字节尾文并备份；正式文档由 Root 唯一应用。V1 仍 active，provider/export=false；本轮未 commit/push。
