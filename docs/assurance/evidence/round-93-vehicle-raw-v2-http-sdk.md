# 第93轮：车型原件 V2 HTTP 与 SDK

日期：2026-10-19。范围止于原件 HTTP、SDK/domain 接线和窄验证。依据冻结 PDF 合同 §5/§7、R93 map/addendum 与 [实施计划](../../plans/2026-10-19-vehicle-raw-v2-http-sdk.md)。Root 已独立核两份实际 run、source、报告计数、四份修改前原件及 S2/R38；本修订 seal 的整文件绑定与三个 R92 历史 suffix 待 Root 最终独核。

## 已实现与用途边界

三 detail 接受 `format=raw-evidence-v2&mode=history`，三 content 固定为对应 ID 的 `/content?mode=history`。V2 十键复用原件/冻结 provenance helper；保留各 endpoint 业务字段、capture receipt/query/storage_kind 及 quarantine 三分支。旧 text envelope 不增字段，旧 vehicle text 无 mode 继续兼容；未协商 binary409，history/format422、未知404、坏件503固定完整性码、用途403。binary 或固定来源/首代 row/query/capture 身份均进入新分支，合法 UTF8/JSON/hash 改写不能降级绕门。非 vehicle text 独立核严格 UTF8、MIME、长度、hash 及已存在的权威对象。

三个 binary metadata 和三个 content 分别检查同一完整性已核身份的 `local_original_read`；Snapshot/VehicleQuarantine metadata 带业务字段时另核 `structured_fact_use`。二者不互授，content 不要求 accepted/结构化用途；unknown capture/rejected 不制造解析成功或候选。生产两用途仍 pending403、Provider/export=false；私有可信政策 fixture 只用于工程正例。内容先全量验证，再返回固定 PDF attachment、no-store/nosniff/CSP，不实现 partial/range/206。历史可见范围继承 local-session/workspace，未新增逐账户 ACL。

SDK新增三 metadata 与三 content 方法，统一必需 `(id,fence,signal?)`，沿原 request/ApiError/credentials/no-store。内容内部重取 metadata，闭合 endpoint/分支 schema、ID 与唯一 content_path 后，只取固定 ID 路径；核真实 Blob、MIME/size、完整 bytes SHA256 与 `%PDF-`。每个异步阶段前后及返回前复核 caller fence、abort、transport epoch，后者不冒充账户 epoch。非null parser/provenance bundle ID 收紧为64hex，binary Snapshot/Capture identity 非null；旧 domain 50342B 前缀及旧 SDK 78055B 逻辑可精确重建。

## 实际验证与失败保留

| 实际 run | 选择范围 | 结果 | child |
| --- | --- | --- | --- |
| `.artifacts/r93-t-a64c203f9e71` | 1whole＋21exact，22targets/10modules，48cases | 41pass/7call fail；setup/teardown各48pass，runner3/pytest1，自然结束 | 15parser＋2旧Node＝17，全exit0/live0 |
| `.artifacts/r93-f-7c4e8a2d1b60` | 4exact/3modules，10cases | 10pass、三阶段各10，runner/pytest0，自然exit0 | 4parser＋2旧Node＝6，全exit0/live0 |

首run的7红为 case8–11 `test_fixed_first_generation_identity_cannot_be_downgraded_to_utf8` 与 case12–14 `test_nonvehicle_v2_text_integrity_and_existing_object_are_authoritative`，安全失败均 `ValueError/apps/api/tire_api/db.py:460`。新 fixture 通过 ORM 改写 append-only 历史，未到 HTTP 断言。完整保留首run与22941B/df73ab…旧 test 后，仅两函数改为既有风格的 Core 私库损坏；参数/decorator/断言不变，生产防改写保护未变。另经静审收紧 SDK 身份合同，并保留三个 SDK 修改前完整文件。

最终覆盖取首run case1–7、16–46共 **38**（114阶段全过），加复验 **10**，共 **48唯一分批目标**；总执行58，不是一次48全绿、49或58唯一。新API模块18case、旧兼容30case；原始160只是 runner manifest，未跑全部 API/Worker。复验覆盖两fixture函数8case与两个旧Node；原首红不改写。

