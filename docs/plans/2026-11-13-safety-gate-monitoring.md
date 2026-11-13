# Safety Gate持续监控实施计划

## 目标与依据

接通原规格P0安全来源的定时检查、告警变化提醒和抓取任务。阶段基线为main的 `68a6b0c`。复用Safety Gate官方索引、周报、内容版本与变化事件，沿现有Worker、摄取锁、来源代次及任务事件流实现。采用brainstorming与writing-plans梳理设计，用户已授权持续实施。

## 规则及执行合同

- 规则属于当前会话及其账户作用域，配置名称、启用状态、检查间隔、关键词和最近周报数量。默认每21600秒检查最近4份，允许3600至604800秒及1至12份。周报数量定义明确的滚动覆盖范围，历史档案仍可通过查询入口读取。
- 每轮先实时核验完整官方索引，再按官方发布日期、编号和原生ID确定最近周报，依序实时核验。新周报自动进入范围，保存索引快照、选中周报及逐次查询回执。未全部成功时记录不完整状态，已接受的独立周报仍可作为证据。
- 复用ETag及Last-Modified核验。每个来源同时最多一个受管任务，两次请求间隔至少2.1秒，单轮最多300秒，租约600秒。来源Adapter继续执行其robots和响应大小合同。
- 规则创建与修订支持请求标识重放，修订使用expected_revision防止覆盖。暂停或归档后的旧任务继续占用租约直到收尾或过期，接收及提交前验证规则修订、租约和来源代次。
- 每次完成有效周报检查后，从对应周报的已保存变化事件形成规则提醒。只选择当前规则修订创建后观察的事件，关键词同时检查变化前后版本。规则与事件唯一约束保证重试去重。提醒关联告警、内容版本、原件和变化前后值，具体SKU适用性保持not_assessed。
- 所有任务阶段复用monitor-tasks的claimed、running、finished记录、分页与SSE。任务执行、规则和运行记录只追加。新增独立表兼容已有SQLite及PostgreSQL库。

## 实施与验证顺序

1. 新增 `apps/api/tests/test_safety_gate_monitoring.py` 并登记受管回归。覆盖规则重放、账户隔离、到期调度、真实Worker入口、最新周报选择、304去重、部分失败、暂停及来源代次变化、租约过期、任务游标和提醒原件关联。
2. 新增 `apps/api/tire_api/safety_gate_monitor_models.py`、`safety_gate_monitoring.py` 和 `safety_gate_monitor_routes.py`。在db及main登记。扩展SafetyGateService的摄取guard，沿正常捕获／Parser／采纳链执行。
3. 在 `monitor_tasks.py` 与 `apps/worker/monitor.py` 接通独立Safety Gate任务，复用任务生命周期和恢复合同。
4. 扩展共享类型及SDK，新增 `apps/web/components/safety-gate-monitoring.tsx`。正常Safety Gate界面可创建、暂停、恢复、归档规则，读取提醒、原件和现有任务详情。检查会话切换、取消及迟到响应。
5. 运行Safety Gate、任务和Worker相关受管回归、Web测试、三端类型和独立生产构建。使用隔离库验证正常HTTP和生产Web，执行PostgreSQL及旧库追加升级验证。真实来源核验与合成变化分别记录，长期生产运行按实际持续时间报告。
6. 回填验收与交接卡，保留原始失败、源码绑定、原规格和历史交接尾文，提交推送并核对远端。完整V1继续包括真实模型、其他P0来源、人工Golden、生产权限、六平台及全部发布Gate。

## 复验入口

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/sg-monitor-next --targets apps/api/tests/test_safety_gate_monitoring.py apps/api/tests/test_safety_gate_alerts.py apps/api/tests/test_safety_gate.py apps/api/tests/test_monitor_tasks.py apps/api/tests/test_monitor_task_execution.py apps/api/tests/test_recall_monitoring.py
npm run test --workspace @tire/web
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
```

实现过程中按失败证据补充用例和复验范围，实际回执写入Git忽略的.artifacts目录。

## 本阶段执行结果

规则、Worker、证据回执、应用内提醒、Web及任务SSE已接通。实际生产浏览器定位到Next压缩缓冲和会话中间件覆盖路由头，修复后代理首块212ms，同一任务完成态336ms更新。最终十模块215项回归、Web55项、SDK13项、三端类型、生产构建、真实官网与HTTP27项及PostgreSQL24项通过；旧库177→185表保留旧数据。真实库和22轮合成库各19项关闭核对通过，自有资源关闭。

原始失败、各阶段回执与未验收范围见[监控验收](../assurance/evidence/safety-gate-monitoring-2026-11-13.md)。真实自然长周期、通知lag、AI引用、Native消费及完整V1继续开放；不能将隔离到期提前与合成变化当作生产长期验收。
