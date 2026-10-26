# Source Page Change Monitoring Implementation Plan

> 本文件是下一项的实施计划；产品、迁移和测试尚未按此实现或执行。沿用当前 chat 的实施、独立审查与 Root 验证分工，不另建或移动 worktree，不 commit/push。多人共享工作区，所有实施者只修改各自明确拥有的文件，保留他人及既有 dirty 编辑。用户已经授权继续独立工作，不再询问实现方式选择。writing-plans / brainstorming 的分解、取舍和渐进验收原则适用；其中新建 worktree、逐任务 commit 和重新询问选择的通用步骤由本次明确边界替代。

**Goal:** 已登记轮胎来源在固定查询范围内成功采纳的文本原文发生变化时，记录来源级事件，向显式启用的本机共享规则投递站内提醒，并能重开前后证据。

**Architecture:** 复用 `TireQuery`、`MonitorJob`、`AlertRule` / `AlertRuleRevision`、现有 Worker、来源 generation 和采纳事务。新增独立的来源页事件与来源页通知两表；页面事件不依赖或虚构 SKU，不写入 `ChangeEvent`。仅比较同 URL 的成功采纳文本哈希，页面通知使用新增 API / DTO，旧 SKU 提醒、Interest、Webhook 和 AI 输出合同保持各自语义。

**Tech Stack:** 现有 Python / FastAPI / Pydantic 2 / SQLAlchemy 2、SQLite / PostgreSQL DDL、TypeScript、React / Next；使用 stdlib SHA-256，不新增依赖或执行框架。

---

## 1. 依据、已确认现状和完成口径

- 原需求：`E:/Mix/SunBrowser/跨平台轮胎查询、证据化监控与 AI 知识应用需求规格及技术方案.md:67` 的信息监控明确包含“参数变化、新规格、新 OE、新技术、标签变化、测试发布、安全召回、页面变化”；367–391 行给出关注更新及 `raw_snapshot → SHA-256 → ... → alert evaluation` 主链。仓内原文副本为 `docs/requirements/2026-09-26-tire-intelligence-original.md`。
- `docs/HANDOFF-2026-10-18.md:184` 的完成清单把完整页面变化列为待办。其历史轮次和旧验证不能作为当前功能已实现的证明。
- 写计划时实际读取的 `docs/HANDOFF.md` 最新前缀仍为 R132。R133 的关注所有权工作由 Root 单独收尾，本计划不改其源码、回执或交接冻结。实施时先读届时最新前缀，避免覆盖并行增量。
- `service.QueryService.record_success` 已按原文哈希变化追加 `Snapshot`，但只有结构化 `facts_hash` 变化或首次观察才追加 `ChangeEvent`。当前 `monitoring.Kind` 仅 `facts_changed` / `variant_observed`。
- `interest_governance.append_catalog` 只对前后 SKU 集合的对称差产生 `TireCatalogRevision`。相同成员、相同字段而原文变化，不会产生等价页面事件。当前产品中未找到名为 `SourceCatalogEvent` 的类型；不能假设存在该入口。
- 当前迁移尾为 `028_ai_price_versions`。本计划暂用 `029_source_page_monitoring`，实施前必须重新核尾号及并行迁移；发现占用即重新命名实际下一号，不改写历史迁移。
- 这是已采纳文本范围的首片，不覆盖解析失败原文、quarantine 原文、任意网页发现、PDF / Material capture、页面区块语义 diff、动态噪声消除或长期真实源质量。本片通过也不关闭“完整页面变化”及完整 V1 Gate。
- KIT 捕获原 UUID 的结果仍未确认；本计划不恢复、重发或替换 UUID，不打开它的保留私库，不要求 EPREL Key、真实模型凭据、外部材料或设备。

## 2. 已确定的取舍

