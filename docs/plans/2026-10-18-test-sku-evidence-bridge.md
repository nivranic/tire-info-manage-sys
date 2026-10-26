# TestEvent 与精确 SKU 人工证据桥 Implementation Plan（R71）

**Goal:** 交付从已有 PDF 原件、精确双侧证据预览到双账户审核、追加修订及历史失效解释的证据桥，作为原规格推荐的前置能力。

**Architecture:** 独立 `TestSkuLink` / `TestSkuLinkRevision`，不修改 Participant、厂商事实或 R65/R70 合同。历史重建和当前适用性分离；服务器重建全部证据，预览指纹与乐观版本锁定写入。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite 私有验证、React 三端共享组件、TypeScript domain-types / API client。

状态：**实施合同已冻结，工程工作流已实现并限定验证；真实来源支持/代表性Golden未验收，A不能完整关闭。**终态见末节及[第71轮报告](../assurance/evidence/round-71-test-sku-evidence-bridge.md)。沿用用户持续实施授权；在当前有未提交实现的工作区协作，不自动提交、创建干净分支替代现有树或触碰正常数据库。使用 brainstorming / writing-plans 技能收敛设计；本会话直接执行，不重新询问是否实施。

## 1. 原需求与起点

- [原规格](../requirements/2026-09-26-tire-intelligence-original.md)：精确版本身份、TestEvent 独立记录、证据原文、个人权重仅解释和有引用推荐。
- [R70](../assurance/evidence/round-70-test-ai-grounding.md)：含仓库测试的 AI 包仅事实摘录；该边界继续保持。
- [设计草案](2026-10-18-test-sku-evidence-bridge-design.md)：本合同落实 A 的工程工作流，B 条件化解释、C AI 推荐仍是后续需求。
- 基线：`.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/baseline.json`，修改前现场核对 R70 清单 880 源、18 文档、179 证据全部一致；HEAD `4d0ef60fa2240146113a3fac172759c665cf339f`。

## 2. 材料方案与证据含义

选择**既有上传 PDF 原件＋明确逐字段声明＋不同管理员账户复核**。其他可选方案：新增专业来源受许可下载通路，能进一步证明传输来源但目前没有专业测试站来源/许可配置；仅保存人工关联实现较小，却不能支撑后续精确身份核对。前者是后续工作，后者仅为本合同的线索等级。

材料采用既有 `/v1/documents`（PDF、8MiB、内容寻址对象），不新增全文镜像或 PDF 解析器。上传者须确认有权在本地共享工作区保存和重开；`rights_basis` 是声明，不是系统授予许可。`%PDF-` 只证明文件标记，不保证可打开、页码或出版者真伪。审核者必须人工打开并对照完整材料；页、区域、短引文是人工定位，系统不声称做过 PDF 语义抽取或真伪鉴定。

固定来源轴：`material_origin=operator_supplied`、`origin_verification=unverified`、`read_scope=local_workspace`。测试事件仍为 `manual_transcription/unverified`。机构名称、HTTPS 引用、哈希、上传成功或管理员操作都不能改变该轴。

证据等级：

- `manual_assertion`：人工关联线索，不能移植成绩为精确 SKU 性能。
- `source_explicit_identifiers_in_supplied_material`：声明所提供的材料中明确载有逐项标识，经另一管理员账户对照；**不是裸的来源确证、在线核验或独立测试认证**。

审核状态与等级分轴。最高适用性仅 `conditional_reviewed_transcription`；条件包含当前有效、无冲突、全身份字段有直接材料声明、现行精确身份完整、双账户复核。否则为 `none`；人工线索即使已审核仍不能用于 SKU 性能移植。双账户不证明两个真人独立，不展示“独立认证”。

## 3. 冻结请求

所有 JSON 对象禁止额外字段、拒绝 bool 代整数。不得接收客户端 actor/user、事件正文、厂商 facts、身份完整状态、来源核验状态或 eligibility 覆盖。

