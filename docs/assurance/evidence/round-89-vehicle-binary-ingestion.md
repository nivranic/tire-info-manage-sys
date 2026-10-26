# 第89轮 车型二进制写入与有限消费者闭包

日期：2026-10-19。**VehicleService binary 采纳、质量隔离与有限消费者闭包已实现；118唯一目标已分批验证。**首 run 117通过/1失败的原红保留，仅一处测试期待修正后精确两项复验通过；不是一次118全绿。

本轮把 R87 的独立 binary capture journal、R88 的 PDF child 与 R86 的冻结原件 helper 接到 `VehicleService` 写入路径。范围是 binary 事实采纳、质量隔离、旧详情/审批拒绝，以及同步 InterestEvent 和知识索引的必要闭包；不是完整 PDF/P5、binary 审批/重解析/发布治理或 V2 API/SDK/UI/Native 交付。依据[冻结合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)，承接[第88轮](round-88-vehicle-pdf-child.md)。

正常库未连接启动；真实历史 S2 仅在私有 SQLite/ObjectStore 中离线重放，经实际隔离 child 与 returned receipt。私有 adapter 的 `ready`、mapping/deployment/directory 都是合成授权 fixture，不改变生产首代目录、在线 fetch 或正式 Parser release/外部真人 Golden 资格。InterestEvent/InterestNotification 是数据库链，receiver/network 调用为 0，不称外部推送验收。

## 受管运行及输入绑定

两次受管运行均已自然终态，Root 独立复核实际 result、安全 reports/JUnit、三阶段分账和源码绑定。首红与窄复验均保留：

| 实际运行 | 回执 bytes / SHA256 | 结果 |
| --- | --- | --- |
| `.artifacts/r89-t-5c8017e29da4/result.json` | 21467 / `98a45581f7e778bcde034401158266e1e12bb6117a718b6a6e0ada47e1d0f815` | 118 collected/protocol/executed，117通过、1失败，0 skip/incomplete；runner3、pytest1 |
| `.artifacts/r89-f-6d8f2c740a91/result.json` | 19656 / `3f99fae19942990844bf7bb80063125f8dd91b0d3c61e80723d3bc072c3709b7` | 精确 fence 函数两项，2 collected/protocol/executed且2通过，0 fail/skip/incomplete；runner0、pytest0 |

首 run 的 setup/teardown 各118通过，call 为117通过/1失败；唯一失败为 case index11 的 `test_binary_adoption_preserves_real_source_and_selection_fences`，safe `AssertionError` 定位 `test_vehicle_binary_ingestion.py:356`。原实现先比较已 pin 的 source access generation；并发 pause 递增 generation，故返回 `source_access_changed`，测试原误期待 `source_paused`。selection 分支的 `parser_deployment_changed` 保持正确。

保留首 run 原 test 明确副本 `.artifacts/r89-impl-04a6a3aab9d946a5ac1dab33654c0ad6/test_vehicle_binary_ingestion.first-run.before-fence-correction.py`（24016B / `8b518072e9bee69c8f19459b5bbc065c029a24c1634ba39745d6ec93f309e08e`）后，仅修正这一 Constant；未改生产、输入、参数 ids 或其他断言。correction 回执 `fence-expectation-correction.json` 同目录，2213B / `2dbecb45a7c041996694d7e3d8532df20084ba1b38f790d239b86233b571576d`。正逆字节差分精确，4205 AST 节点保持，唯一语义 Constant 位于 line356/index1996；最终 test 为24024B / `c8b6b25a5d98601ee14ef613f4087027f3dfd0882363108a948b70c73b72e17a`。

第二 run 只运行该精确函数，source/selection 两项 setup/call/teardown 各2通过。最终取首 run 其余116项＋第二 run 两项＝**118唯一分批目标**，不是一次118全绿，也不是120个唯一目标；首 run 已通过的 selection 项不重复计数。新 module 为21项（首20通过/1失败，后 fence 两项复验），新 module 最终覆盖取首其余19＋复验2。