采用“新来源页事件 / 通知 + 复用既有任务 / 规则”。直接把 `page_changed` 塞入 SKU `ChangeEvent` 会受到非空 `variant_id` 和现通知的 `TireVariant` inner join 限制，既遗漏零 SKU 页面，又容易制造假身份；不采用。把页面事件作为第十个 Interest domain 会牵动冻结、匹配、历史查询、外发许可及 Webhook 合同，超出首片；不采用。

首片规则与通知维持现监控的 `scope=local_workspace`。它们是本机共享工作区记录，不是私人兴趣，不新增账户归属或服务器租户隔离声明。原来的私人关注、私人 AI 草稿及其授权仍走现有路径。

## 3. 固定 scope 与事件判定

### 3.1 查询身份

复用以下实际算法，不另造模糊匹配规则：

```python
query = TireQuery(...).canonical()
query_key = digest(query)
job_id = digest({'source_id': source_id, 'query': query})
```

- `TireQuery` 只含现有 model / size；model 使用现有规范化，size 保留正式 `R` / `ZR` 区别。页面匹配不调用 `monitoring.matches` 中面向 SKU 的 substring / `ZR → R` 匹配。
- scope 是精确 `source_id + query_key`，同时保存 canonical query 供核对。普通查询的 `selection_filters` 只是输出投影，不进入页面 scope；不能因换筛选条件重复建页面监控任务。
- 来源必须来自现有已登记轮胎目录，型号属于该来源支持范围，遵守 `requires_size`。不接受用户输入抓取 URL；最终 URL 来自现有 Adapter 的已采纳结果。
- 同来源、不同 canonical query 仍是不同观察范围；即使落到相同 URL，也不做跨 query 合并或去重。

### 3.2 基线与比较条件

1. 沿用 `record_success` 在 ingestion 锁内取得的该 source/query 最近成功 `Verification`（`ok` / `not_modified`）作为前驱，不能取全局 SKU 最新事实，也不能取最近一次“发生变化”的记录。
2. 新观察必须完成现有来源 / lease / Parser / quality 门并成功采纳，且本次 verification status 为 `ok`。
3. 前后 Snapshot 均存在，source_id / query_key 与两 Verification 一致，前后 `source_url` 完全相同，且两个 Snapshot.raw_hash 不同，才产生 `page_changed`。
4. 没有前驱时仅建立基线，不叫页面变化或新发布。URL 不同时不跨地址比较；新成功观察自然成为后续该 query 的基线。首片不新增 URL 迁移事件，也不把 URL 漂移称为原文变化。
5. 304、相同文本、仅 Parser 版本 / identity 改变、仅内容类型或验证时间变化不产生页面变化事件。字段与成员相同但原文哈希不同必须能产生事件；参数变化与页面变化可以各自成立，不能互相替代。
6. 失败、未通过质量门、历史读取、历史重解析候选、授权回退都不产生本事件，也不推进成功采纳基线。

`Snapshot.raw_hash` 当前是 `SHA256(result['body'].encode('utf-8'))`。公开名称使用“已采纳文本原文变化”；不声称它是压缩 HTTP 字节、PDF 原件字节或页面语义哈希。首片不增加全局 HTML 清洗、忽略时间戳或其他噪声剔除；这些必须后续按来源有版本地设计。

### 3.3 两张新增表的最小字段

新增 `apps/api/tire_api/source_page_models.py`，不改变 `Snapshot` / `Verification` / `QueryRun` 的列或旧行。

| 表 | 必需字段与关系 |
|---|---|
| `source_page_changes` | `id`；`schema_version` 固定 `source-page-change@1`；`source_id`；`query_key`；`query` canonical JSON；`previous_verification_id` / `verification_id` 均 FK `verifications.id`；`previous_snapshot_id` / `snapshot_id` 均 FK `snapshots.id`；`source_url`；`previous_raw_hash` / `raw_hash`；`observed_at`；`fingerprint` |
| `source_page_notifications` | `id`；`rule_id` FK `alert_rules.id`；`rule_revision_id` FK `alert_rule_revisions.id`；`event_id` FK `source_page_changes.id`；`delivered_at`；nullable `read_at`；绑定除 read_at 外全部不可变字段的 `fingerprint` |

