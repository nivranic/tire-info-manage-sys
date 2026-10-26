# 第67轮：治理与目录变化的兴趣通知（2026-10-18）

本轮继续原规格第213、227–237行的本地兴趣关注切片，将手工参数纠错、SKU生命周期、身份决定和来源目录成员变化接入第66轮的冻结事件与私有通知。七类条件保持不变，支持域由四个增至八个；通知可以重开对应的原始治理记录。完整推荐、相关信息流、实时监控及完整V1仍未完成。本轮未提交、推送、迁移正常库或发布。

## 实现与最终合同

[实施计划与最终合同](../../plans/2026-10-18-interest-governance.md)保留需求、文件所有权及终态记录。四个新增域的精确名称如下；旧四域合同继续有效。

| 域 | 业务动作 | 原始 evidence kind | 含义和限制 |
|---|---|---|---|
| `tire_curation` | `manual_override / revoke / clear_override` | `tire_curation_revision` | 本地人工决定，按原source/base恢复前后有效值；保留来源原值、null、零与字段缺席 |
| `tire_lifecycle` | `revoke / restore` | `tire_lifecycle_event` | 本地SKU状态；不代表官方召回、来源停售或参数变化 |
| `tire_identity` | `correct / merge / clear` | `tire_identity_revision` | 本地追加映射；原source是匹配主体，target只作决定依据，不移动事实或重定向兴趣 |
| `tire_catalog` | `added / removed` | `tire_catalog_revision` | 同source/query的相邻已采纳结果中的成员变化；目录移出不等于撤销SKU |

- 新增追加表 `tire_catalog_revisions` 及迁移 `017_interest_governance_catalog`。每行冻结原variant、前后snapshot/Verification、presence与完整binding；唯一约束为 `(variant_id, source_id, query_key, revision)` 和 `(variant_id, verification_id)`。SQLite真实唯一约束、外键及ORM不可更新/删除已验证，正常库未升级。
- 四域均在原业务事务中发布；通知失败会回滚原业务记录及其关联写入，不另行commit。仅接受历史中可复核的证据；合法旧治理记录缺少历史身份时仍允许保存，事件为 `indeterminate` 且不通知，不借当前身份补证。
- 完整AND必须在一个来源上下文的同一侧成立。手工纠错使用直接的 `identity/facts/source_facts`；生命周期、身份和目录使用 `source_contexts[]`，不跨来源拼接。生命周期/身份撤销前态保留原关系的退出解释，restore/clear后旧关系须重新review；目录移出前态也可解释退出，移回不会复活旧关系。
- 目录 `changed_paths` 仅为 `catalog_membership/state`，状态为 `present/absent`。事实不变的移出、重入及A→B→A重复快照对仍有独立origin；304和成员不变的重验不伪造目录变化。目录关系链以完整成功Verification历史重建，包括017以前的历史，不以未回填的新账本修订替代。
- 精确reader为 `GET /v1/interest-evidence/{kind}/{record_id}?mode=history`，返回 `interest-original-evidence@1`、`local_workspace/local_snapshot`、kind/id/entity/revision/fingerprint、公共原行record及evidence。指纹来自重新读取的公共原行，排除内部session、idempotency_key、request_hash及动态适用性；404 `interest_evidence_not_found`、409 `interest_evidence_mismatch`，非法kind或mode为422。读取原记录，不返回最新替代记录或通知副本。
- 共享类型、SDK根出口和三端共用面板已适配四域、新筛选字段 `curation/identity_resolution/catalog_membership` 与原始reader。前端核对kind/id/entity/revision/fingerprint，保留Auth ready、ownerEpoch与AbortSignal边界。
- 保存/修改兴趣仍为future-only，不补历史通知、不创建抓取或调度。来源刷新使旧人工overlay失效属于能力表明确列出的 `derived_manual_applicability` 缺口；来源拒绝/隔离与仅验证元数据亦不伪造已采纳事件。同浏览器session_scope资料带入政策沿用第66轮/ADR-057，本轮不宣称永久账户隔离。

## 分阶段验证

下表按实际执行顺序和范围分别记录，不能将数量相加，也不能将后续目标通过写成先前整组全绿。回执目录同时保留日志/JUnit；源码稳定只适用于各次记录的具名文件。