`BridgeSelection`：`event_id`、`event_revision_id`、`participant_key`、`variant_id`、`tire_snapshot_id`、`fact_version_id`。事件 revision/state/fingerprint、完整 participant/hash 由服务器重建。固定 link 范围是 `(event_id, participant_key)`，同范围一个 link；修订可重新声明另一 SKU，不覆盖旧证据。

`BridgeMaterial`（0–3）：`document_id`、`expected_raw_hash`、`expected_metadata_hash`、`event_locator`、`participant_locator`、`rights`。两个 locator 均为 `{page,region,quote}`，场次和对象关联也保留材料出处。`rights` 为 `{rights_holder,basis,store_original:true,workspace_reopen:true,quote_identifiers:true}`，都是操作者有界文本/严格布尔声明；本轮 `provider_use/export` 固定不允许，未新增许可。明确标识等级至少一个，人工线索可无材料。材料 metadata hash 为 `digest({**document_metadata(row,size),actor_session_id:row.actor_session_id})`，覆盖原件 id/raw_hash/byte_count/content_type/source_url/title/rights_basis/operator/actor_session_id/created_at。预览和当前/历史读取验证对象映射、大小及 SHA；不能从损坏的对象退回 DB 副本。

`BridgeAssertion`（0–20）：`field`（服务器允许的 variant-identity@2 字段）、`material_document_id`、`material_value`（严格 string 或 bool）、`quote`（1–300字）、`page`（1–100000严格整数）、`region`（1–200字）。字段不重复；原值与当前 SKU 精确身份逐项比较，false 不等于未知，缺失字段不从目录补全；代码及命名空间、市场、尺寸等均不能按名字推断。允许附证据，但不能由客户端填写结论。完整字段集以当前规范身份实际键集合为准，数组类型字段需保守排除并解释，不能默默扁平化。

`BridgePreviewRequest`：`mode:'history'`、`action:create|revise|review|revoke|restore`、`link_id:null|string`、`selection`、`materials`、`assertions`、`evidence_level`。

`BridgeDecision` 在预览请求上增加：`expected_revision`（新建0）、`expected_fingerprint`、`declaration_revision_id`（创建null，其余引用当前声明修订id）、`operator`、`reason`、`acknowledged:true`、`opened_materials:[{document_id,raw_hash,metadata_hash}]`、`confirmed_event_revision_id`、`confirmed_participant_hash`。review 的 opened_materials 必须精确覆盖全部所选材料，确认值必须来自服务器预览。署名不能代替账户身份；短引文和 locator 不自动成为可验证的语义证据。服务器给每个 quote 保存原始 UTF-8 SHA-256，不将 JSON digest 冒称原文 hash。

写入携带 `Idempotency-Key` UUID。按稳定 `actor_user_id+key` 唯一；同 key 同请求返回原操作及精确版本，不同请求409。重放不能绕过当前账户/管理员资格，不能重定向另一个对象或隐式新审。

## 4. 路由与响应

所有写/预览沿用管理员守卫；读为本地共享工作区，必须 `mode=history`，`Cache-Control:no-store`。不能声称生产账户/租户隔离。

- `GET /v1/test-sku-links/materials?mode=history&offset=0`：已有 PDF 元数据、原文 hash、metadata hash、分页；只读，无自动下载。选中材料的原件完整性由预览强制核对。
- `POST /v1/test-sku-links/preview`：无审计/commit 副作用的双侧重建与提交门禁。
- `POST /v1/test-sku-links/decisions`：版本、指纹、权限和原件确认均通过后追加。
- `GET /v1/test-sku-links?mode=history&event_id=...`：分页 link 当前摘要。
- `GET /v1/test-sku-links/{link_id}?mode=history&revision=...`：精确历史，损坏明确拒绝，不能降级读取当前版本。

响应 schema `test-sku-link@1`，主体含 `id/revision/revision_id/review_state/effective_state/eligibility/boundary/selection/frozen_evidence/material_evidence/assertions/checks/unknown_fields/blockers/stale_reasons/binding_hash/fingerprint`。预览另含 `can_submit`、当前版本与 `confirmed_participant_hash` 所需服务器值。history 明确每次 action、账户、署名、原因、时间、版本；当前适用性与该历史当时的原记录分别展示。

