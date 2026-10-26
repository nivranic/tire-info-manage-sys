# R77 Candidate AI Assistance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 当前会话按用户持续实施授权执行；不提交、不切换工作树、不丢弃既有 dirty。

**Goal:** 交付独立的、逐来源用途许可约束的车型轴位规格候选 AI 辅助链路，允许模型从当前候选中选择有依据的后续核对选项或拒选，并明确性能证据不足。

**Architecture:** 服务器从 R69 重建当前车型、精确 SKU、全部人工关系和本人偏好，以白名单形成最小外发投影，独立保存准备、用途许可修订和一次性同意消费。复用 AI 网关、持久预算及调用账本，以专用模型合同校验选择及各候选理由；通用分析、流式、规则和报告不得消费此准备包。

**Tech Stack:** FastAPI / Pydantic / SQLAlchemy / SQLite 私库；React / TypeScript；现有 OpenAI Responses 优先网关。

---

## 范围与依据

- 原规格 `docs/requirements/2026-09-26-tire-intelligence-original.md` 第 215–225、658、787、1194 行约束偏好、精确身份、引用与发布评测。C 完整范围仍包括专业性能取舍及其真实评测，本轮只完成规格域的首批工程切片。
- R75 B、R70 测试事实摘录、R71/R74 `provider_use=false/export=false` 不变。本轮不读取 TestEvent、R71 断言、专业材料或其派生成绩用于外发；不改变其用途许可。
- 没有七维精确 SKU 性能证据，不以型号、Acoustic、同尺寸或人工审核推断抓地、安静、耐磨、官方原配或安装安全。偏好排序只能形成待研究维度。
- 真实 Provider 连通、语义质量、真人 Golden 和完整 V1 发布门仍待独立验收。合成自有材料正例只证明工程链路。
- 已核 R76 最终清单 SHA `012ace3ba222adba598d62a1670cad83eee5546459cd1e9c1ec71658600a703f`，1506 项先前绑定保持。新基线 `.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/baseline.json`。旧回执及旧计划不覆盖。

## 冻结不变量

1. 需要登录；额外保存准备时的账户 ID，并在准备、提交、尾读及历史读取核对。现有同 cookie 会话聚合仍不能称为全站严格账户隔离。
2. 显式选择 2–20 个去重精确 SKU。R69 `truncated=true` 硬拒；所选任一缺失、关系失效、未知未经确认或身份/原件变化则整组拒绝，禁止静默删项。完整当前重建签名绑定全部已扫描关系与偏好版本。
3. gate 使用完整本地依赖；外发只允许精确身份、车型轴位要求、match/unknown/not_declared 检查、已审关系引用、偏好和服务端理由。不得发送整份 facts、来源自由文本、来源 URL、原件、审核备注或专业测试内容。
4. 理由 ID 绑定 variant、车型/配置/轮毂/轴位、关系修订、字段/原值/状态。肯定理由仅可来自当前有效已审关系或真实 match；unknown/not_declared 仍逐项展示，不能作匹配理由。
5. 用途许可独立于个人同意。逐来源实际投影绑定 source kind、snapshot、原件 hash、所用字段和投影 hash；许可为追加的 grant/revoke，绑定 `candidate_spec_assistance@1`、实际 Provider 范围、有效期和修订代次。缺任一依赖许可即不可外发。管理员声明须包含权利人、许可依据、许可证据 hash 和用途确认；管理员身份不证明其拥有来源权利。生产来源不得自动授予许可，合成正例明确自有。
6. grant 后必须重新准备。撤销再恢复同内容也产生新代次，旧准备/同意不得恢复。撤销入口不能依赖 grant 仍有效，避免过期后无法撤销。
7. 个人同意绑定 actor、准备/包 hash、问题、Provider/model/endpoint、隐私/预算策略、prompt/schema 和实际 body hash。没有配置时可读本地缺口，无 consent hash 或 sendable 不提交。私有偏好和问题遵从现有 allow_private。
8. 同准备只能一次持久消费；UUID 同键只读重放，不再付费，异键重复消费拒绝。预留锁内及真正 adapter.generate 前以新读事务重建全部依赖、许可和配置；失败留存失败完成，不自动再调。调用期间的外部世界变化无法被本地事务锁保证，不能作绝对实时性承诺。
9. 复用 `reserve_response/execute_response`，数据库反查准备记录强制专用 claim。不得只以 payload purpose/origin 开关绕过身份/字段门；保留既有身份检查并建立明确的 C 字段合同。不得让空 evidence 成为绕过手段。
10. 专用输出只允许 choose/abstain、候选 ID、各自合法理由 ID 和受限不确定性代码。拒重复键、非有限数、未知/重复 ID、错候选理由、额外字段和自由文事实。服务器渲染来源事实、条件性模型选择及完整不足，明确未证明优于未选项，不产生性能排名/综合分。
11. 首批同步，不开放流式/报告/规则。通用 prepare/analysis/stream/lookup/history/save/export 必须排除或拒绝 C 包及结果，不能通过既有 generic `grounded_answer` 旁路。专用详情是冻结历史，不能显示为当前有效推荐；重开核对当前许可与依赖，失效不伪装新结果。
12. 各对象追加保护，迁移只在 GUID 私库验证；正常库不启动、不迁移。无凭据、cookie、密码摘要或私库进入公开回执。
13. 专用准备类型先按 pack_id 无 actor 过滤查数据库，再核 owner；查不到 actor 匹配不得回退普通分支。同账户跨 session、外账户、泛用幂等重放和所有 pack/detail/report 读取均使用相同结构判别。许可签名绑定具体 head revision ID/代次/expiry；预留后预检失败落失败 completion，不能留下可自动重试 pending。
14. selected 与 not_selected 是输入候选的精确分区；未选或拒选不能修改 R69 eligibility 或宣称不适配。固定 ranking=not_computed、performance_score=null；所有七维性能未知时，不得渲染任何偏好性能优先序。规格选项不表明比未选项更好。