- 事件 `verification_id` 唯一；通知 `(rule_id,event_id)` 唯一。所有 ID 使用现有 uid 风格，字段长度和 UTC 时间沿用项目类型。
- source/query 前后关系通过 Verification 与 QueryRun 重新核对：两个 Verification 的 source/query 与事件一致，引用 Snapshot 与各自 snapshot_id 一致，对应 QueryRun 的 canonical query 与 query_key 一致。QueryRun 自身及 actor_session_id 不复制进公开通知。
- 事件哈希前后不同、SHA 格式及版本固定值在闭合输入 / 持久化检查中验证；事件不接受外部 POST actual，不由客户端提供 observed_at、hash 或快照绑定。
- 事件完全只追加；通知除 read_at 外禁止更新或删除。采用现有新实体的 SQLite 原生 / PostgreSQL DDL 与 ORM 追加保护模式，禁止 conflict REPLACE 偷换旧记录。通知指纹不因已读变化重算。
- 不复制 body、parsed_variants 或 FactVersion 到新表。Parser 版本、原文观察时间、核验时间通过既有 Snapshot / Verification 取值并分别展示。
- 去重绑定“本次采纳核验”而非哈希对。A→B→A→B 是三次变化，第三次不得被第一次的 `(A,B)` 吞掉。

### 3.4 事务、调度与权限不变量

- 在 `record_success` 已 flush 新 Verification 后调用来源页 helper；调用者已经持 ingestion 锁。helper 不 commit、不另取锁、不补历史、不自动重试、不吞通知错误。
- Snapshot / FactVersion（如有）/ Verification / page event / page notification 属于同一采纳事务。注入通知写入失败时全部回滚，不留下已采纳事实但丢失提醒的半成功状态。
- 规则按该事件发生时的有效修订评估，须已启用、未归档且 source/query 精确一致。保存 `rule_revision_id`；之后修改规则不能重写旧提醒。
- 显式限制规则及其有效修订创建时间不晚于事件 observed_at；再次评估历史事件不能向后来启用或新建规则补发。暂停期间无通知，恢复规则保持现有“恢复为暂停”语义。
- 复用 `MonitorJob`、`claim_job`、`guard_claim`、`finish_job`、现有 4 小时至 7 天间隔、来源间隔和租约。页面 / SKU 规则共享 source/query job；不多抓一次，不把 Interest 保存变成轮询。
- `assert_source_access` / `assert_source_run_access` 的 generation、来源暂停归档、Parser gate、原生 SSRF/robots/大小/超时约束继续生效。Worker 仍以 `fallback_policy='never'` 执行，不做离线报警。
- 当前共享监控权限不扩成服务器身份保证。页面 API 复用本机正常会话和审计路径，不公开 actor_session_id、cookie、凭据、lease token、请求幂等 key；不增加公开原文导出用途。

## 4. 规则与 API / SDK 合同

### 4.1 复用规则

现 `RuleSettings.kinds` 增加 `page_changed`，但页面模式必须独占：`kinds == ['page_changed']`、`variant_id is None`、`fields == []`、`conditions == {}`。保留旧两种 kind 的全部原组合；不把技术条件或字段条件解释为页面选择器。

页面 / SKU 模式在已创建规则中不可互换；编辑试图切换模式返回固定 422 并提示新建另一规则，原修订保留。旧 SKU 规则内部的 kind 编辑行为保持。创建页面规则沿用 `validate_rule_target` 的来源 / 支持型号 / 必需尺寸检查；编辑、启用及归档恢复沿用现 revision fence 和审计。

`interval_for` 对 `variant_id=null` 的页面规则可自然调度；旧 `record_alerts` 继续只处理 SKU ChangeEvent，新 helper 只读取页面规则，不向旧 alert 表写假 change_id。

