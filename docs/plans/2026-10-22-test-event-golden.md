# Test Event Golden Workspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让用户以既有测试事件和供审原件建立独立预期、人工复核和冻结集，并在真实产品界面消费冻结预期，查看当前或历史事件及精确身份桥的逐字段差异。

**Architecture:** 新建专用测试事件 Golden 模块及四张追加式表，保持旧 tire/vehicle Golden、RawCapture 与 Parser 发布合同。复用现有账户/admin、Signed/Fence/UUID 幂等模式、TestEventRevision 和 R71 材料/身份桥；服务端只读消费者从真实记录构造 actual，客户端只提供选择和冻结指纹。工程差异结果与本机审核状态独立展示，不将本机署名提升为真人 Golden 资格。

**Tech Stack:** 现有 FastAPI、Pydantic、SQLAlchemy、SQLite/PostgreSQL 迁移框架、TypeScript SDK、共享 React/Next 界面；无新依赖、Provider、网络来源或执行器框架。

---

## 已定边界与依据

Root 已审定专用模块方案，本会话按后端、UI/SDK、独立验证三线执行，无需再向用户确认设计。不 commit/push，不新建遗漏现有 dirty 的 worktree，不 reset/clean/stash，不回退其他代理改动。普通 API/正常库与保留证据库不得启动或打开；验证由 Root 使用审查后、固定输入的新私槽 launcher 执行。

原规格 `docs/requirements/2026-09-26-tire-intelligence-original.md:159–180,796,1138,1194,1300` 要求事件化原始值、单位、来源名次和条件，禁止直接跨事件排名，并要求人工审核 SKU/车型/测试真值及 Golden 零错合并。规格没有强制某种审核 UI；本设计只有在下面的实际差异消费者一并交付时才算完成，不能只存 JSON 和 approved 标签。

当前 `golden.py:55–69,178–194` 只接受 tire/vehicle RawCapture；`GoldenCaseRevision.capture_id` 是非空 RawCapture FK。备选方案是修改旧表可空捕获并扩展全部 kind 分支，或共享三张旧表另加测试内容表；两者都会影响旧查询、冻结集和 Parser 合同。本轮选独立四表，以既有模式复用控制逻辑，不伪造 capture，不重建旧历史表。

R71 已有身份桥人工声明/复核；它不等于事件原始成绩真值。R76 已有 pure checker/corpus/CLI，但明确没有持久产品审核入口。其 `human_truth_status=pending_external_review`、`release_gate=inconclusive` 和真实覆盖统计保持原义，不由本功能本机签名修改。

## 稳定接口与数据合同

命名统一为 `TestEventGolden*`，路由前缀 `/v1/test-event-golden`。只读 GET 和 evaluate 必须 `mode=history`；写入均须登录并传 UUID `Idempotency-Key`、`operator`、`reason`、`expected_revision`、`expected_fingerprint`。初始 Fence 为 0/null，后续精确绑定当前修订。按稳定 user.id 隔离写入幂等，保留 actor_session_id 作为当时上下文；重放先返回原结果，同 UUID 不同正文409。

### 输入类型

```ts
interface TestEventGoldenEventRef {
  event_id: string;
  event_revision_id: string;
  event_fingerprint: string;
}
interface TestEventGoldenLinkRef {
  participant_key: string;
  link_id: string;
  link_revision_id: string;
  link_fingerprint: string;
}
interface TestEventGoldenIdentityExpectation {
  participant_key: string;
  truth: "linked" | "not_linked" | "unknown";
  sku_label: string | null;
  expected_variant_id: string | null;
}
interface TestEventGoldenExpected {
  event: TestEventPayload;
  identity_assertions: TestEventGoldenIdentityExpectation[];
  distinct_pairs: { left_sku_label: string; right_sku_label: string }[];
}
interface TestEventGoldenMaterial extends BridgeMaterial {
  rights: BridgeRights & { quote_test_results: true };
}
interface TestEventGoldenContent extends GoldenSigned, GoldenRevisionBinding {
  title: string;
  event_ref: TestEventGoldenEventRef;
  materials: TestEventGoldenMaterial[]; // 1..3，document_id 不重复
  link_refs: TestEventGoldenLinkRef[]; // 0..60，每 participant 至多一个
  expected: TestEventGoldenExpected;
  evidence_note: string;
}
interface TestEventGoldenReviewRequest extends GoldenSigned, GoldenRevisionBinding {
  case_revision: number;
  case_fingerprint: string;
  action: "approve" | "reject" | "revoke";
  acknowledged: true;
  opened_materials: { document_id: string; raw_hash: string; metadata_hash: string }[];
}
interface TestEventGoldenCaseRef {
  case_id: string;
  case_revision: number;
  case_fingerprint: string;
  review_revision: number;
  review_fingerprint: string;
}
interface TestEventGoldenSetWrite extends GoldenSigned, GoldenRevisionBinding {
  title: string;
  action: "freeze" | "revoke";
  case_refs: TestEventGoldenCaseRef[]; // freeze 1..3；revoke 空数组
  acknowledged: true;
}
interface TestEventGoldenEvaluateRequest {
  expected_set_revision: number;
  expected_set_fingerprint: string;
  target: "frozen_revision" | "current_head";
}
```