`frozen_evidence` 分 test/tire：测试完整payload、revision_id/revision/state/fingerprint、participant/hash、条件/尺寸/机构关系/rights；SKU 原快照出处/原文SHA/完整原成员、精确 identity/schema、真实FactVersion内容/指纹/structured locator。材料元数据和短引文另存，不混入厂商 facts。完整 revision fingerprint 覆盖 selection、双方原证据、材料、assertions、review actor/原声明 actor、before/after、binding、request hash；不能只对 binding 哈希。

## 5. 状态、历史与当前门禁

- create/revise/restore → pending_review；review → reviewed；revoke → revoked。revoked 不能直接review；restore 不恢复旧审核。review 不能同时更改声明，必须先 revise。
- review 的账户 id 必须不同于当前声明的账户 id。不同 session、operator 文本或重新登录同一账户均不满足。声明者稳定保存，不能通过审核或撤销操作变成审核者自身来混淆原声明。
- 响应提供稳定 `declared_by_user_id/declaration_revision_id` 和 `allowed_actions`；review/revoke/restore保留原声明归属，只有create/revise产生新声明。
- 当前重新审核可以选择仍有效的原材料；变更事件修订/SKU或材料必须先追加声明。读取历史无写，无偷偷自动复审。
- 事件 revision_id/revision/state 均绑定；即使 payload 恢复同指纹仍失效。participant 需核完整原对象；同 key 换对象不能复用。
- SKU当前身份合同、身份决定 revision、生命周期 revision、所有关联来源目录 membership transition 绑定。身份redirect→clear、撤销→恢复、目录移除→重入的 ABA 失效，不能只对终态相等。
- 原始证据重建必须以历史快照自身 schema/原成员/真实 FactVersion 为准；不能把当前 contract_metadata 写回历史冻结体。当前 contract 单独比较。
- 元数据刷新不使原证据失效。非身份性能事实变化可单独警示，不伪称精确身份改变；具体门禁由身份/状态/来源目录是否仍成立决定。
- 检测材料/原文/成员/事实/存储修订篡改时 fail closed；不返回篡改后的证明，也不调用带 audit/commit 的 GET 作为 helper。

## 6. 任务、所有权和验证

### Task 1：后端证据桥（review_corpus_ultra）

新建 `apps/api/tire_api/test_sku_link_models.py`、`test_sku_links.py`、`apps/api/tests/test_test_sku_links.py`；修改 `db.py`、`migrations.py`、`main.py` 的必要注册。019仅新增表/约束，不回填旧事件；追加记录保护必须有针对性验证。具名函数包括 reconstruct_event_participant / reconstruct_tire_evidence / freeze_materials / validate_assertions / current_link_binding / assess_link / preview_link / append_link_revision / reconstruct_link_revision。

先构造旧实现没有的工作流和失败测试，再实现。新建/同范围重复创建、修订/双账户审核/撤销恢复、精确历史、材料损坏、身份/目录ABA、幂等/并发和权限逐项验证。私有 runner 在应用 import 前清空宿主配置、禁止真实外联/正常库/子进程，GUID短路径SQLite和对象根。

### Task 2：共享合同与三端 UI（review_handoff_ultra）

新建 `packages/domain-types/src/test-sku-links.ts`、`apps/web/components/test-sku-links.tsx`；更新 domain exports、`packages/api-client/src/index.ts`、`apps/web/components/test-events.tsx`。可新增专用 CSS。SDK增加上述路由消费和 UUID 头。增加 SDK 公开类型/路径契约消费验证，不能只重复实现断言。

参测对象旁进入独立证据桥面板：选择精确 snapshot/fact（不能仅输入型号或尺寸）、已有原件/上传、逐字段材料声明、完整预览、署名理由、创建待审、另一管理员读取原件并审核、修订/撤销/恢复/精确历史。原文 Blob 安全下载和 URL回收；材料标共享未核验，人工原文位置不能伪称自动定位。未知、冲突、当前失效原因始终呈现，R70事实摘录入口保持。