### 4.2 新增独立页面通知入口

在新 `source_page_monitoring.py` 注册，并从现 `register_monitoring_routes(app)` 薄接，避免为了此功能重构 main：

| 方法 | 合同 |
|---|---|
| `GET /v1/source-page-notifications?mode=history&unread=false&offset=0&limit=25` | shared workspace 历史列表；offset>=0，1<=limit<=50；返回 items / total / offset / limit |
| `GET /v1/source-page-notifications/{id}?mode=history` | 精确提醒、冻结规则修订和来源页事件详情；引用损坏返回固定错误，不能猜另一快照 |
| `PUT /v1/source-page-notifications/{id}/read` | 闭合请求 `{"read": true/false}`；幂等设置已读，只改 read_at，追加现有审计 |

公开 `SourcePageNotification` 包含自身 ID / 已读 / 投递时间、rule_id / rule_name / rule_revision、`event`（source/query、前后 Snapshot / Verification 引用、URL / hash / 原文观察与核验时间）、`scope='local_workspace'`、`data_state='local_snapshot'`。不包含 `variant_id`、SKU identity、参数 changes 或原文 body。

列表只读元数据，不加载原文；详情重核指纹和引用闭包，校验需要原文时按既有有界文本读取并复核 SHA，不把未验证 metadata 称为完整原件核验。前后原文打开复用现有 `/v1/evidence/{snapshot_id}` 和证据检查器；不新增另一套下载、渲染或外发通道。

旧 `/v1/notifications`、`LocalNotification` 及其 AI explain 合同保持现状。SDK 增加独立 list / detail / mark 方法和 AbortSignal，不给旧 DTO 填 null identity。页面通知不提供“AI 解释这次变化”按钮，不调用模型。

### 4.3 AI 草稿兼容门必须同时交付

`ai_rule_drafts.ApplyRequest` 引用通用 `RuleCreate`，扩展后会接受新 kind；当前 apply 只核 prepared fields，不能依赖旧 Proposal schema 保证人工提交仍在能力内。

在 apply 新写入前核对：

```python
if not set(payload.rule.kinds) <= set(pack.payload['capabilities']['kinds']):
    raise HTTPException(422, '规则包含本次支持能力之外的提醒类型')
```

冻结 capabilities 仍只有原两种 kind，`ai_rule_contract.py` 的 Proposal、prompt 和模型输出能力不扩。测试旧合法 AI 草稿应用、原幂等重放仍通过；手工把已完成旧草稿的 rule.kinds 改为 page_changed 必须 422，且规则 / application / 调度均无新写入。此用例使用合成 completed 记录，不请求真实模型。

## 5. 安全验证入口的先行窄修

现有正式后端入口为 `scripts/run_api_worker_regression.py`，R119 / R121 已实际复用，不新建 launcher / guard。其 `--phase` 支持 selfcheck / collect / run；`--targets` 接受登记文件或 nodeid；`--output-root` 必须位于本仓 `.artifacts` 下且尚不存在。可选 `--actual-dir` 只用于明确 R76 actual run，本项不设置。

bootstrap 先清理继承的密钥、代理、TI_/TIRE_/DB 环境，将 `TIRE_DATABASE_URL` / `DATABASE_URL` 固定到新槽 `private/bootstrap.db`，tmp / objects / bundles / pytest basetemp 和 R119 测试目录也固定到同槽；安装 `RegressionGuard` / `ChildPolicy` 后才 pytest collection。未指定 targets 会选择显式全部模块，因此本项必须提供具名目标。

当前已确认 runner 的 teardown 对 `sys.modules.get('tire_api.main')` 使用 `getattr(loaded, 'app', None)`；在 R115 的 lazy export 下可能因此构造默认 app。虽然 URL 已指向新槽，仍不满足“未使用时不构造默认 app”的边界，先作窄修：

