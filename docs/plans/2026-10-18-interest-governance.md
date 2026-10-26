# 第67轮：治理与目录变化的兴趣事件实施计划

> 使用 writing-plans / executing-plans 按任务实施，延续用户已授权的原始需求；不自动提交、推送、迁移正常库或调用外部服务。

**Goal:** 补齐手工参数纠错、SKU 生命周期、身份决定与来源目录成员变化的相关通知，并可按原记录精确重开证据。

**Architecture:** 延用第66轮不可变兴趣事件和私有通知，在原业务事务内发布四类新域事件；目录变化新增追加成员账本。匹配只用当时已绑定的原始快照和治理记录，多个来源分别评估完整条件，不借当前身份或跨来源拼接。保留精确 SKU、人工决定与来源目录缺席之间的区别。

**Tech Stack:** FastAPI / SQLAlchemy / SQLite + PostgreSQL 通用 DDL；共享 TypeScript / SDK / React 三端面板。

## 1. 需求依据与当前证据

原始规格第213、227–237行要求关注中心只推送真正相关变化，第66轮已实现七类条件和四域事件。本轮继续交接卡 P1 下一功能队列，不把局部兴趣切片视为完整推荐、信息流或完整 V1。

实施前已在新 `.artifacts/r67-interest-governance-1792303216270-bd0c521d/r66-before-r67.json` 核对第66轮 final-v2：848源码、9文档、92证据 SHA/长度均一致。其回执与旧生成器保留原字节，后续文件变化属于本轮新快照。

可选方案：仅钩入旧共享提醒无法冻结私有条件；从当前管理界面头部重建旧通知会误用最新身份/状态；采用原事务事件发布与精确历史 reader，并为缺少原始成员账本的目录变化补追加记录。

## 2. 必须维持的语义

- 新域为 `tire_curation`、`tire_lifecycle`、`tire_identity`、`tire_catalog`；域名和原始 evidence kind 由后端与共享类型共同冻结，不混入旧轮胎事实事件。
- 纠错来源于真实 `ManualFactRevision`，包含 manual_override / revoke / clear_override。按该 source/base_fact_id 及不超过该修订的各字段记录恢复当时 effective facts，来源原值与人工有效值分开。核对 before/after/source_before，保留 null、零、缺席与恢复来源值。支持合法304 actual fact/member版本分离。
- 生命周期只采用该治理记录实际引用的、包含精确 variant 的已采纳 snapshot 成员；按来源形成独立 contexts。前后使用同一证据上下文，仅生命周期状态改变，不能制造事实变化。revoke / restore 不是官方召回或来源停售。
- 身份决定仅 correct / merge / clear，均是本地追加映射；不移动历史事实、不重定向关注，不虚构 split。引用 binding 中原 source/target 事实与快照，核对 binding_hash；匹配主体保持原 source，target 只作决定依据。不能历史重跑使用当前 endpoint 的 summary/review。
- 目录新增/移出/再次加入由同一 source/query 的相邻已采纳结果确认，不把缺席当 SKU 撤销。成员账本保存两个 snapshot、Verification、精确 variant、动作/状态和修订，origin为当次Verification+variant；304不产生虚假目录变化，重入不能因事实相同丢失，A→B→A后的重复快照对也不能丢新动作。目录 changed_paths 仅表示成员状态变化，不把用于证明移出前身份的材料缺席误记为参数变化。
- 多源证据不能拼接 AND；完整条件必须在一个上下文的一侧成立。明确缺少可复核历史身份的合法旧治理记录，允许保存为 indeterminate 历史事件且不通知；新兴趣适配不得反向阻止原先合法管理操作。
- 治理撤销的 before 关系链使用明确的前态状态/修订，不把刚flush的撤销误套到before，不用减一微秒避开并列时间。restore / clear 后旧适配关系仍须重新review，不能因状态恢复就自动授权旧链；核对关系原binding里的生命周期/身份修订，同时保留非适配事实UTQG变化的已审exact identity例外。
- 新产生记录、事件、通知在同事务；发布失败回滚原写入。不额外 commit、模型、抓取、调度或外部投递。幂等与 future-only 规则沿用第66轮，创建/修改兴趣不补发历史。
- 新 evidence kind 为 `tire_curation_revision`、`tire_lifecycle_event`、`tire_identity_revision`、`tire_catalog_revision`，fingerprint为公共原行 payload 的 digest，排除内部会话ID与动态valid_to。精确 `GET /v1/interest-evidence/{kind}/{record_id}?mode=history` 返回 `schema:interest-original-evidence@1`、scope/data_state/kind/record_id/entity_id/revision/fingerprint/record/evidence，重新读原行而不是返回通知副本；校验 kind/id/entity/revision/fingerprint，缺失或不符不得改读最新记录。新增变化筛选字段为 `curation`、`identity_resolution`、`catalog_membership`，七种关注条件不变。
- 来源刷新使旧人工 overlay 失去适用性不是新 ManualFactRevision；不伪造治理动作。本轮能力表明确该衍生变化尚未单独通知，原已采纳事实事件仍保留。来源拒绝/隔离、仅验证元数据与其他尚未实施项仍列明，不能从总需求删除。
- 现有 session_scope / 同浏览器会话跨账户数据带入政策保持原有范围，本轮不宣称严格永久账户隔离。