Python expected 使用独立 strict/closed literal 校验，所有 EventPayload 字段显式存在；可复用 R76 `EventLiteral` 的形状与类型精确语义，不用产品 EventPayload 正规化生成预期。raw_value 必须保持字符串、小数尾零及负零；source_rank、单位、protocol、conditions、缺失/null/false/0 分开处理。全文 expected 上限500000 UTF-8 B，身份断言必须覆盖所选 participant、不重复；unknown 的 sku_label/expected_variant_id 必须null，不能计作已知负例。linked/not_linked 必须提供冻结 link_ref、非空逻辑 sku_label 和明确 expected_variant_id，服务端复核其事件/participant 归属。distinct pair 两标签必须存在且不同，不重复、不反向重复；一方未知或未完成检查不报零错合并通过。

材料复用 R71 EvidenceDocument、原件长度/SHA、metadata_hash、event/participant locator 和有界 quote。新增 quote_test_results 是独立的本机权利声明，不能从 quote_identifiers 推导；不认证其真实性、不改变原件来源许可。保存、approve、freeze、evaluate 均重核实际对象及冻结 metadata，不接受哈希相同但原件缺失，不读工作区任意路径。不得把 R74 身份未知论文补成猜测尺寸/SKU 正例。

### 路由与输出

| 路由 | 输入/结果 |
| --- | --- |
| GET `/cases?mode=history&event_id=&offset=0&limit=10` | 可选event_id，分页summary；不返回大正文 |
| GET `/cases/{id}?mode=history&revision=` | 当前/指定历史内容、精确冻结输入、独立expected、当前review与追加历史 |
| POST `/cases` | Content，201 CaseDetail |
| POST `/cases/{id}/revisions` | Content，201 CaseDetail；原case绑定event_id不可换 |
| POST `/cases/{id}/reviews` | ReviewRequest，admin；201 CaseDetail＋recorded_review |
| GET `/sets?mode=history&offset=0&limit=10` | 最新集分页 |
| GET `/sets/{id}?mode=history&revision=` | 当前/历史冻结集与当前blockers |
| POST `/sets` | SetWrite，仅freeze，admin；201 SetDetail |
| POST `/sets/{id}/revisions` | SetWrite，admin；201 SetDetail |
| POST `/sets/{id}/evaluate?mode=history` | EvaluateRequest；只读200 Evaluation，不写结果、事实、事件、bridge或审核 |

CaseSummary 稳定键：`id,event_id,revision_id,revision,fingerprint,title,review_status,review_revision,review_fingerprint,blockers,created_at`。review_status 为 `pending/approved/rejected/revoked`，陈旧性单独由blockers表达。CaseDetail增加 `event_ref,event_snapshot,materials,link_refs,expected,evidence_note,operator,reason,actor_user_id,latest_review,history,reviews,history_truncated,reviews_truncated,is_current,boundary`；history/reviews各最多100。

SetDetail稳定键：`id,revision,fingerprint,title,action,state,case_refs,cases,eligible,blockers,operator,reason,created_at,history,history_truncated,boundary`；state 为 `frozen/revoked`。case_refs固定内容与审核双指纹，原引用按原值保留；任何内容/审核/事件/桥修订、撤销或ABA变化都不能让旧集恢复当前可用。