```python
loaded = sys.modules.get('tire_api.main')
cached_app = vars(loaded).get('app') if loaded is not None else None
if cached_app is not None:
    cached_app.state.database.engine.dispose()
```

实际实现保留现有异常处理和资源回执，不通过 getattr / hasattr 解析 app，不把当前未缓存 app 当需要关闭的实例。以未缓存模块的 __getattr__ 陷阱、已缓存 stub 的 dispose 次数及既有 lazy main 单元验证该分支；不运行默认工厂补 smoke。

runner 会对既有 R38 备份作文件字节哈希保全，guard 也有该特定库的既有 readonly 例外；这不等于本项获准建立该库的 SQLite 连接。本项目标不得连接正常或保留 SQLite，不添加使用该例外的测试、不放宽白名单。若执行合同连备份字节保全读取也禁止，先由 Root 单独解决入口合同冲突，不能静默绕过 guard 或移除保全检查。

## 6. 分阶段任务与文件所有权

以下是下一轮实施任务。每阶段先补有意义的负例，再最小实现，再由 Root 用既有入口运行；本计划写入本身不运行这些动作。

### Task 1：修正安全 runner 的 lazy cleanup，登记新测试

**Owner:** 验证入口负责人；不与后端 worker 同改 runner。

**Files:** 修改 `scripts/run_api_worker_regression.py`；优先在现有 `apps/api/tests/test_main_lazy_app.py` 增加 cleanup 陷阱 / 已缓存分支回归；新页面测试模块出现时登记 `TEST_MODULES`。

1. 将 cleanup 的缓存查找提取为可单测的窄 helper，保留 dispose 异常处理与原回执语义。
2. 用新模块对象的 __getattr__ 记录/拒绝 app 访问；未缓存 cleanup 应零访问零构造。缓存假 app 应仅 dispose 现有实例一次。
3. 本阶段不预登记不存在文件。Task 2 / Task 3 实际创建 `apps/api/tests/test_source_page_migration.py` / `apps/api/tests/test_source_page_monitoring.py` 时，由验证入口负责人同步加入 `TEST_MODULES`；目录与显式清单不一致会在任何 phase 前报 `explicit_module_manifest_drift`，不能关闭此校验。
4. Root 用 fresh selfcheck，再 collect / run 具名 lazy main 模块。保存实际失败与修复后新批证据，不合并为一批通过。

### Task 2：两表、迁移和持久化不变量

**Owner:** 后端负责人，拥有 `source_page_models.py`、`db.py`、`migrations.py` 和两个新 backend 测试文件；不得覆盖同时进行的其他迁移。

**Files:** 新建 `apps/api/tire_api/source_page_models.py`；修改 `apps/api/tire_api/db.py` / `migrations.py`；新建 `apps/api/tests/test_source_page_migration.py`；按实际 schema 版本登记需要更新既有独立 version registry / 精确迁移断言。

1. 实施前重核迁移尾号；暂定 `029_source_page_monitoring` 仅创建两表、索引和 guards，不更新旧行，不重建旧表，不回填历史事件。
2. 编写基于真实旧 028 schema 的私有 fixture，独立断言新增 schema / ledger、旧行和旧对象保全、重复升级幂等、故障回滚。不能仅用当前 Base.metadata 创建“旧库”。
3. 为 SQLite 和 PostgreSQL 写同语义约束 / 保护。PG 本轮只静态 DDL 断言，除非另有独立真实 PG 执行；不从 SQLite 绿推 PG 绿。
4. 把模型注册接到现 `Database.initialize` 的 locked 初始化路径；版本隔离 fixture 保留原历史节点，不把精确 expected 偷改成宽 subset。正常库升级独立留账，本轮绝不启动正常入口来应用 029。

### Task 3：采纳 producer、规则和 API 事务闭环

**Owner:** 后端负责人；Task 2 后顺序实施，避免同时改 `monitoring.py`。