## 3. 任务和文件所有权

### Task 1：后端四域与历史读取（review_corpus_ultra）

Create: `apps/api/tire_api/interest_governance.py`，必要的目录账本模型模块，`apps/api/tests/test_interest_governance.py`。

Modify: `interest_events.py`、`interest_matching.py`、`interests.py`；`curation.py`、`lifecycle.py`、`identity_resolution.py`、`service.py` 原事务 hooks；目录模型注册、追加017迁移和 `tests/version_registry.py`。

1. 与前端 owner 同步四域、四 evidence kind、精确 reader HTTP/DTO 和筛选字段。
2. 添加并运行针对关键失败模式的测试，再实现冻结适配器、来源独立 contexts 和目录追加账本。
3. 注册历史 preview 与精确原始 reader：建议 `GET /v1/interest-evidence/{kind}/{record_id}?mode=history`；公共 payload / 指纹字段写清，不暴露操作者 cookie/session_id。
4. 同原事务发布，验证失败回滚、重复提交/304无重复、旧记录不补发、目录移回及状态动作的独立修订。
5. 在隔离 SQLite 验证017迁移、重复升级与旧数据保留；PG DDL只证明静态兼容，不冒充实际运行。

### Task 2：三端共享合同与原始 reader（review_wire_ultra）

Modify: `packages/domain-types/src/interests.ts`、SDK 根入口和 `packages/api-client/tests/interests.mts`、`apps/web/components/interest-center.tsx`；必要时现有合同测试配置。

1. 扩展域名、evidence kind、字段筛选与精确 evidence DTO，不改变旧域合同含义。
2. 增加显式 reader 分支，按原记录与冻结引用核对，不把新 kind 落入 snapshot 默认分支。
3. 展示中文领域/动作/限制，明确本地撤销、身份映射和目录移出差别。
4. 保持 Auth ready、ownerEpoch、AbortSignal和完成时主体核对；reader错误不显示最新替代数据。
5. SDK兴趣合同、workspace typecheck、三端前端生产构建；生成配置恢复原字节。浏览器视口不是原生运行证据。

### Task 3：独立业务与事务审查（review_handoff_ultra）

Create: 专属 `.artifacts/review-r67-*` 和有必要的 `apps/api/tests/test_interest_governance_review.py`；不与实现 owner 同改产品文件。

1. 独立覆盖来源上下文隔离、身份映射不重定向、状态动作不伪造事实、手工原值/有效值区别。
2. 检查目录304/移出/移回、事务回滚、未来生效和旧原始记录精确读取。
3. 发现问题先报告具体复现，由实现 owner 修复；测试范围与阶段失败分开记录。

### Task 4：真实隔离集成、文档与新清单（Root）

Create/Modify: 新的私有 fixture/QA 脚本、本轮 evidence 报告及独立 `.artifacts/r67-*` 回执。必要时扩展现有合成兴趣 fixture，不覆盖旧回执或私有数据。

1. 使用合成来源/私有 SQLite/对象根/Parser bundle，禁止外联、Provider和正常库；不运行默认API启动。
2. 通过真实治理写入和 QueryService 产生四域事件；真实浏览器检查新域解释、原记录重开以及状态/目录差别，涵盖桌面和手机布局。
3. 只运行受影响范围回归；不把第66轮限定或第63轮全量结果当成本轮全量通过。
4. 更新 README/交接/总计划/风险与本轮报告，生成当前源码、dirty、文档和allowlist证据清单，再独立核验。不覆盖第66轮任何旧证据。