Evaluation稳定键：`schema:"test-event-golden-evaluation@1",set_id,set_revision,set_fingerprint,target,state,case_results,observed_wrong_merge_count,checked_distinct_pair_count,wrong_merge_count,human_truth_status,boundary`。state 为 `passed/failed/inconclusive`；human_truth_status永远pending_external_review，wrong_merge_count永远null；可报告范围受限的observed_wrong_merge_count。case_results各含 `case_id,event_id,expected_event_revision_id,actual_event_revision_id,review_status,eligible,blockers,state,differences,comparison,identity_results,distinct_results,differences_truncated`。difference为 `{path,expected,actual,code}`，最多100项，使用closed有界JSON；不要返回无关用户、凭据、任意数据库行。

boundary统一：`scope=local_workspace,data_state=local_snapshot,accepted_as_facts=false,review_identity=self_reported_local_operator,human_truth_status=pending_external_review,provider_use=false,export=false`。approved只代表本机内容审核记录。审核者须admin且稳定user.id不同于内容作者，换session不能自审；这仍不认证两个真人。

## 实际消费者和复用点

1. UI从测试事件详情打开“测试真值与复核”，展示当前修订、1–3份供审PDF、完整SHA/metadata、独立预期编辑器；复制当前事件只能生成待审草稿，不自动审核。
2. 审核界面展示已保存精确内容；通过既有下载方法真实取得原件并校验SHA后，另行勾选人工核对，approve提交opened_materials。服务端重核原件和内容Fence。
3. 冻结1–3个已审核case。集合只是独立案例的组合；不得将不同事件测量拼成总榜。
4. “核对冻结版本 / 核对当前版本”实际调用evaluate。服务端读取TestEventRevision并复核payload/fingerprint，调用与现有 `/test-events/{id}/compare` 相同的只读比较逻辑；保留原值/原单位/来源名次，不重算子集名次。
5. 对所选R71 link使用 `checked_revision/link_view/current_link_binding/assess_link` 等现有读路径获取真实选择、完整identity与当前eligibility；不调用create/review决策，不由客户端传actual。已知distinct标签落到同一variant_id或有效identity_key时报告observed_wrong_merge，unknown不算已验证负例。
6. target=current_head发生更新时，返回新旧逐字段差异及event_changed/bridge_changed等blockers，eligible=false；不偷偷改冻结输入。target=frozen_revision仍能重开历史，但同时呈现当前失效状态。缺失、篡改原件或冻结记录时明确拒绝，不回退到当前数据。

Root补充裁决：历史GET保留已保存内容并以200及明确完整性blocker展示原件不可用；这不代表证据有效。approve、freeze和evaluate重核失败时返回4xx，绝不回退原件。evaluate只接受当前集合修订及指纹的Fence；target=frozen_revision指该集合绑定的事件/桥历史，旧集合修订仍可经GET读取。

R76 `evaluate_corpus` 的actual合同包含创建/审核HTTP观察，并有专用于冻结语料的假设，不能用测试helper生成伪HTTP输入接入生产。只复用独立strict literal、类型精确差异与distinct-pair语义；必要时增加一个窄public pure比较函数，旧R76输入/输出、人工资格常量和归档manifest不变。不新增CLI、定时器或通用插件层。

## Task 1：后端持久模型、规则与消费者（review owner）

**Files:**
- Create: `apps/api/tire_api/test_event_golden_models.py`
- Create: `apps/api/tire_api/test_event_golden.py`
- Create: `apps/api/tire_api/test_event_golden_checks.py`
- Modify: `apps/api/tire_api/db.py`（模型注册）、`main.py`（路由注册）、`migrations.py`（新追加式迁移）
- Modify only if needed: `test_events.py`（抽出比较的只读函数，原端点行为不变）、`professional_golden_checks.py`（窄pure复用，不改R76合同）

1. 四表固定为 `test_event_golden_cases/test_event_golden_case_revisions/test_event_golden_case_reviews/test_event_golden_set_revisions`：case头固定event_id；content固定event_revision_id、payload/fingerprint、1–3材料与link refs、独立expected；review绑定content修订/指纹；set仅保存精确case/review refs及冻结内容。修订和审核分别递增，带前指纹、actor_user/session、幂等key/request_hash。新版本固定 `027_test_event_golden`，`upgrade(..., include_test_event_golden=False)`仅供显式历史构造，默认True；`include_vehicle_binary=False`不执行027。
2. 新迁移只创建四表和追加保护，不改旧Golden表、不重建RawCapture。所有新表有ORM及SQLite update/delete/replace保护；PG按现有模式提供DDL，未实跑不能称PG已验。
3. 写入在现有ingestion锁内校验Fence/幂等/完整性，先核全部依赖再一次提交。授权失败、引用冲突、原件损坏不能留半个case或审核。
4. GET与evaluate读取不走事件GET的审计提交路径；业务消费者不写库，事件、原成绩、事实、bridge、来源策略不被修改。
5. 实现上述类型/路由与有界字段差异，新增模块完成后交独立审查，再冻结运行源。