**Files:** 新建 `apps/api/tire_api/source_page_monitoring.py`；修改 `apps/api/tire_api/service.py`、`monitoring.py`、`ai_rule_drafts.py`；新建/完善 `apps/api/tests/test_source_page_monitoring.py`，向现 `test_ai_rule_drafts.py` 增加 capability kinds 负例。

1. 先覆盖：同 URL / 同 scope / 字段成员不变但原文 A→B 产生一个页面事件与一个启用规则通知，旧 facts 通知不伪造变化。
2. 写追加 helper，固定前后 Verification / Snapshot 闭包、事件指纹、唯一约束和只读元数据视图；在当前成功采纳事务的适当 flush 点接入。
3. 扩页面独占规则及模式不可互换检查，复用创建、revision fence、暂停归档恢复与调度。页面-only 规则也应使已有 job 可领取；相同 scope 的 SKU / 页面规则仍只有一个 job。
4. 实现三条独立页面通知 API、固定错误及审计；不修改旧通知 SQL union 或旧 LocalNotification 语义。
5. 补 AI apply kinds 门，保持旧 frozen capabilities 和模型端 schema。
6. 加注入回滚、重复 helper / 重启恢复、并发单赢家、来源 generation / lease 失效等真正边界测试；失败不得降低现有 guard 或采纳预算。

### Task 4：共享类型、SDK 和手工业务入口

**Owner:** 前端 / SDK 负责人；不修改后端 worker 所有文件，不覆盖 R133 工作台变更。

**Files:** 新建 `packages/domain-types/src/source-page-monitoring.ts` 并从 index 导出；修改共享 `AlertRuleSettings` 的 kind 类型、`packages/api-client/src/index.ts`；修改 `apps/web/components/monitoring.tsx`；新增具名 SDK 合同测试及其项目既有 tsconfig / script 登记。

1. 新 DTO 明确 shared / history 标志、原文观察与核验时间；不得复用 SKU identity / changes，也不暴露私有会话和 lease 字段。
2. SDK 薄接现有 transport，list/detail/read 传 AbortSignal，验证查询参数、已读 body、固定错误透传；旧通知 API 的请求与返回不变。
3. 手工新建规则可选择“来源原文变化”；选择该模式清理并隐藏字段 / 技术 / SKU 条件，不自动启用、不自动创建新来源或新 Worker。已保存页面模式不可切换成 SKU 模式。
4. 在现监控区域增页面通知块，显示原文变化待核对、source/query、前后观察 / 核验时间及证据按钮；复用任务详情与证据检查器。未知 raw 值按原文字符串展示，不生成参数差异或 AI 结论。
5. 新 UI 请求遵循当前 ownerSignal / effect 取消模式，避免组件卸载后的迟到写入；共享工作区数据仍不冒称私人归属。

### Task 5：Root 正式验证、限定验收和交接

**Owner:** Root 唯一执行和应用正式证据。独立 reviewer 审产品与验证入口，不把静审 ACCEPT 当实际运行。

1. 保存本轮实际受影响产品 / 测试 / runner 原字节和源绑定；不将 Git HEAD 总 diff 当本轮范围。确认其他 agent 已停止编辑即将验证的文件。
2. 完成 Task 1 的新入口 selfcheck；收集新测试；运行新 backend 两模块，再按影响运行下列必要回归。每次 fresh UUID 私槽，不重新打开旧批 SQLite，不把 red 回执覆盖成 green。
3. SDK、三端类型及现有受审生产 Web build 分组验证。只有新关注点或失败才扩大验证；不重跑 R127–R133 已过 UI 全套，不冒用历史 PWA 离线证据。
4. 受控私有 fixture 中实际走现 Worker 的固定 scope 合成来源，不启用真实官网/Provider；再做手工规则→成功采纳文本变化→独立通知→前后证据限定浏览器闭环。
5. 记录实际请求、来源性质、fresh 路径、失败批、资源终态和代码稳定性；汇总 resources_closed 不等于逐 SQLite DBAPI 句柄已核 close。只有实际完成后由 Root 更新报告和 HANDOFF；本计划不提前写通过数。