| 阶段 | 实际结果 | 回执与范围 |
|---|---|---|
| 第66轮修改前绑定 | 848源码、9文档、92证据SHA/长度一致，issues为空 | [r66-before-r67.json](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/r66-before-r67.json)；旧final-v2保持历史身份 |
| 后端预实现反例 | 3失败，0通过 | [before](../../../.artifacts/review-r67-backend-before-c9c76031ca744d1f89dc6702723d1f72/verification.json)；新能力实现前 |
| 后端首批治理 | 3通过 | [first](../../../.artifacts/review-r67-backend-first-84489c5dcefa4d3a9d5c1c59dc59a7e1/verification.json) |
| 后端受影响原行为回归 | 136通过、2失败 | [regression](../../../.artifacts/review-r67-backend-regression-df5d8700c2c04b8f8e5d23b9cc01a7bc/verification.json)；旧总事件计数与旧schema模拟前提，详见下文 |
| 后端修正目标 | 10通过 | [final-target](../../../.artifacts/review-r67-backend-final-target-fee116d47845462f8fe121b2a470a724/verification.json)；3治理、5迁移、2修正节点，11产品源稳定；早于目录链修复 |
| 独立第一/第二批 | 17通过；随后19通过 | [17项](../../../.artifacts/review-r67-governance-4beaeed6d04446fa9e16eeaaf9b96f7c/first-9ec916ba83264c8ead97c7240878a220/verification.json)、[19项](../../../.artifacts/review-r67-governance-4beaeed6d04446fa9e16eeaaf9b96f7c/final-d89e8a9feb0d46709a183269065cf400/verification.json)；当时尚无新增目录链反例 |
| 独立P1目录链反例 | 修前1失败/19 deselected；修后1通过/19 deselected | [修前](../../../.artifacts/review-r67-governance-4beaeed6d04446fa9e16eeaaf9b96f7c/catalog-chain-before-cb3545ca5bb1457cbce5e5258b9d381c/verification.json)、[修后](../../../.artifacts/review-r67-governance-4beaeed6d04446fa9e16eeaaf9b96f7c/catalog-chain-after-825dfad9a8c54b89af1434b7f128d5d1/verification.json)；两次具名源码均稳定 |
| 后端目录链正反控制 | 5通过 | [catalog-chain](../../../.artifacts/review-r67-backend-catalog-chain-a725b845cae844208d06638eb5bc4e7b/verification.json)；含P1反例、原合法UTQG正链及3治理，2产品源稳定 |
| 后端最终目录相关回归 | 35通过 | [catalog-regression](../../../.artifacts/review-r67-backend-catalog-regression-f5bf8f6c30b5445f996e2cf7286ebc11/verification.json)；interest_events、interest_review、interest_governance三组，11产品源稳定 |
| 独立最终封存 | 20通过，0失败/错误/跳过 | [sealed](../../../.artifacts/review-r67-governance-4beaeed6d04446fa9e16eeaaf9b96f7c/sealed-18e359d39a864259b02d7356addb0e42/verification.json)、[独立报告](../../../.artifacts/review-r67-governance-4beaeed6d04446fa9e16eeaaf9b96f7c/R67-REVIEW.md)；20个具名产品/测试文件SHA与长度无漂移 |
| SDK兴趣目标合同 | exit0 | [sdk](../../../.artifacts/runtime/interests-governance-frontend-59550dc28197425b8e7f37b81c22687f/sdk-verification.json)；`npm run test:interests --workspace @tire/api-client`，公共类型及注入合成transport探针，不是后端集成 |
| 工作区类型检查 | exit0 | [types](../../../.artifacts/runtime/interests-governance-frontend-59550dc28197425b8e7f37b81c22687f/types-verification.json)；`npm run typecheck`，不是原生运行 |
| Web前端生产构建 | exit0，静态页5/5 | [web](../../../.artifacts/runtime/interests-governance-frontend-59550dc28197425b8e7f37b81c22687f/web-verification.json)；Next编译/类型/PWA生成，隔离dist为 `.next-r67-interest-governance` |
| Desktop前端生产构建 | exit0 | [desktop](../../../.artifacts/runtime/interests-governance-frontend-59550dc28197425b8e7f37b81c22687f/desktop-verification.json)；TypeScript/Vite资产，不是Tauri安装包 |
| Mobile前端生产构建 | exit0 | [mobile](../../../.artifacts/runtime/interests-governance-frontend-59550dc28197425b8e7f37b81c22687f/mobile-verification.json)；TypeScript/Vite资产，不是Android/iOS验收 |
| 隔离API第一阶段 | 57断言通过、1失败，done=false | [phase1](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-api-phase1.json)；合成目录触发来源质量门禁 |
| 隔离API第二阶段 | 3断言通过、1失败，done=false | [phase2](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-api-phase2.json)；fixture模式前提不成立，未继续业务断言 |
| 隔离API最终阶段 | 95/95断言通过，done=true | [browser-api-final.json](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-api-final.json)；私有合成数据与实际治理/QueryService流程 |
| Chrome桌面最终UI | 19/19断言通过，done=true | [desktop-final](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-ui-desktop-final.json)；1440×1000，无整页横向溢出 |
| Chrome手机视口最终UI | 19/19断言通过，done=true | [mobile-final](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-ui-mobile-final.json)；390×844，无整页横向溢出；不是原生设备验收 |