## 4. 验证命令与边界

所有 PowerShell 命令显式使用 `C:/Program Files (x86)/PowerShell/7/pwsh.exe`；Python 使用 `apps/api/.venv/Scripts/python.exe`。各 worker 在新的 GUID `.artifacts` 和 pytest 临时目录中运行，以现场可执行命令为准，不共享可变数据库。

- 目标 pytest：新增治理/独立审查/迁移用例及原纠错、生命周期、身份、QueryService相关回归；结果保存 JUnit/日志和源码hash。
- Node 兴趣合同、工作区 typecheck 与 Web/Desktop/Mobile 前端生产构建按现有 package scripts。
- `git -c core.whitespace=blank-at-eol,cr-at-eol diff --check`；保持未知 dirty、无staged/unmerged。
- 不放宽 Parser 8秒/并发2/CPU5秒/384MiB。正常库、真实来源/模型、完整API/Worker、真实PG、原生设备/权限/生命周期、生产迁移/签名/发布与全部 V1 Gate 没有执行就保留为未验证。

## 5. 实际执行记录

以下为本轮实际实现与已取得的限定证据，取代执行前建议；完整记录见[第67轮报告](../assurance/evidence/round-67-interest-governance.md)。总Goal保持 active，完整V1按原始规格继续推进。

### 5.1 最终实现与精确合同

1. 后端新增 `interest_governance.py`、`interest_catalog_models.py`，接入原curation/lifecycle/identity/QueryService事务，注册迁移 `017_interest_governance_catalog`。新表 `tire_catalog_revisions` 只追加，保存source/query、variant、前后snapshot/Verification、presence及原始binding；真实SQLite唯一约束与FK生效。017不补发旧事件/通知，不回填目录账本；正常库未升级。
2. 四个新域/原始kind固定为 `tire_curation/tire_curation_revision`、`tire_lifecycle/tire_lifecycle_event`、`tire_identity/tire_identity_revision`、`tire_catalog/tire_catalog_revision`。动作依次为manual_override/revoke/clear_override、revoke/restore、correct/merge/clear、added/removed。七类条件保持不变，域合计八个；`curation/identity_resolution/catalog_membership`进入changed_fields合同。
3. 人工纠错以原source/base_fact为边界重建所有字段前态和有效值，分别冻结 `facts/source_facts`，允许合法304的actual fact/member版本分离，拒绝借用旧base overlay。其他三个新域按 `source_contexts[]` 独立匹配完整AND；target不能替代原source身份。合法旧治理缺少可复核历史身份时保存indeterminate事件、不通知，不阻断原管理操作。
4. 撤销前态可以解释已匹配关系的退出；restore/clear/目录重入均不能自动恢复旧review权限。独立P1反例促成完整Verification目录transition核对，包括017之前的成功历史；before按previous_verification_id明确截断，未用时间减一微秒。目录仅声明成员和state变化，不伪造facts差异、SKU撤销或官方召回；304、同成员重验不产生目录事件。
5. 原始reader最终为 `GET /v1/interest-evidence/{kind}/{record_id}?mode=history`。kind仅接受上述四项，mode必填history；返回schema `interest-original-evidence@1`，scope `local_workspace`、data_state `local_snapshot`，以及kind/record_id/entity_id/revision/fingerprint/record/evidence。fingerprint来自公共原行digest，排除内部session/idempotency_key/request_hash及动态适用性。不存在返回404 `interest_evidence_not_found`，原行与冻结证据不符返回409 `interest_evidence_mismatch`，非法kind/mode为422；不转读最新记录。
6. 共享类型、SDK根出口及Web/Desktop/Mobile共用面板支持四个原始kind。reader核对kind/id/entity/revision/fingerprint，保留Auth ready/ownerEpoch/AbortSignal防护及失败说明。原始record读取与通知里的冻结解释分开，不能以通知副本冒充原行。
7. 四producer通知失败均随原事务回滚；事件/通知去重与future-only不回填延用第66轮。能力表继续明确derived_manual_applicability、source_quality_rejection、metadata_only_verification缺口。同浏览器session_scope政策不变，本轮不证明永久账户隔离。