## 7. 具体测试选择与安全命令

所有 PowerShell 命令使用 `C:/Program Files/PowerShell/7/pwsh.exe`，从本仓执行；下面是实施后由 Root 使用的命令模板，当前未执行。每个 phase 使用独立且不存在的 output-root，不预创建它。若换新 shell，重新赋前四个普通变量；它们不是环境变量。

```powershell
$taskProject = 'E:/Mix/project/tire-info-manage-sys'
$taskPython = Join-Path $taskProject 'apps/api/.venv/Scripts/python.exe'
$taskRunner = Join-Path $taskProject 'scripts/run_api_worker_regression.py'
$taskTargets = @('apps/api/tests/test_source_page_monitoring.py', 'apps/api/tests/test_source_page_migration.py')
```

先完成新文件登记和 Task 1 cleanup 窄修，再执行 selfcheck；此阶段不执行业务用例：

```powershell
$taskSelfSlot = Join-Path $taskProject ('.artifacts/source-page-selfcheck-' + [guid]::NewGuid().ToString('N'))
& $taskPython -X utf8 -B $taskRunner --phase selfcheck --output-root $taskSelfSlot --targets @taskTargets
```

读取 actual result/selfcheck/guard 后，以新槽收集；collect 不能计入用例通过数：

```powershell
$taskCollectSlot = Join-Path $taskProject ('.artifacts/source-page-collect-' + [guid]::NewGuid().ToString('N'))
& $taskPython -X utf8 -B $taskRunner --phase collect --output-root $taskCollectSlot --targets @taskTargets
```

核对收集清单和目标范围，再以新槽运行新功能：

```powershell
$taskRunSlot = Join-Path $taskProject ('.artifacts/source-page-run-' + [guid]::NewGuid().ToString('N'))
& $taskPython -X utf8 -B $taskRunner --phase run --output-root $taskRunSlot --targets @taskTargets
```

cleanup 先行验证和必要回归分别用新槽，按实际影响保留或缩减具名 nodeid，不默认整仓 pytest：

```powershell
$taskLazySlot = Join-Path $taskProject ('.artifacts/source-page-lazy-' + [guid]::NewGuid().ToString('N'))
& $taskPython -X utf8 -B $taskRunner --phase run --output-root $taskLazySlot --targets apps/api/tests/test_main_lazy_app.py

$taskRegSlot = Join-Path $taskProject ('.artifacts/source-page-reg-' + [guid]::NewGuid().ToString('N'))
& $taskPython -X utf8 -B $taskRunner --phase run --output-root $taskRegSlot --targets apps/api/tests/test_monitoring.py apps/api/tests/test_monitor_conditions.py apps/api/tests/test_ai_rule_drafts.py apps/api/tests/test_monitor_task_execution.py apps/worker/test_monitor.py
```

额外选择只用于具体未决风险：来源权限接线变化时运行 `test_source_access.py` / `test_source_settings.py` 的对应目标；目录 producer 调用顺序变化时运行 `test_interest_governance.py::test_catalog_reentry_is_new_even_when_fact_and_snapshot_pair_repeat`；029 实际影响的历史迁移 expected 按精确 nodeid 回归。已有 `test_monitoring.py` 覆盖 future-only、双侧证据、暂停恢复、失败隔离、事务回滚、job 去重和租约；Worker 现用例 `test_scheduled_worker_persists_outcomes_and_never_uses_fallback` 可证明所测后台路径保持在线限定。

runner 的 source bindings 会读当前受管 Python / fixture / TS 输入并在末尾比对；这是现有安全入口行为，不扩写另一份 freeze/launcher。新测试使用 `tmp_path` 或显式本次 private 目录，不硬编码回写旧 `.artifacts`，不修改被测模块常量绕 guard。