## Wire 合同

后端与 SDK 以本段字段名为准；必要新增字段应在实现前由 Root 与审查 agent 确认并单独记为后续勘误，冻结正文不回写。

- `POST /v1/ai/candidate-preparations`：`{selection,expected_preference_revision,expected_preference_fingerprint,variant_ids,question}`。
- 准备响应：`{schema,purpose,preparation_id,pack_id,fingerprint,selection,preference,candidates,dependencies,blockers,provider,consent_hash,expires_at,sendable}`。`dependencies[]` 含 `id,source_kind,snapshot_id,raw_hash,projection_hash,fields,authorization`；authorization 含 state/revision_id/revision/expires_at 或 null。provider 无配置为 null，有配置含 provider/model/state/policy_fingerprint/body_hash/reserved_tokens。候选含 variant_id/identity/reasons/unknown_fields；理由含 id/text 与核对引用，不夹自由事实。
- `POST /v1/ai/candidate-preparations/{preparation_id}/authorizations`：管理员，`{dependency_id,provider,expected_revision,action,rights_holder,license_basis_url,license_basis_note,license_evidence_sha256,expires_at,acknowledged}`；action=grant|revoke。许可依据 URL 不接受身份参数或凭据。旧预期修订冲突 409，不覆盖既有修订。
- `POST /v1/ai/candidate-recommendations`：`{preparation_id,consent_hash,allow_external_processing}`，`Idempotency-Key: UUID`。false、缺许可、错账户、配置/证据变化均零调用。
- `GET /v1/ai/candidate-recommendations/{id}?mode=history` 和 `GET /v1/ai/candidate-recommendations?mode=history&key=UUID`：专用只读恢复。结果含 id/pack_id/state/usage/reserved_tokens/error_code/created_at/completed_at/purpose/answer；详情含冻结准备与 `current=false`，不因恢复而调用模型。answer 包含 decision/selections（带服务器理由）/uncertainty 与明确边界；缺记录 404。

## Task 1：后端与独立用途门（backend agent 所有）

**Files:** 新建 `apps/api/tire_api/candidate_ai.py`、`candidate_ai_contract.py`、`candidate_ai_models.py`；修改 `db.py`、`migrations.py`、`main.py`、`ai_execution.py`、`ai_analysis.py`、`ai_stream_routes.py`、`ai_stream_store.py`、`ai_rule_drafts.py`、`reports.py` 等必要入口；新建 `apps/api/tests/test_candidate_ai.py` 与 support。

1. 阅读 R69 全量重建与原件校验、现有 AI 预算/身份/field gate、各通用读取/保存入口。按本合同实现 gate 与最小投影，严格分离本地签名与 Provider 内容。
2. 实现三类追加账本、私库 additive migration、权限先于校验、授权修订/ABA、prepare、幂等单次消费及专用历史。普通入口数据库反查拒绝专用准备。
3. 先核关键拒绝用例，再实现合成自有材料正例；测试从实际路由准备/授权/再次准备/提交/恢复。受控 adapter 捕获真正 body，不 Mock 候选投影/仓库/身份或预算门。
4. 使用预绑定 GUID 库的受护栏 harness 跑目标测试，记录来源首尾 hash、精确命令与各阶段结果；失败也保留。