[前端总回执](../../../.artifacts/runtime/interests-governance-frontend-59550dc28197425b8e7f37b81c22687f/verification.json)记录五阶段exit0、16项相关源码/配置/合同测试hash一致，以及22项构建产物hash（Web15、Desktop3、Mobile4）；五阶段不是五条业务测试，16项不是全仓覆盖。7个Web生成文件核对恢复到实施前原字节，含原本相同的文件，不是7处产品修复。PWA曾生成17项allowlist资源后sw恢复，不证明用户取得本轮PWA更新。前端没有失败阶段；Desktop/Mobile保留既有大于500kB chunk和独立artifact输出目录不清空提示。

独立最终20项覆盖：非法顶层evidence门禁、多来源AND隔离、生命周期/身份并列时间的前态与重新review要求、四个producer事务回滚、三类合法旧历史缺口、目录成员/重复快照/304/旧车型链、合法304 actual fact与snapshot member版本分离、旧base overlay隔离、公共原行reader、017旧数据保留/不回填/幂等/DDL回滚、真实SQLite约束及PostgreSQL表/索引DDL编译。并列时间动态用例覆盖生命周期和身份，不能扩称全部目录时间排列已穷举。PostgreSQL没有实际运行。

最终API断言覆盖人工override/revoke/clear与零值、生命周期revoke/restore、身份correct/clear不重定向、显式重新review、目录移出/重入/304/重复origin，以及重入后实际UTQG更新的混合兴趣反例和普通事实正控。四类旧原始记录在后续动作与来源刷新后保持精确；缺失/错误kind不转读最新。最终49条通知是该合成流程的累计数据，不是49个独立场景。

两种视口分别检查四域中文说明、冻结条件解释、四个精确原始记录和目录before/after完整资源。当前来源UTQG已更新为333，旧原始记录及目录前后whole body仍读到原300；目录移出从完整旧正文证明成员缺席。Root已查看[桌面截图](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/desktop-catalog-dialog.png)与[手机截图](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/mobile-catalog-dialog.png)，[布局/看图记录](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-ui-layout-visual-review.json)保存断言及测量。视口结果不证明Android/iOS或桌面原生宿主运行，也不覆盖完整账户切换矩阵或主体变化后的迟到响应运行时验收；请求取消有SDK合同探针，owner/epoch迟到响应保持代码防护，本轮未单独运行该浏览器场景。

## P1修复与工装失败保留

独立审查实际复现：已审exact SKU/车型关系 → QueryService采纳4个SKU → 移出1个 → 原SKU以相同facts重新加入。适配接口已返回 `needs_review`，后续UTQG事实变化却仍借旧关系给车型+品牌+尺寸组合兴趣推送。根因是 `_reviewed_contexts` 只比较生命周期/身份修订，遗漏目录成员transition。本轮已修复，并要求移出仍由before侧正确通知、重入及之后UTQG不得复活旧关系、品牌事实正控仍通知；修前失败、修后单项与最终20项均保留。

修复从完整成功Verification序列重建 `source_id/query_key/present/transition_revision`，与relation原binding核对；before按明确的 `previous_verification_id` 截断，after包含当次验证，不用减一微秒。017不回填历史，因此没有错误地将新目录账本revision当作旧关系的历史证明。

