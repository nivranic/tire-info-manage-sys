# Safety Gate外部受许可读取 Implementation Plan

**Goal:** 让外部客户端以独立API Key读取本人成功核验、当前许可覆盖的Safety Gate周报告警，保留精确证据、字段范围及历史状态。

**Architecture:** 接入既有查询归属收据、受管许可账本和Bearer边界；新增独立Safety Gate读取投影、签名分页与SDK校验。普通来源查询保持在线优先，外部读取只读取明确指定的已核验历史，不借Cookie、不触发抓取、不继承普通查询回退权限。

**Tech Stack:** FastAPI、SQLAlchemy、受管许可账本、共享TypeScript SDK及现有API Key管理Web。

## 2026-11-13交付点

步骤1至6已完成本计划的受管SQLite实现与限定验收：归属／许可、Reader／HTTP、专用scope、分页、共享SDK及Web Key管理均接通。最终13模块344项、SDK／三端类型／Web55项／生产构建、官方历史材料HTTP28项、SDK75条及生产Web签发／撤销／布局通过；测试Key和grant撤销，服务关闭。真实来源／模型调用0，正式PG外部Reader、公网与Native继续开放。见[本轮验收](../assurance/evidence/safety-gate-external-api-2026-11-13.md)及[接手卡](../AGENT-HANDOFF-CURRENT.md)。前置归属／许可交付另见[此前记录](../assurance/evidence/safety-gate-external-foundation-2026-11-13.md)。

## 计划启动时的证据与设计选择

基线为 `d8a42a1`，工作区干净。原规格要求公共REST、API Key、证据读取、游标分页及外部权限。当前外部轮胎事实接口已要求新查询冻结的账户归属与具体快照／字段许可；Safety Gate独立表尚未接入这两道门。

选择复用许可与归属机制，再新增源专属投影。直接复用Cookie业务路由会绕过Bearer范围；把欧盟告警映射成轮胎SKU会丢失未知适用性，因此不采用。当前OwnedFactReader为SQLite受管实现，PostgreSQL正式外部读取仍是既有开放项；本轮应明确各后端实测范围，不把普通PG查询通过当作受管外部读取通过。

## 数据与权限合同

- 普通Safety Gate成功查询在发起时冻结登录账户。匿名旧查询不回填归属，后来登录／会话换绑不能追认；后台与单次回退不新增外部归属。
- 新增独立 `safety-gate:read` scope，旧Key不自动获得。沿现有有效期、撤销、账户删除、速率、loopback／TrustedHost及Bearer-only边界。
- 固定来源eu-safety-gate及服务端配置的grant路由。许可审核沿现有CLI与管理员凭据，保存真实许可原文、摘要、操作者和逐修订审计；哈希不是合法权利证明。
- 许可绑定支持SafetyGateSnapshot／SafetyGateVerification，验证完整原件、查询、Parser及成功核验关系；不将其写入通用轮胎Snapshot。
- 目标读取端点为 `GET /external/v1/safety-gate-reports/{report_id}/alerts`，必须提供本人成功query_id；mode明确为history。索引查询或失败／回退query_id不能授权周报内容。
- 在一次新鲜受管事务内重验原Bearer、账户、查询归属、许可当前头、原件及字段投影。原件正文、图片字节、私人规则、Cookie、账户ID和许可审核文档不进入外部响应。
- 输出保持local_snapshot、官方报告身份、原生告警身份、已获准字段、原件哈希／时间／Parser与unknown适用性，不生成SKU适配或解除风险结论。
- 游标绑定Key／owner承诺、路由、query_id、report_id、limit、快照和许可头；15分钟固定期限，不跨Key复用。后续页许可变化、撤销或证据损坏须拒绝，不混页。
- 全链有输入、数据库物化和响应字节上限；无权／不存在的私人证据统一拒绝。SDK独立可信origin、omit Cookie、禁止重定向、严格DTO、有限响应、不自动重试。

## 分步实施

1. 新增 `apps/api/tests/test_safety_gate_query_ownership.py`，先证明正常登录查询缺少归属收据。修改 `safety_gate.py` 复用capture_query_actor／create_query_with_owner，覆盖匿名、登录、会话换绑、失败／304与单次同意，保持既有SQLite／PG普通查询行为。
2. 扩展 `external_fact_governance.py` 的固定来源证据绑定，新增Safety Gate许可回归；旧轮胎许可链和摘要保持原合同。审核记录继续不可变，复用已有CLI。
3. 新增源专属外部Reader与HTTP路由，复用受管事务、凭据重验、查询归属和许可头；实现闭合字段投影和签名分页。新增权限、跨账户、旧查询、源／快照／Parser错绑、策略撤销、游标、容量及并发反例。
4. 在 `external_api.py`、共享类型及SDK严格校验中登记独立scope；扩展API Key界面和可信外部SDK，保留旧调用方及原生传输约束。
5. 运行新模块、已有外部Key／库存、归属、许可、轮胎Reader／分页及Safety Gate相关受管回归；运行SDK、三端类型、Web及生产构建。先以合成材料覆盖权限反例，再以可核验官方许可及明确归属的真实材料进行正常HTTP验收。
6. 完成正常Web签发／撤销凭据及生产客户端消费、来源原件和数据关闭核对。保留失败和源码绑定，更新文档、审查全部差异，再提交推送并独立核对远端。

## 复验与发布边界

新测试须登记 `scripts/run_api_worker_regression.py`，每轮使用新的 `.artifacts/sg-external-*` 槽；执行期间不修改其受管输入。新clone重建许可材料、隔离账户与运行时，真实材料和凭据不提交。

先补齐以上链路后才宣称本阶段接通。完整外部CRUD、生产IAM／RLS、正式PG外部Reader、真实OpenAI、Native设备及其他V1 Gate仍按原范围继续推进。若回退，先撤销测试／部署Key及受控grant路由，保留只追加归属、许可与审计历史。
