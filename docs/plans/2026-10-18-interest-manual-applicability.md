# 第68轮：来源事实更新后的人工处理适用性通知实施计划

> 使用 writing-plans / executing-plans，延续用户已授权的完整需求。本计划不自动授权提交、推送、正常库迁移、真实来源或模型调用。

**Goal:** 来源采纳实际新增 FactVersion 时，对从适用变为待复核的人工覆盖或字段撤销产生可精确回查的派生记录与私有通知；保留原人工决定。

**Architecture:** 在 QueryService 原采纳事务内新增只追加适用性账本，并复用冻结兴趣事件、私有匹配和精确原行接口。每次 variant/source 实际事实版本更替聚合受影响字段，分别冻结前后 source/effective facts、实际事实与快照成员版本、原人工修订和触发 Verification。前后 query 可以不同。

**Tech Stack:** FastAPI、SQLAlchemy、隔离 SQLite；PostgreSQL DDL 编译；共享 TypeScript、SDK、React 三端面板。

## 1. 依据、现状与方案选择

原规格第186–208行要求事实追加、人工决定与证据分别保留，第213、227–237行要求关注者只接收真正相关变化。R67已经接入八域，本轮解决能力表 `derived_manual_applicability` 缺口，完整推荐/信息流、来源/平台及全部 V1 Gate 均继续保留。

开工前只读核验 R67 清单通过：854源码、233展开dirty、11文档、178证据、194链接、15风险owner，staged/unmerged均0。原清单与新核验摘要位于 `.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/r67-before-r68.json`；旧回执只绑定改动前快照，不覆盖。

现有 `curation.review_state` 按 variant/source 的最新事实ID判定适用性，query不参与；整条fact改变便可能失效。`service.record_success` 即使304也协调事实头，所以跨query的合法304可能新建actual fact v3而快照member仍v1。没有新fact的304、同facts新正文、仅目录/元数据变化不使overlay失效。目录review与人工overlay适用性是两套已有规则，本轮不顺手改变。

备选方案：只转发来源参数事件无法说明人工有效值变化；伪造 ManualFactRevision 会错误声称人工做了决定。采用独立追加派生记录，保留旧人工修订号和独立派生修订号。

## 2. 冻结合同与不变量

| 合同项 | 固定值 |
|---|---|
| domain | `tire_curation_validity`（22字符，满足既有24字符列） |
| evidence kind | `tire_curation_applicability_event` |
| action / state | `invalidate` / `needs_review` |
| before state | `applicable` |
| changed_field | `curation_applicability` |
| migration | `018_interest_manual_applicability` |
| model / table | `TireCurationApplicabilityEvent` / `tire_curation_applicability_events` |