### 5.2 验证阶段、缺陷与范围

- 后端预实现3失败→首批3通过；受影响原行为回归136通过/2失败。两处旧测试前提分别为总InterestEvent计数没有区分新增目录域、旧schema模拟未先处理017目录FK表；仅适配测试后10项目标通过。目录P1修复后正反链5项、最终相关回归35项分别通过，具名产品源运行前后稳定。**没有重跑整组138项，不能合成为138项最终全绿。**各阶段日志/JUnit与回执见本轮报告。
- 独立17项、19项通过发生在新增目录链反例之前。该P1反例修前1失败/19 deselected，修后1通过/19 deselected；最终封存20通过、0失败/错误/跳过，20个具名产品/测试文件SHA/长度稳定。覆盖四producer回滚、来源AND隔离、生命周期/身份并列时间、旧历史缺口、304实际base、目录重复转换/旧车型链、精确reader、017保留/幂等/回滚、真实SQLite约束与PG DDL编译。PG未实际运行，动态并列时间不是全部目录顺序穷举。
- 隔离API阶段一57断言通过/1失败：合成目录触发来源质量row_loss_threshold。阶段二3通过/1失败：新增控制行超出原query尺寸，被schema以source_unavailable/source_schema_validation_failed拒绝。保留失败后改为同查询范围4行、只移出1行，并增加seed live/4行硬断言，没有放宽schema或质量门。第三host最终95/95断言通过、done=true，包含治理写入、重新review、目录重入后的实际UTQG反例/正控，以及四类旧原始记录在后续来源刷新后保持精确；49条累计通知不是场景数。
- Chrome桌面1440×1000与手机视口390×844分别19/19断言通过、done=true且无整页横向溢出。检查四域说明、冻结条件、四精确原记录、目录before/after whole body；当前来源UTQG333而旧材料仍为300。首次桌面工装8通过/1失败为“不代表”与实际“不表示”文案断言不一致，仅修工装后通过。浏览器视口不是原生设备验收。
- SDK注入transport目标合同、workspace typecheck、三端前端production build共5阶段exit0，16项相关源/配置/合同测试hash一致；Web静态页5/5，22产物hash为Web15/Desktop3/Mobile4。7个Web生成文件核对恢复实施前字节（含原本相同文件），PWA生成17项allowlist后sw恢复，不证明PWA更新；三端前端构建不是原生验收。无前端阶段失败，既有大chunk/独立输出目录提示保留。准确命令和五份回执见本轮报告。
- 两次API工装失败、首次UI工装失败和目录P1修前回执均保留，不能由最终通过抹除。截图路径限制通过内联原字节保存处理；手机模拟重载后重新注入public references才运行最终检查。Sandbox preflight中API/Next报告ready但跨exec/Chrome本机端口超时，主动停止均exit1；按获准host模式同私有路径重启才可访问，不声称环境根因已修复，未改产品/预算，未计通过。
- 独立runner外网/子进程/正常库尝试均0，loopback16为TestClient运行时自唤醒；最终API fixture Provider/外部网络/Parser子进程均0、未用正常库。计数不覆盖整个浏览器或Next进程。正常库、真实来源/模型、完整API/Worker、真实PG、原生/物理设备、PWA更新与生产发布Gate未由本轮验收。

### 5.3 收尾与后续

最终API shutdown HTTP200且实测exit0，Next开发进程主动Ctrl+C后exit1；旧API亦exit0，四个私有端口均无监听，测试页关闭。最终合成fixture为7兴趣/7修订/45事件/49通知/24目录记录；浏览器开发阶段3个生成配置按备份SHA/长度恢复，与前端构建阶段7文件恢复分别记账。停止与配置恢复回执均见本轮报告，私有fixture存储不纳入交接allowlist。

本轮源码/dirty/文档和allowlist清单入口为 `.artifacts/r67-interest-governance-1792303216270-bd0c521d/verification-final.json`，生成和独立核验由Root另行记录；本节不代替最终主清单核验。旧第66轮清单与生成器不覆盖。清单不是完整工作区归档或私有数据备份。未提交、推送或发布；完整推荐/信息流、derived人工适用性及其他相关事件、专业样本/Golden、来源/平台矩阵与全部发布Gate继续保留，不能标全V1完成。