按 auth.ownerEpoch/user.id 和 event_revision_id 隔离草稿/中止请求/拒迟到响应；请求pending禁双击，ambiguous write重试固定UUID；payload改动须新预览与新UUID。组件禁止 next/*，读 apps/web/AGENTS.md 与根 node_modules/next/dist/docs 的use-client指南后实施。

### Task 3：独立对抗验证（review_wire_ultra）

仅负责 `apps/api/tests/test_test_sku_bridge_review.py` 与本轮 `.artifacts/.../review/`。不改产品。独立验证自审同账户异session、客户伪造来源等级、无材料标识、未知/false/不匹配字段、原件/元数据/双侧成员篡改、事件/身份/生命周期/目录ABA、过期预览/重放/原历史读取及R70不扩权。发现报告Root，不能自行放松产品门禁来通过。

### Task 4：集成与交付（Root）

审查实现与冻结合同差异，执行最小必要相关回归、workspace typecheck、三端前端构建。私有HTTP和真实浏览器验证声明→换账户→核对原件→审核→旧修订重开→事件变化失效，桌面和390/320窄屏；实际能验证的结果与合成材料/真实样本分开。

计划命令（由各owner写GUID护栏runner后执行）：

```text
apps/api/.venv/Scripts/python.exe -X utf8 -B <R71-private-runner.py> apps/api/tests/test_test_sku_links.py ...
apps/api/.venv/Scripts/python.exe -X utf8 -B <R71-independent-runner.py> apps/api/tests/test_test_sku_bridge_review.py
npm run typecheck
npm run build
npm run desktop:frontend
npm run mobile:frontend
```

前端命令先检查实际 package scripts；实测命令/exit/源码绑定写新回执。构建生成文件按基线字节恢复，关闭本轮私有API/Next和测试页面，保留取证。禁止无理由扩大重跑旧全量。

## 7. 完成边界与后续

工程工作流通过也不关闭“有来源支持的代表性人工Golden”。当前仓库没有测试对象↔精确SKU的真实完整材料，不能以合成PDF/厂商参数fixture代替该验收。后续需来源许可与固定地址allowlist的真实来源字节捕获（现有 text capture 不冒充HTTP原始字节），以及代表性专业样本人工核对。

本轮不允许给R70包附桥就放开模型推断；后续B/C必须另冻推荐作用域/双侧身份/同场条件/偏好解释和模型合同。完整V1、其他来源、原生设备、真实Provider、正常库保全/迁移与发布Gate继续保持原目标，不从本切片删除。

回退：本轮只追加新模块/路由/表；代码回退需按本轮差异人工处理，不 reset/clean 整树；已有事件/厂商事实/原件不改写，新记录作为历史保留，不直接删表或清库。

## 8. 实施与限定验收终态

冻结请求/响应和所有权均已落实；另补充participant合法移除的当前binding缺失语义（历史仍严格重建），以及旧pre016测试发现的新表after_create触发器幂等安装，不改旧测试或预期。原件确认仍是人工声明，不存在系统阅读/来源真伪认证。全部原有R70/设备AI合同保留。

最终相关后端110通过、1具名未选另有fresh非Web初始化探针；独立119初验/兼容修补后13相关复验分阶段通过；SDK12、公开类型/专用UI类型与workspace typecheck、三端前端生产构建通过。真实私有API34、1441×934桌面React34、390×844和320×740布局/读取各11条断言通过。291相关前端源稳定、7构建生成文件恢复，最终API15源前后稳定且护栏0；运行3配置恢复，所有本轮服务/测试页已关闭。详细证据和失败历程见第71轮报告，不能累加为全量或用合成PDF替代专业Golden。

本合同的A工程部分通过不等于A全部关闭；真实许可来源捕获/代表性人工Golden、B条件化解释、C专用AI推荐及完整V1继续待办。正常库019保全/迁移与PG/原生设备仍未验收。当前清单入口为`.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/verification-final.json`，以实际生成及独立核对为准。