1. 一条新实际FactVersion对一个variant/source至多产生一条派生记录，`after_fact_id`唯一；独立revision按variant/source递增。只有原事实存在且至少一个字段的最新人工头为manual_override/revoke、base_fact_id恰为before fact时产生。clear_override、旧base、已needs_review、其他source/variant不纳入。重新人工核验后的下一次新base可再次触发，不能自动恢复任何旧覆盖。
2. 账本最少字段：id、variant_id、source_id、before_fact_id、after_fact_id、verification_id、revision、action、manual_revision_watermark、affected、binding、created_at。fact与verification使用真实FK；unique约束、ORM追加保护与018幂等/DDL事务保持既有架构。既有行不修改、不回填旧派生事件或通知。
3. affected[]逐项冻结 `manual_revision_id/manual_revision/field/action/before_status/after_status/manual_fingerprint`；before_status为manual_override或revoked，after_status为needs_review，fingerprint为R67公共原行digest。watermark是当次variant/source最大人工revision，冻结前后重建不得借后续人工头或时间减一微秒。
4. binding.before/after分别保存该侧来源依据：`snapshot_id/source_id/query_key/source_url/raw_hash/identity_contract_version/parsed_variants_hash/verification_id/verification_status/verified_at/member_hash/structured_locator`，以及 `fact_version_id/fact_version/facts_hash/snapshot_member_fact_version`。实际fact字段与快照member字段分别核验，允许合法304的版本分离；前后query允许不同但variant/source必须一致。after verification必须是本次真实采纳，时间来自本次新fact/verification，不能用304复用快照的旧观察时间。证明缺口明确保留，不以当前身份补证。
5. before使用旧source facts并应用当时全部有效人工头；after使用新source facts，受影响项标记needs_review。零、null、缺席严格区别；原ManualFactRevision及其动态valid_to推导不改。changed_paths仅列真实effective值差异及curation_applicability/state：新source值恰等于旧manual值时不伪造facts路径。原来源事实事件仍只表达来源事实变化。
6. 多来源不拼AND，mixed条件只用当时有效的已审精确关系；目录重入、SKU恢复或撤回身份映射不能被新派生事件复活。缺少旧侧可核验身份的合法采纳可留下indeterminate派生记录而不通知；不反向阻断既有合法来源采纳。
7. 新账本、source snapshot/fact/change/verification、目录账本、兴趣事件和通知在同事务；写入/通知失败全部回滚，不吞错、不另commit。保存兴趣仍future-only，history/reader不补账本、不补发、不发起抓取或调度。
8. 精确reader复用 `GET /v1/interest-evidence/{kind}/{record_id}?mode=history` 和 `interest-original-evidence@1`。新增kind重新读取独立原行及公共digest，核对原实体、独立修订、关联人工原行与两侧来源依据；缺失404、不符409，不返回最新记录或通知副本。旧四类原行含义保持不变。
9. 共用UI显示“人工处理适用性”“来源事实更新后待复核”，明确原人工决定仍保留；区分原人工修订和派生修订。可按原ID重开原人工决定及派生原行，并重开前后完整来源原文、核对scope/raw hash/正文SHA256。适用性reader不能沿用目录“两侧query相同”的守卫。
10. 能力表新增第九域并移除已交付的derived缺口；来源拒收/隔离及仅元数据核验仍明确未覆盖。同cookie session_scope政策保持既有范围，不宣称严格服务器账户隔离。

## 3. 任务、所有权和执行步骤

### Task 1：后端账本、生产者与精确reader（review_corpus_ultra）

Create: `apps/api/tire_api/interest_applicability_models.py`、`apps/api/tire_api/interest_applicability.py`、`apps/api/tests/test_interest_applicability.py`。

Modify: `service.py`、`interest_governance.py`、`interest_events.py`、`interest_matching.py`、`db.py`、`migrations.py`、`apps/api/tests/version_registry.py`；必要时 `test_core.py` 的旧schema构造与既有迁移fixture，保持生产FK。不得修改前端或独立review测试。

1. 先写单次/多字段失效、无新fact、去重和事务回滚反例，在私有GUID目录记录修前结果。
2. 实现018表、原事务hook、watermark/actual fact绑定、冻结adapter、历史候选与原行reader；与前端同步上述固定键名，不擅改冻结语义。
3. 运行新目标及受影响curation/interest/迁移和旧schema节点；阶段失败保留原回执，修正后只按实际复跑范围报告。

### Task 2：共享类型、SDK与三端面板（review_wire_ultra）

Own: `packages/domain-types/src/interests.ts`、必要根出口、`packages/api-client/src/index.ts`、`packages/api-client/tests/interests.mts`、`apps/web/components/interest-center.tsx`。读 `apps/web/AGENTS.md` 与适用Next指南后修改。不得同改后端/独立测试/Root QA。

1. 新domain/field/kind、SDK合同及明确中文状态；保持旧原行和Auth ready/ownerEpoch/AbortSignal完成时主体核对。
2. 派生reader核对独立record与affected人工ID/修订/指纹；两侧完整原文分别核对，允许跨query、actual/member分离，错误不显示替代当前值。
3. 跑SDK注入合同、workspace typecheck和三端前端生产构建；独立输出目录，记录源码/制品SHA，恢复生成配置原字节。构建期间Root不启动Next dev。

### Task 3：独立业务、迁移和事务审查（review_handoff_ultra）

Own: `apps/api/tests/test_interest_applicability_review.py` 与专属新 `.artifacts/review-r68-*`；不改产品源码、前端或他人测试。

1. 独立覆盖其他字段更新、source恰等于manual、revoke/null/0、clear和旧头、多source、多query304 actual/member、目录独立规则、并列时间、A→B→A、重新人工核验后再次失效。
2. 事务注入失败验证完整采纳回滚；018旧行/幂等/DDL回滚/SQLite真实FK和unique、PG仅DDL；精确reader在后续刷新后不漂移，缺失或篡改拒绝。
3. 提交具体反例交实现owner修复；冻结后跑最终具名源码绑定目标，不将PG编译或浏览器视口当真实PG/设备。