## Task 2：类型、SDK 与界面（frontend agent 所有）

**Files:** 新建 `packages/domain-types/src/candidate-ai.ts`、`packages/api-client/tests/candidate-ai.mts` 与合同 tsconfig、`apps/web/components/candidate-ai.tsx`/`.css`；修改共享 types/SDK 导出、package scripts、`personalized-home.tsx`。

1. 阅读 `apps/web/AGENTS.md` 及对应 Next 指引。新增独立类型和可注入 SDK 路由，所有读取带 history，提交携 UUID 与明示 consent hash，不自动重试。
2. 首页 R69 候选下挂独立规格辅助面板，显式选择候选、输入问题、准备，展示最小外发字段/用途许可缺口/模型和预留预算，然后单次同意提交。准备或 actor/选择变化清空同意；迟到响应隔离。
3. 连接失败保留请求标识，先专用 GET 恢复，不能自动 POST。结果区分来源事实/模型候选草案/完整不足，长期保留性能未建立提示；无配置和无许可流程仍可解释阻断原因。
4. SDK 正反例和 workspace 类型检查；三端前端构建属于 Web 产物，不声称新原生设备验收。浏览器私库流程另由 Root 验证。

## Task 3：独立反例（review agent 所有）

**Files:** 新建 `apps/api/tests/test_candidate_ai_review.py`；独立报告放 `.artifacts/review-r77-<GUID>/`，不得改生产实现。

至少覆盖：缺任一许可、撤销/恢复代次、错 Provider/model/body、prepare 后偏好/关系/身份/原件变化、truncated、选择 A 引用 B 理由、unknown 作 match、额外自由事实、重复 JSON key、同键/异键消费、actor 换绑、预留后实际调用前撤销、普通分析/stream/报告/历史旁路。真实外网/子进程/正常库为零。独立 agent 不能从产品输出自动生成预期。

## Task 4：集成、回执与交接（Root 所有）

1. 对冻结合同执行审查勘误；核工作区与 R76 旧回执保全。并行修改者不得回退他人改动，冲突由 Root 顺序处理。
2. 执行后端最小相关回归、独立反例、SDK/typecheck/三端前端构建；用 GUID 私库及受控 Provider 运行真正 prepare→授权→新prepare→提交→恢复，核零权限调用与专用输出。
3. 浏览器桌面与 390/320 窄屏验证实际新面板；如宿主或工具阻断，报告精确限制，不能用构建代替运行时验收。
4. 新建 `docs/assurance/evidence/round-77-candidate-ai-assistance.md`；更新 README/两交接入口/风险登记。记录本轮只是 C 规格域工程首批，专业性能推荐、真人评测与真实 Responses 未关闭。
5. 新清单绑定源码、文档、受管理配置与公开回执；核旧 dirty 全保留、requirements 与历史回执原字节，最终独立审计。不得记录凭据与私库；Goal 保持 active。

## 验证环境与回滚

- PowerShell7：`C:/Program Files (x86)/PowerShell/7/pwsh.exe`；Python：`apps/api/.venv/Scripts/python.exe -X utf8 -B`。
- 导入 main 前清 TI/TIRE/Provider/代理配置，`TIRE_DATABASE_URL` 与 `DATABASE_URL` 同时指向同一 GUID 私库，objects/bundles 也使用私根。护栏核数据库 resolved path，禁止正常 DB、真实网络和未许可子进程；Windows SelectorEventLoop 内部 socketpair 只按本次精确 endpoint 放行。
- Parser 8 秒墙钟/5 秒 CPU/384 MiB/并发 2 保持；`os.link` 沙盒 WinError5 时保留失败，在宿主用同护栏补验，不 Mock 仓库。
- 命令由新 harness 收口，至少 `pytest apps/api/tests/test_candidate_ai.py apps/api/tests/test_candidate_ai_review.py`、`npm run test:candidate-ai --workspace @tire/api-client`、`npm run typecheck` 及三端前端 build，分阶段记录，不能累加为全量。
- 回滚仅撤销本轮新增路由入口或保持未配置阻断、对许可追加 revoke，不删除历史。正常库未应用迁移，无生产回滚操作。所有既有 dirty 保留。
