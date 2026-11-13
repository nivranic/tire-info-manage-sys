# Safety Gate持续回退授权 Implementation Plan

**Goal:** 使Safety Gate普通在线查询支持原规格的会话、来源与查询类型持续回退授权，并保持在线优先、拒绝优先和逐次消费审计。

**Architecture:** 复用query_fallback_policies的预览、明确确认、只追加修订和消费回执；新增周报索引及指定周报两类仓库查询范围。复用QueryFallbackPolicy界面，仓库类型与设备类型分别表达，未实现的设备消费不扩大。后台监控、AI与内部调用不继承普通查询授权。

**Tech Stack:** FastAPI、SQLAlchemy、现有SQLite／PostgreSQL模型、TypeScript共享类型与Next客户端组件。

## 依据与选择

基线为 `46885d1`，工作区干净。原规格第6节要求在线失败后可以本次允许、持续允许此类查询或拒绝；当前Safety Gate只有单次授权，已有轮胎／车型／NHTSA持续授权链可复用。

方案比较：扩展现有策略可保留同一套权限与审计；另建Safety Gate策略会重复撤销、过期与并发逻辑；将其冒充recall_search会使既有NHTSA授权范围变宽。采用第一种，分别登记 `safety_gate_reports` 与 `safety_gate_report`，不新增数据库表。

## 合同

- 普通HTTP查询由服务端明确标为programmatic，Service缺省仍为internal。请求体不能自行选择audience。
- 每次仍先访问来源，只有原有白名单网络中断／超时可消费持续权限；Parser失败、结构变化、来源禁用或代次变化不能触发持续回退。
- 回退前提交唯一消费回执，读取后再次核对策略、会话、条件、来源代次与期限。响应保留LOCAL_SNAPSHOT、原因、快照时间、原件哈希及策略修订。
- never优先于允许并禁止旧的单次同意；ask保留单次同意。暂停、撤销和过期阻止后续自动读取，显式历史入口独立保留。
- 索引策略不授权指定周报，指定周报类型授权明确覆盖该来源的周报查询，不限定某个周报ID；具体请求身份冻结在每次消费回执中。
- 默认仓库权限不跨UserSession。旧设备查询类型及宿主解码器不扩展；Safety Gate界面只提供仓库策略。
- 原有Worker始终fallback_policy=never，本轮不将历史结果标为在线监控成功或生成新的通知。

## 执行步骤

1. 新增 `apps/api/tests/test_safety_gate_fallback.py`，在 `scripts/run_api_worker_regression.py` 登记。先验证既有入口拒绝新查询范围的红批。
2. 修改 `apps/api/tire_api/query_fallback_policies.py` 的查询类型和固定来源范围校验；修改 `safety_gate.py` 的programmatic入口、持续回退及单次授权拒绝门。
3. 修改 `packages/domain-types/src/warehouse-fallback.ts`，独立仓库范围类型，保持DeviceFallback类型不变；导出类型并在SafetyGateResult添加可选授权回执。
4. 修改 `apps/web/components/query-fallback-policy.tsx` 与 `safety-gate.tsx`，复用策略管理、隔离设备入口、展示索引／周报范围和历史授权证据。通过三端类型验证旧调用兼容。
5. 受管回归覆盖正常允许、在线／304、索引与周报隔离、每次唯一回执、读取前持久化、never／ask、暂停撤销、过期、跨会话、来源变化、读后撤销、损坏快照、后台不继承及显式历史。联跑原策略、Safety Gate查询与监控模块。
6. 正常HTTP与生产Web验收预览／明确确认、网络失败后的LOCAL_SNAPSHOT和消费回执、撤销后的询问、原件恢复及窄屏。SQLite／PostgreSQL分别核对持久化与恢复，所有合成网络故障明确标记，不冒充真实官网故障。
7. 更新验收与当前交接入口；审查差异、原规格及历史尾文不变量、敏感信息、源码绑定，提交推送并核对远端。

## 复验命令

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/sg-fallback-next --targets apps/api/tests/test_safety_gate_fallback.py apps/api/tests/test_query_fallback_policies49.py apps/api/tests/test_query_fallback_policy_boundaries49.py apps/api/tests/test_query_fallback_preferences49.py apps/api/tests/test_safety_gate.py apps/api/tests/test_safety_gate_monitoring.py
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
npm run test --workspace @tire/web
```

## 回退与未验边界

暂停／撤销本轮策略后可以回到前一程序版本；新查询类型的历史修订及消费回执保留，不删除账本。新版本旧库无需新表。实际生产权限、自然长周期、真实模型及六平台设备业务仍按完整V1独立验收。

## 实际执行结果

后端与Web链路已接通。最终六模块116项、SDK7项、Web55项、三端类型、生产构建、隔离PostgreSQL34项、正常HTTP26项及生产Web45项通过。真实历史材料副本关闭29项核对通过，原185表旧行、旧列及15份原件保留，6份策略全部撤销。自有服务与端口已关闭，浏览器保留空白页；真实来源与模型调用0。失败、阶段边界及回执见[验收记录](../assurance/evidence/safety-gate-fallback-2026-11-13.md)。