两run nodeids/reports逐索引一致；JUnit分别48/7failure及10/0；progress分别144与30条 test_report，各另1条 collection_finished。两run selfcheck均通过、无reporting failure、资源关闭，listener/retained endpoint0、非selfcheck拒绝0，正常DBfalse、真实Provider/receiver0。child累计23＝19parser＋4旧Node，均exit0/live0。

| 公开回执 | bytes | SHA256 |
| --- | ---: | --- |
| 首 result.json | 23893 | `081d5d0b56adc90b9f6b83f5456709581244b012633308f0b82302894315bd1c` |
| 复验 result.json | 20425 | `921de7f12d56bdcb8bcacdafb22906223727708e4ed8e26b62c01bbd825b7026` |
| 首 source-before/source-after，各 | 123644 | `be275f96e186f6f199020688a52d18401d141131568fb6e25b3dbd0d3ed06005` |
| 复验 source-before/source-after，各 | 123644 | `4dafdeae1ff836b3defb66e2cb4465c83df941ac96938e7c0bc32a8a9335e0f3` |

各run686 source首尾整文件相同；第二686与live逐项相同。相对R92恰7旧源变＋3新/0删；跨run恰4源变：API新test、domain index、raw-evidence-v2 module与未执行.mts。首run的这四项分别由 `.artifacts/r93-fixture-core-fix-a9e316f2c870/test_vehicle_raw_v2.before.py` 与 `.artifacts/r93-sdk-identity-fix-8218e7f5debc4c11/before/` 三份完整原件匹配；其余682源保持。API四生产、SDK index、runner及Guard/ChildPolicy跨run未变；31旧vehicle_raw顶层定义源码保持。不是修改前产品回归或全栈验收。

## 原件证据、未验范围与下一入口

独立S2 before/after位于 `.artifacts/r93-meta-a64c203f9e71/` 与 `.artifacts/r93-meta-7c4e8a2d1b60/`：四份采样及live均3240150B/`0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，与每次pre-use核分列。R38仅hash核对，前后/live均25374720B/`a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4`，未打开正常库。

历史S2在私库经真实隔离child/receipt与TestClient路由验证；新的policy、mapping/deployment/directory及unknown PDF是明确合成fixture，不等于新在线capture、生产许可、正式release或真人Golden。真实quality rejection另走实际ingestion。两个合法Node仅运行既有公共import/Device DTO与prepare消费包装；新增 `.mts` 编写但未执行，未运行tsc/npm、新SDK Mock或真实HTTP→SDK，不能用source binding或旧import替代Blob/abort/fence行为验收。Guard/ChildPolicy/launch/REVIEWED固定边界未放宽。

下一入口先审[车库与离线事实复制用途闭包](../../../.artifacts/vehicle-binary-garage-offline-4a8127c9df65/proposal.md)，再另轮审[SDK受管入口](../../../.artifacts/sdk-raw-evidence-managed-entry-83b5d6f392c042ca/proposal.md)及UI/Native保存前同一fence接线；两提案均仅候选、未实施或运行，不与R93混账。SDK提案的 `.mts` pin 属于旧快照，实施前须对齐届时封存源；当前禁止裸Node/tsc绕行。首代fetch/ready仍关闭，requires_source_verification、生产两用途pending与Provider/export=false保持。PG旧迁移/活PG、正常库保全升级及完整PDF/V1 Gate仍开放，原Goal继续active；未提交推送。

原R93 seal `verification-final.json` 保留原字节；本次修订前报告与三入口完整原件保全于 `.artifacts/r93-next-order-preservation-0f3e1d4bfabe4d53/before/`。仅修本文及三入口R93前缀，整个R92后缀原字节保持，冻结合同/计划/map/addendum与历史seal不改。本修订seal候选为 `.artifacts/r93-close-6b28c4d9e173/verification-final-v2.json`，待Root最终独核。