通过依据为实际 result：selfcheck 成功、目标执行完整、无非预期 non-selfcheck denial、源稳定、资源汇总关闭及终态 exit0；失败原件保留，必要修复后新批重测。R119 / R121 报告中的 venv Python 3.12.10 是历史执行身份，下一轮需记录实际解释器身份，不能照抄旧值。Python audit/wrappers 不等于 OS sandbox。

## 8. 验收矩阵

| 场景 | 必须观察的结果 |
|---|---|
| 同 scope / URL 原文 A→B，字段与成员完全相同 | 一条 page event；启用页面规则一条通知；FactVersion / SKU changes 无伪变化 |
| 原文与参数同时改变 | 页面和 SKU 通知各按各自启用规则产生，前后证据绑定正确 |
| 首次观察、同原文、304、仅 Parser 改版 | 无页面变化事件；成功核验原行为保持 |
| URL 改变、不同 query、不同来源 | 不跨边界比较，不借用另一范围基线 |
| 成功空结果且通过原质量门 | 可建立/比较页面基线，不需要制造 variant_id；不得绕质量门强收空结果 |
| 来源失败、解析失败、quarantine、历史回退 | 无页面事件/通知，不误称成功采纳或离线变化 |
| A→B→A→B、重启及重复调用 | 三次真实变化可保留；同一 verification/event 重放不重复 |
| 规则晚建/晚启用、暂停、归档恢复、陈旧修订 | 不补发历史；恢复暂停；旧通知冻结原规则修订；stale edit 409 |
| 多规则同 source/query、同来源不同 query | 复用原 job / 来源预算；范围隔离、通知各一次 |
| lease/source generation 变化 | 旧请求不能采纳新 event/notification；原任务回执完整 |
| 通知写入注入失败 | 本次采纳及新事件通知整体回滚，重试新执行可正常成立 |
| 非法混合 kinds / SKU / fields / conditions | 闭合拒绝，无副作用，不静默忽略条件 |
| 旧 AI 草稿被人工改成页面 kind | apply 422，规则和 application 零新写入；旧合法 apply / replay 保持 |
| 坏事件指纹、错前后引用、损坏原文 | 固定受控失败，不替换成其他记录；无秘密或异常原文泄露 |
| 两表升级/重复初始化/故障回滚 | 旧 028 数据及 schema 对象保全；新约束按实际 DB 层生效 |
| 实际手工业务闭环 | 规则显式启用、独立通知可见、前后证据可重开，无模型/真实外网请求 |

## 9. 回滚与后续边界

- 本计划阶段只新增文档，回滚只涉及该新文档；不动 HANDOFF 冻结、产品或验证库。
- 实施时保存每个实际拥有文件的修改前原字节。需要撤回代码时按本轮范围精确恢复，不 reset/stash/clean，不覆盖并行 agent 的后续编辑。
- 发布前可先暂停/归档页面规则停止后续提醒；共享 job 若仍有 SKU 规则，继续按原规则运行，不删除任务或历史。
- 029 是追加 schema。优先停用功能并保留两表与历史；禁止为了代码回退删除正常/保留库表或证据。只在新建合成私库验证迁移事务回滚；正式库升级/备份/回退需独立执行合同，本项不代做。
- 不开展真实材料 capture、EPREL、模型/Embeddings、公开 Webhook 新领域、原生设备、真实 PG、默认正常库升级或生产部署。它们有各自未完成账，不因本片通过而关闭。
- 后续完整页面监控还需解析失败/隔离观察、来源许可边界、URL迁移事件、来源特定噪声策略与长期运行质量；不能用本片的 accepted text / synthetic 结果宣称全网页或完整 V1 已验收。

本文件截至写入时是待实施计划，无产品完成或验证通过声明。Root 后续依据实际执行更新对应正式报告；当前 HANDOFF 不修改。