## Task 2：共享类型、SDK和完整入口（impl owner）

**Files:**
- Create: `packages/domain-types/src/test-event-golden.ts`
- Modify: `packages/domain-types/src/index.ts`（仅导出）、`packages/api-client/src/index.ts`（SDK方法）
- Create: `apps/web/components/test-event-golden.tsx`、必要局部样式
- Modify: `apps/web/components/test-events.tsx`（入口）
- Test owner: `packages/api-client/tests/test-event-golden.mts`及最小沿用的测试tsconfig

1. 按上述合同实现类型；方法名统一 `testEventGoldenCases/Case/createCase/reviseCase/reviewCase/Sets/Set/createSet/reviseSet/evaluateSet`，均以 `testEventGolden` 前缀组成完整名称，例如 `testEventGoldenCreateCase`。
2. 材料目录复用既有testSkuMaterials与文档下载SDK；新增quote_test_results声明、原件校验与单独人工确认。不要把readFile/打开按钮视为人工审核。
3. 提交开始冻结payload+UUID；丢响应保留同一请求可重放，不生成新UUID制造重复记录。选择事件/内容或账户变化取消旧请求，迟到结果不得覆盖新选择。
4. 完整提供草稿、修订、审核、冻结/撤回、历史、evaluate两种target及逐字段差异展示。陈旧/撤销/unknown与本机自报边界可见，不把inconclusive画成通过。
5. 桌面及窄屏实际HTTP/UI验收覆盖入口到差异消费者；前端构建与SDK测试不代替实际UI结果。

## Task 3：独立测试与迁移审查（verify owner）

**Files:**
- Create: `apps/api/tests/test_test_event_golden.py`
- Create: `apps/api/tests/test_test_event_golden_migration.py`
- Modify: 测试version_registry、历史025/026/024迁移断言和现canonical regression runner manifest；不修改产品源码
- Regress: `test_test_events.py`、`test_golden.py`、`test_golden_release_gate.py`、`test_test_sku_links.py`、R76 pure checks的相关具名用例

先写能证明产品缺口/反例的测试，不从生产比较器生成expected。覆盖：独立raw_value/负零/尾零/原名次/单位/条件精确差异；跨事件成员拒绝；unknown不算负例；已知不同SKU同variant/identity明确错合并；缺原件/同长篡改/metadata漂移；1–3材料和集合全成员绑定；同账户跨session自审拒绝；无admin审核/冻结拒绝；同UUID重放/不同正文冲突；事件/桥/内容/review ABA与撤销失效；历史可读；evaluate不改业务行；旧tire/vehicle合同不变。

迁移在全新私库及带既有Golden/TestEvent数据的私副本验证：旧表schema与原列行保持、新四表和保护齐备、重复initialize幂等、事务失败无半成品。不得直接打开R118保留证据库，避免readOnly也生成sidecar；需样本时先由Root复制到新私槽。

后端复用既有受审入口 `apps/api/.venv/Scripts/python.exe scripts/run_api_worker_regression.py --phase run --output-root <Root审定的fresh私槽> --targets <已登记的具名目标>`；该入口固定Python3.12.10，不能冒称R118的3.14/TCP验收。Root唯一执行fresh output；verify登记新测试/调整确属历史版本断言。命令由Root审定实际目标后执行，内部仍走已有护栏；**不直接执行普通pytest、常规应用入口或正常数据库初始化命令，不新增PS freeze/launcher外壳。** SDK、类型、构建及真实UI也由Root沿既有受审入口执行，不新增通用执行框架或测试矩阵。

## 完成与回退

完成必须同时具备：真实产品入口持久保存/审核/冻结；消费者实际读取当前/历史事件和桥并显示独立预期差异；定向反例、迁移保全、SDK/类型和真实UI闭环通过；资源自然关闭与源稳定；真人覆盖/Provider/正常库/设备边界如实保留。工程完成不等于原规格所有Golden数据及V1发布Gate完成。

回退只涉及本轮明确新增模块/路由/类型/UI和追加迁移；保留已产生的历史账本及失败证据，不删除未知数据或改写旧表。无commit/push；各owner不是独占工作树，不回退其他人的修改，跨owner文件变更先协调。