| 首 run 实际目标模块 | 范围 | 首 run call |
| --- | --- | --- |
| `test_vehicle_binary_ingestion.py` | 整模块21 | 20通过/1失败 |
| `test_vehicles.py` | 整模块 | 29通过 |
| `test_vehicle_quality.py` | 整模块 | 12通过 |
| `test_interest_events.py` | 整模块 | 5通过 |
| `test_quarantine_review.py` | 整模块 | 19通过 |
| `test_knowledge.py` | 整模块 | 26通过 |
| `test_quality.py` | quarantine metadata/audited history 精确目标 | 1通过 |
| `test_source_settings.py` | 管理 guard 精确目标 | 1通过 |
| `test_parser_releases.py` | ABA及暂停保留 raw/真实 receipt 两精确目标 | 2通过 |
| `test_interest_review.py` | reviewed vehicle-SKU 链及通知失败原子性两精确目标 | 2通过 |

首 run 为6个整模块＋6个精确目标＝12 target条目、10模块；第二 run 是一个精确函数条目、两参数项。**154仅注册 manifest 长度，未运行全154。**R88及更早结果不与本轮相加为当前全套。

两 run 各678个源码输入首尾逐 byte 相同；第二 run 的678个全部与最终 live pins 一致。跨 run 只有上述 test 一 Constant 变化，首 run 由明确原副本绑定、其余677输入与最终 live 一致。相对 R88，本轮源码为五生产＋runner六变、新 test 一增、零删，其余671不变；文档和显式 S2 采样不属于678源码输入。

## 本轮实现范围

- `vehicles.py`：binary 观察继续由可信 source/query 与显式 encoding 校验；持有 ingestion lock 并重核来源/selection fence 后，先核 durable capture，再构建服务端六键 `parse_provenance`。snapshot/quarantine 存 `body=None`、`body_encoding='binary'`、`raw_capture_id`，`raw_hash` 来自原 capture，不把 PDF bytes 转成文本。caller 伪造 provenance 被拒绝，旧 UTF-8 路径保持。
- 采纳仍通过原 fact hash 与 parser identity 去重；重复观察增加核验、不伪造事实版本；同原件私有 mapping A→B 创建新 snapshot 并绑定新 mapping，旧 snapshot 仍保留原冻结身份；两者 raw/fact hash 相同，未变事实版本保持1，不回写历史 parse_provenance。capture 与 completed execution 独立于采纳事务保留；通知 INSERT 失败使采纳链整体回滚，不把独立 journal 一并回滚。
- binary 质量异常生成 `VehicleQuarantine` 并保留原件/冻结身份，不进入旧 UTF-8 `consume_approval`。`quality.py`、`quarantine_review.py` 与旧 vehicle evidence 详情在 binary 分支返回固定 `409 binary_evidence_format_required`，先于旧 body 编码或 binding 计算。旧审批 GET/POST 同样拒绝，不能把这一安全拒绝称为 binary 审批交付。
- `interest_events.py`：同步 `publish → freeze_vehicle → _vehicle_side` 在 binary 分支复用冻结 provenance/helper，避免 `None.encode()`；`_relation_side`、`_reviewed_contexts` 复用该 side，原 publish/freeze/relation/reviewed-context 算法保持。实际数据库通知与其 INSERT 原子性受测，不引入 receiver/网络链路。
- `knowledge_index.py`：公共完整性门在索引 signature 命中早退之前，覆盖搜索和 embedding prepare/validate 的共同 refresh 入口。完整 snapshot 用 `populate_existing=True`，避免 identity map 遮蔽低层损坏。损坏时返回固定 `409 vehicle_raw_integrity_failed`，Provider 调用为 0；warm 场景保留旧 index/plan 及 signature，不自动删旧索引、不回写冻结历史。
- 三处候选门分别位于 previous baseline、`_vehicle_side` 与 knowledge heads：`binary OR (SOURCE_ID + FIRST_GENERATION_ID)`。固定首代身份即使被合法存储 CHECK 接受地降为 `utf-8 + 非空 body + application/json`，仍进入原件/provenance 核验并失败关闭；该窄门不收紧全部历史 UTF-8。