### Task 4：集成、文档和新封存（Root）

Own: `scripts/interest_web_fixture.py` 必要扩展、新R68 API/UI QA脚本、计划/报告、README/交接/总计划/风险和新机器清单。其他人不改这些文件。

1. 用私有合成fixture产生普通失效、纯状态变化、304跨query协调与后续旧原行重开；不启动默认API或迁移正常库。
2. SDK/构建完成后，真实私有API与Chrome核验前后effective/source区分、原人工决定和派生原行、两侧完整原文；1440桌面/390手机布局与截图目视。
3. 停止并确认自建进程、端口与页面，按SHA恢复生成配置；更新所有当前入口和剩余队列。旧R67文件/清单/回执维持历史身份。
4. 新机器清单绑定现场HEAD、apps/packages/scripts source集合、展开dirty、原始需求、文档、风险owner和明确allowlist证据；排除私有DB/对象/凭据/大raw制品。独立核验后收尾，清单不等于归档。

## 4. 验证与工作边界

使用 `C:/Program Files (x86)/PowerShell/7/pwsh.exe` 和 `apps/api/.venv/Scripts/python.exe`；每个runner先设置私有DB/对象/bundle后导入应用，AI/Embeddings关闭并限制外联/子进程/数据库路径。目标pytest保留log/JUnit和前后源码SHA；Node/类型/构建分别记录；`git -c core.whitespace=blank-at-eol,cr-at-eol diff --check`。

保持Parser8秒、并发2、CPU5秒、384MiB；不reset/clean/stash/commit/push，不覆盖未知dirty。正常库/对象、真实官网/模型、完整API/Worker、真实PG、原生宿主/凭据/设备、生产迁移/签名/发布及完整V1 Gate，没有实际执行就继续列为未验证。上一轮是有源码与证据变化的实质进展，本轮继续推进原完整目标，Goal保持active。

## 5. 实际执行记录

以下为实际实现及已取得的限定证据，不从前文预期推定完成；逐项回执见[第68轮报告](../assurance/evidence/round-68-interest-manual-applicability.md)。完整Goal保持active，完整V1未完成。

### 5.1 最终实现与合同核对

1. 新增 `interest_applicability.py`、`interest_applicability_models.py`，在QueryService采纳事务内按actual新FactVersion聚合失效字段；注册 `018_interest_manual_applicability`。新表只追加，after_fact_id唯一、variant/source/revision联合唯一，三个事实/验证引用有真实FK。不修改旧ManualFactRevision、不回填旧派生事件/通知，正常库未升级。
2. 最终域/kind为 `tire_curation_validity / tire_curation_applicability_event`，动作invalidate、before applicable、after needs_review，changed_field为curation_applicability。affected固定关联人工ID/修订/字段/动作/状态/公共digest；独立派生修订与manual_revision_watermark分别冻结，不能借后续人工头重构旧事件。
3. binding保留前后各自来源/query/snapshot/member/验证及actual fact证明，并冻结成员presence。支持跨query304 actual v3/member v1，事件时间来自本次新fact/Verification。无新fact304、仅目录/正文/元数据变化不使overlay失效；目录review规则独立保持。
4. 两侧source/effective facts分开，before应用当时仍有效的override/revoke，after回到新来源事实；clear/旧base/已失效头排除。changed_paths只包含真实effective facts差异及curation_applicability/state，source恰等manual时不伪造facts差异。原source事件与原人工决定语义保持。
5. 新kind使用R67精确history reader外壳，重读派生原行，核对实体/独立修订/公共digest、关联人工及两侧basis；缺失404、不符409，不读最新替代。旧历史身份证明不足时合法采纳继续成功，派生事件indeterminate且不通知。新账本和通知失败随原采纳事务回滚。
6. 共享类型/SDK/共用UI接入第九域、关联人工原行与两侧完整原文，允许不同query及actual/member版本分离。主体/取消防护保持；编译与代码检查不能代替迟到响应、原生或账户隔离运行时验收。future-only、history不补发及同cookie session_scope政策不变。

### 5.2 分阶段验证与失败保留