138项阶段的两个失败分别为：原轮胎事务测试仍将全部InterestEvent总数固定为1，新增独立目录事件后实际为2；旧schema模拟在重建verifications前没有先移除017目录外键表。修正仅适配测试前提，没有取消外键或回滚断言；随后10项目标及最终35项相关回归通过，**没有重新跑整组138项，不宣称整组最终全绿**。

API第一阶段的合成目录行数损失触发 `source_quality_quarantined/row_loss_threshold`，[只读诊断](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/phase1-source-quality.json)保留。第二阶段为扩成4行而加入的两个控制行尺寸超出原query，被生产schema以 `source_unavailable/source_schema_validation_failed` 拒绝，fixture模式前提未成立。Root停止该API后，将控制行改为同查询范围、不同品牌/代码的同size R记录，并增加seed live和4行硬断言；第三个host完成最终95项。修正限于合成前提，没有放宽查询schema或来源质量门禁。

[首次桌面UI工装回执](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-ui-desktop-phase1.json)保留8断言通过/1失败、done=false：工装匹配“不代表”，实际说明为“不表示”。只修正文案断言后，两种视口分别19项通过；没有为通过工装改写产品含义。以上失败均不计入最终成功数量，也不由最终结果抹去。

浏览器截图filePath受工具workspace范围限制，图片先返回内联，再由本地按原字节保存；手机模拟重载导致首轮缺少页内public references，重新注入后才运行最终检查。截图前重开桌面对话框没有计为新增覆盖。

Sandbox preflight中API/Next各自报告ready，但其他exec会话和Chrome连接本机端口超时；Root主动Ctrl+C停止两个进程，均exit1，日志[api-runtime-1.log](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/api-runtime-1.log)与[web-dev.log](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/web-dev.log)保留。之后按获准host模式使用同私有路径重启才可访问；这是观察到的环境差异，不宣称根因修复，未改产品或预算，也未将preflight计为通过。

## 运行时收尾

[最终fixture](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/runtime-host-3/fixture-final.json)记录7兴趣、7兴趣修订、45事件、49通知及24目录记录；这些是合成运行的累计表行数。最终API shutdown HTTP200且实测exit0；Next开发进程主动Ctrl+C后exit1。此前两个API进程亦exit0，四个本轮私有端口均无剩余监听；测试页关闭，仅保留原空白页。Root的[停止回执](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/runtime-closeout.json)记录实际状态。

浏览器开发阶段涉及的next-env、tsconfig、sw三个生成配置按备份SHA/长度精确恢复，[browser-generated-restored.json](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/browser-generated-restored.json)保留逐项结果；它与前端构建阶段7文件恢复是两个范围，不相加为10个独立修复。私有fixture存储保留本机，不纳入交接证据allowlist。

## 证据边界与后续

独立审查外部网络尝试、子进程尝试、正常数据库尝试均为0；16次loopback为Windows asyncio/TestClient自唤醒，没有产品监听服务或浏览器。最终API fixture另行记录 `normal_database_used=false`、Provider调用0、外部网络尝试0、Parser子进程0；这些计数只覆盖相应API/独立runner，不能扩大为浏览器、Next或整个工作站都无外联。Parser墙钟8秒、并发2、CPU5秒、384MiB预算未放宽。

正常数据库/对象目录、真实官网来源、模型、完整API/Worker回归、PostgreSQL运行、原生安装包/设备/凭据权限/生命周期、PWA离线更新、生产迁移/签名/发布及全部V1 Gate均没有由本轮上述限定证据验收。第63轮全量和第66轮旧回执继续保留其历史源码身份。

本轮机器清单入口：[verification-final.json](../../../.artifacts/r67-interest-governance-1792303216270-bd0c521d/verification-final.json)。源码/dirty/文档/allowlist清单的生成与独立核验由Root另行记录；本文分项结论来自上表实读回执，不声称已独立核验最终主清单。清单只能证明采集快照一致，不是工作区归档、私有数据备份或产品验收替代品。后续继续补derived人工适用性、其他实体/相关事件、完整推荐/信息流、真实专业样本与Golden、来源/平台矩阵及生产发布Gate；Goal保持active，完整V1未完成。