本轮只覆盖为写入闭包必须同步执行的 side、lazy knowledge 公共门及其已测搜索/embedding 入口；不是全部 consumers、向量架构、webhook receiver、V2 原件内容路由或 SDK/UI/Native 验收。原 `fitment_fact_hash`、`vehicle_provenance`、knowledge document 构建及 UTF-8 审批 binding 算法未改。

## 新测试与样本资格

新 `test_vehicle_binary_ingestion.py` 在运行前经标准库 AST 静审：10 个函数，21 个静态参数项，全部参数短 ids，无 skip/xfail。实际首 run 已收集21项，其20通过/1失败及后续精确两项复验的分账见上文。

覆盖私有 file-SQLite 的独立 checkout：真实 recorder 回调之后、ParserExecution 尚不存在时，另一个 Session 已能核 capture/object/selection；随后执行实际 PDF child 并核 completed execution fingerprint、returned receipt 与 raw input_hash。其余反例覆盖重复采纳、私有 mapping 变化、binary 质量隔离与旧详情/审批 409、caller provenance 伪造、capture/execution 损坏、错 URL/车型、数据库通知 INSERT 失败、source/selection 并发暂停 fence，以及 cold/warm × object/execution/provenance/encoding 的八项消费者损坏场景。编码降级还从新 Session 单独验证同步 event side 与 previous baseline。

历史 S2 为 3240150B / SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，不是本轮新在线响应。每次读取先核大小/SHA；新测试核 actual child/receipt，既有 raw helper 回归仍含合成 completed receipt，不把历史身份反例全部称为真实执行或生产采纳。

四份显式采样均读取真实 S2 metadata，Root 已独立核其时间包围各自 completed 运行，原件均为上列3240150B / 同一 SHA256：

| 显式采样回执 | UTC | receipt bytes / SHA256 |
| --- | --- | --- |
| `.artifacts/r89-meta-5c8017e29da4/s2-before.json` | `2026-10-19T03:46:29.5053209Z` | 298 / `deb717654f62c835f695a52e78f5c9875ead624b0809067a81c2e4944c3efcf3` |
| `.artifacts/r89-meta-5c8017e29da4/s2-after.json` | `2026-10-19T03:53:19.2030653Z` | 298 / `a2e3f4dcd224e77796f870a10841b91933264e70884e89b0e60123c7f1154c4a` |
| `.artifacts/r89-fmeta-6d8f2c740a91/s2-before.json` | `2026-10-19T04:00:26.882578+00:00` | 294 / `e9035939aca0687557f1be059092433aa7ff6611cc2d48658d8910c17320b5a4` |
| `.artifacts/r89-fmeta-6d8f2c740a91/s2-after.json` | `2026-10-19T04:00:50.287754+00:00` | 294 / `e7b54006b935bf1008309300fbd3bd90b1922c493da118246847ad184e48ea49` |

显式 before/after、每次 pre-use 核验与678源码稳定是三种独立证据，不混称同一清单观测。

## 源码、静审与受管边界

| 当前文件 | bytes | SHA256 |
| --- | ---: | --- |
| `apps/api/tire_api/vehicles.py` | 32822 | `7c27ff29817cb1e3bd4a9ac2897efe4eb5607008babf69784440cff8ed2fb6f9` |
| `apps/api/tire_api/quality.py` | 21101 | `c93e4333668f6ecdf737d731315151c3f7bbd8f20c8d2a2d1bb3473e630b5449` |
| `apps/api/tire_api/interest_events.py` | 30019 | `633125c57742c2bc5ad91fb97373f6c2ad8ad0382a2b8a3bf4fe29289fc8ae27` |
| `apps/api/tire_api/knowledge_index.py` | 23442 | `4d9ca89110668bdee89bec4d504c676a979596d9c3d7ce0e0e5eefcd397f5416` |
| `apps/api/tire_api/quarantine_review.py` | 10319 | `c7ef304ec2c3c7612f1a0ab1bb25834c7e930eefe9fb099af966e5e8c53314c6` |
| `apps/api/tests/test_vehicle_binary_ingestion.py` | 24024 | `c8b6b25a5d98601ee14ef613f4087027f3dfd0882363108a948b70c73b72e17a` |
| `scripts/run_api_worker_regression.py` | 42519 | `5d023c2f7ae8f8bbe67737cba6ee8abc54b8fe0ebd61e71889cd44347800b600` |
| `scripts/regression_children.py` | 27470 | `c45982002e0c289529b03a371ce5b7696666d4239b82323d6e35b5837b7a4f7d` |
| `scripts/regression_guard.py` | 26536 | `23f34b2e58bd5fdc200e6c812df43632c96b1fff5d538ff307ef84cf9b592629` |

