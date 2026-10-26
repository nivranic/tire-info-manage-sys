# 第86轮 车型原件与冻结映射身份helper

日期：2026-10-19。**统一车型原件读取、服务端parse_provenance构建/核验及内部V2字段构建的helper切片已实现并验证。**仅新增`vehicle_raw.py`，尚未接入生产capture、PDF child/bundle派发、车型写入、审批、消费者或HTTP路由；内部metadata生成的content_path不表示对应内容路由已交付。首代fetch/ready仍未开放，完整PDF及V1 Gate保持开放。

沿用[冻结合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)§2.3/§2.4与[第85轮SQLite切片](round-85-vehicle-binary-024-migration.md)。本轮没有重跑R85迁移套件、连接正常数据库或执行PG迁移。完整性helper不授予来源用途许可，也不替代调用方的授权和新事实采纳锁。

## 实际运行与证据资格

唯一受管运行：`.artifacts/r86-t-5c047a8eb192/result.json`，20190B/SHA256 `853b765eb672098a73a241b97738d6748749131f3c488f9096c8a28190984373`。pytest/runner均exit0，115唯一条目全部通过，0失败/跳过/incomplete；setup/call/teardown各115通过。独立静审及指定venv隔离AST先通过，随后才运行测试。

| 实际目标模块 | 通过 |
| --- | ---: |
| `test_vehicle_raw.py` | 51 |
| `test_raw_captures.py` | 15 |
| `test_vehicles.py` | 29 |
| `test_vehicle_pdf.py` | 20 |

**115仅为上述四模块，151只是runner注册manifest长度，没有运行全151。**R85的分批313项不与本轮115相加为当前唯一全套结果。Root已独立核本run、safe reports三阶段计数和675个输入逐项live大小/SHA一致。

真实S2历史原件只从已指定R81路径读取，先核3240150B/SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，再写入本run私有ObjectStore及私库。测试执行者与Root事后只hash复核原件仍同pin，所有S2用例实际执行且无skip。原件不是Git fixture，也不是本轮新在线响应。

测试使用真实私有bundle封存/登记与真实ObjectStore；完成receipt由私库测试构造，并通过现有`record_execution`登记。**这些是合成completed receipt，不能证明真实PDF child执行、线上采集或正式事实采纳。**既有映射源码未经替换封存的正例使用独立revision2；另有仅含四个literal及顶层raise的合成归档映射，用于证明helper只读AST、不导入执行归档源码。同SHA的@1/@2反例不表示生产已发布第二映射。

## helper已核行为

五个入口为`checked_vehicle_bytes`、`checked_vehicle_capture`、`build_vehicle_parse_provenance`、`checked_vehicle_parse_provenance`和`vehicle_raw_metadata`。它们以no_autoflush保护读取，不提交、不修复历史、不查询当前部署；对外只抛固定`vehicle_raw_integrity_failed`，不转出原始路径或异常。

- UTF-8旧Snapshot/Quarantine没有capture引用时，严格编码旧body并核hash，不补造capture/Verification或映射身份；有引用则核原QueryRun与两行元数据/字节。legacy capture仅在没有对象引用时保留原DB读取路径；已有对象引用缺失/错映射/错长度/同长度损坏均失败，不回退DB。UTF-8旧Rejected没有capture时仍核自身原文及精确QueryRun；binary Rejected必须与同query capture一致。
- Binary capture核固定source/vehicle/URL/MIME、精确QueryRun及query_key、原ParserSelection/version/三键identity和完整对象链。允许有基础PDF签名的合法未知修订读取metadata，parse_method/mapping_id为空；不以支持SHA或已完成Execution作为capture读取条件，也不把失败原件提升为accepted。
- Binary Snapshot/Quarantine额外要求S2原件、原Selection/DeploymentRevision/登记bundle、completed receipt、input_hash及Execution fingerprint一致，quarantine还绑定自己的query。parser_digest按原manifest计算；execution_digest绑定原Selection与receipt，registry/deployment只比五个稳定来源字段，合法历史host变化不会因整descriptor强等被误拒。
- 已登记manifest及实际存储tree经`verify_bundle`核验，再有界读取原bundle的mapping文件，仅AST提取四个literal。六键parse_provenance来自该原bundle，校验原件SHA、映射文件SHA及payload车型/source_version/method/mapping；不读当前工作区mapping常量补身份、不调用`record_execution`写历史、不调用当前Parser或current_deployment。
- 构建器拒绝调用方预塞的provenance、错车型/来源版本、错声明/selection/receipt和缺执行记录；reader拒绝六键缺失/多键/错身份。已验证同原件不同mapping各自保留原bundle，旧bundle缺失/被改即失败，payload及调用方对象不被helper重写；fact hash和既有vehicle_provenance键集合保持。

内部metadata只支持Snapshot、VehicleQuarantine、RawCapture、RejectedObservation四类车型记录；生成闭合字段，binary body为null，ID拒绝路径段等非法形状。它没有注册V2/下载路由，也没有改旧客户端协商。`quarantine_review.binding/context/consume_approval`与`VehicleService.persist`仍是旧文本链，binary审批、重解析/发布完成指纹和生产写入接线继续待实现，不能据本轮helper宣布审批可用。

## 当前绑定与运行边界

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| `apps/api/tire_api/vehicle_raw.py` | 19126 | `bdd9495d04a84dc6c3ccbbe1ab149be284a6c97de2505957ff12f009729821bf` |
| `apps/api/tests/test_vehicle_raw.py` | 32393 | `fdcc9c06a2da85cea82bbb8e0ad764436c6a8f304e7c8d208b5da1b8c7dfa92d` |
| `scripts/run_api_worker_regression.py` | 42360 | `62de8c7817b65281f1827caf755d02b27f77f692d9d2b6a89bd66928c8686971` |

Runner只新增一个模块登记及两处计数/帮助文案；内存逆回三处精确恢复R85 runner SHA256 `ffed48b2fa282f5a370af28478cb64bab82ad5e80cd1a2b236319bd2a6412ee3`。相对R85显式输入，本轮仅4既有改变（runner及三个文档顶部）、3新增（helper、测试、本报告）、零删除；旧1898个checked文件中1894保持原字节，inventory从1129到1132。R85及更早报告/seal、冻结合同、五个023静态fixture、Guard和ChildPolicy不改。

本run675输入首尾稳定；报告失败和非selfcheck拒绝均0，资源关闭，四个受管child均退出/live0。exit73/61属于既有capture崩溃与Parser probe故障用例，另两个受管Parser exit0；它们不构成PDF child验收。R38原件前后均25374720B/SHA256 `a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4`。normal_database_started=false、real_provider_or_receiver_calls=0；Python Guard不声明OS/native syscall保证。

## 下一精确入口

helper切片不重做。继续冻结合同的真实capture可信context、PDF child/bundle固定派发与版本、捕获先提交、车型写入及冻结provenance接线，再接binary质量/审批/重解析/发布与全部消费者、V2 API/SDK/UI/Native。内容端点、用途授权和reader接线完成前，metadata内的未来路径不作为已开放能力。

首代仍`requires_source_verification`，许可pending、`provider_use/export=false`、fetch/ready未开放。PG旧库受控迁移/活PG、正常库保全与升级、真实专业精确SKU/外部真人Golden、完整专业性能C/真实Responses及完整V1各Gate独立继续。正常库、实网、Provider/receiver本轮未新调用，未提交推送；不再索要EPREL Key或URL。