- 后端预实现0通过/3失败；首集成0通过/3失败来自fixture查询scope不一致：prepare model+size与刷新size-only对应不同query-local SKU。仅修fixture为同scope后3通过，未放宽产品身份规则。最终受影响回归69通过、0失败/错误/跳过，18具名文件（14产品、4测试）运行前后SHA/长度稳定。各阶段分开保留、不相加；未重跑完整API/Worker。
- 独立早期1失败/22 deselected为curation_applicability尚未进入changed_fields、兴趣创建422；随后23通过，补三类旧车型链/future-only的4目标通过，最终封存27通过、0失败/错误/跳过。31具名产品/测试/helper/runner文件前后稳定，报告时再核无漂移。不存在23+4+27合并计数；最终组未发现需再次修改产品的问题。
- 独立覆盖多字段/其他字段触发、source等manual、0/null/缺席/revoke、无新fact与目录边界、clear/旧头/重新核验、跨source AND、跨query304、并列时间watermark、两类完整采纳回滚、旧证据缺口、目录重入/restore/identity clear后的旧关系不能复活、只读/future-only、四类精确原行关联篡改、018保留/幂等/DDL事务、真实SQLite约束。PG只有表/索引DDL编译，未运行PG。
- SDK注入transport合同、workspace typecheck及Web/Desktop/Mobile前端生产构建五阶段均exit0，前端总回执passed/issues0，16相关源无漂移且封存时再核一致。本轮实际修改4文件、22制品、13证据文件（含before.json）；Web静态页5/5、PWA生成17项allowlist后恢复，生产构建阶段7生成文件核对恢复原字节（含原本相同者）。这些数量不是业务测试数，三端前端构建不等于原生或PWA更新验收；既有大chunk/独立输出目录提示保留。
- Root实际私有API83/83断言通过、done=true。首次450→300聚合两个真实人工头，0→0只报状态不伪UTQG路径，跨query304 actual7/member5并允许前后query不同；原人工450与旧派生原行在当前源334后仍精确。还覆盖clear/旧头不重复、重新核验再失效、无新fact普通304/正文、future-only及R/ZR/未审车型不猜配。83是断言数，不是独立场景数。
- Chrome桌面1440×1000与手机视口390×844各30/30断言通过，无整页横溢；检查三类派生/人工原行、冻结条件、独立修订以及六侧完整旧来源原文，Root已查看桌面及两张手机截图。相同核心流程在两视口执行，不是60个独立场景或原生/完整账户切换/迟到响应矩阵。
- API/UI没有失败断言。首次Next入口错用apps/web/node_modules而MODULE_NOT_FOUND，无live session handle且未记录exit code；改解析根node_modules后成功，原/成功日志分开保留，是工装路径修正。手机模拟重载后重新注入冻结引用再跑最终检查，截图内联按原字节保存。
- 后端/独立runner外网、child和正常库尝试均0；69组loopback61、27组loopback24为TestClient自唤醒，计数不覆盖整个浏览器或Next。正常库、真实来源/模型、完整API/Worker、真实PG、原生设备/权限/生命周期、PWA更新和生产发布Gate未由本轮限定证据验收。

### 5.3 收尾与剩余范围

最终fixture为10次tire operation、6兴趣/6修订、31事件/29通知、8目录/4适用性/6原人工修订，累计表行数不是独立场景。API fixture external/parser child/Provider/normal DB attempts均0、未用正常库。API shutdown HTTP200且实测exit0，成功Next开发进程主动Ctrl+C后exit1；宿主复核8958/3370均无监听，测试页13关闭并保留原空白页12。

开发阶段3个生成配置按备份SHA/长度恢复，与生产构建阶段7文件恢复分别记账；Root语法/AST检查和scoped diff exit0，生成配置无残留diff。私有fixture存储保留本机且不入交接allowlist。全部回执、日志与截图入口见本轮报告，本次文档收尾没有重跑测试或构建。

主清单入口为 `.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/verification-final.json`，生成及独立核验由Root另行记录；本节不冒充最终主清单核验。旧R67文件/清单/回执保持历史身份，清单不是整仓归档或私有资料备份。未提交/推送/发布，继续其他相关事件与跨域治理、完整推荐/信息流、真实专业样本/Golden、来源/平台矩阵及全部发布Gate，完整Goalactive、V1未完成。