初始实现静态回执 `.artifacts/r89-impl-04a6a3aab9d946a5ac1dab33654c0ad6/static-verification.json` 为 4563B / SHA256 `31b42931cad7eba40a86eb2d074ac4f56db3dab8d5064b61a19d56ac5193db14`。该原回执及原 implementation.diff 保留首 run test pin，不以最终 test 覆盖；最终唯一期待修正另由 correction 回执、旧 test archive 及第二 run 绑定。baseline.json 同目录为3688B / `851e3ee814f1e57498c7775970a628c3079c358a007cf63c41b9f995a9596cae`，13份 baseline archive 与 R88 inventory 精确匹配；implementation.diff 为97768B / `aec66d5807a6e0e535b8b2bcf484178a7ce7e08cc23d7ca7ec5ee88426fd57ec`。独立全 diff、标准库 AST、源码 pins、合法 CHECK 降级场景及 warm 早退顺序均在 run 前通过静审；修正后再独立静审。静审本身无产品 import、pytest 或 SQL 执行。

五生产与新测试外，8 个复用文件与 R88 原字节一致：`vehicle_raw.py`、`captures.py`、`parser_provenance.py`、`parser_releases.py`、`test_vehicle_raw.py`、`test_vehicle_pdf_runtime.py`、`test_vehicles.py`、`test_parser_bundles.py`。旧 `binding/context/consume_approval/review_state/snapshot_review` 函数源码原字节保持。runner 只增加新 module 登记与两处 manifest 计数文字，逆回精确恢复 R88；ChildPolicy、Guard 整文件保持，策略/模板/类别/权限/预算未放宽。154 仅当前注册 manifest 长度，不代表全 manifest 回归。

首 run 36个、窄复验2个 aggregate child，合计38个均 exit0，两个 run 均 live child0、active listeners/retained endpoints metrics0、resources_closed=true。所有非 selfcheck 拒绝、已知 IPv6 import probe 与其他意外拒绝均0；正常 DB false、真实 Provider/receiver0。R38 备份原件不变依据各自受管 before/after 元数据；封存不打开数据库。测试共享 app/DB 的产品导入只发生在受管进程内；静审零 import 不等于测试零 app import，Python Guard 也不等于 OS/native syscall 保证。

## 封存与下一精确入口

本轮正式文件为9个既有文件变更（五生产＋runner＋三个入口）、2个新增（新 test＋本报告）、零删除。机器封存入口 `.artifacts/r89-close-0e7b9ca2d143/verification-final.json` 以实际生成及 Root 独立复算为准，不预填 seal hash。继承 R88 显式目录并另立两 run／旧 test archive／correction／S2 的绑定，不声明检查任意工作区文件。

R88 及更早报告/旧 seal、冻结合同与五个 023 fixture 保留原字节；未知 dirty 不回退。下一步继续 binary 审批/重解析/发布治理、尚未闭合的全部消费者及 V2 API/SDK/UI/Native；adapter 在线 fetch、生产首代 ready 未开放。许可 pending、`provider_use/export=false`、`requires_source_verification` 保持。PG 旧库受控迁移/活 PG、正常库保全升级、正式外部真人 Golden、专业性能 C/真实 Responses 与完整 PDF/V1 各 Gate 仍独立开放。未提交推送，不再索要 Key 或 URL。
