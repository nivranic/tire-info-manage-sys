# 第90轮 车型二进制审批、历史重解析与 Parser 发布治理

日期：2026-10-19。**binary 质量审批、历史重解析与 Parser 发布/Golden 治理切片已实现；唯一受管运行381个唯一目标全部通过。**新增审批29项、历史重解析21项均实际通过，无复跑或阶段累计。

本轮承接[第89轮写入与有限消费者闭包](round-89-vehicle-binary-ingestion.md)，依据[冻结R90设计](../../plans/2026-10-19-vehicle-binary-governance.md)和[原PDF合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)。范围为 VehicleQuarantine 独立 binary 审批、后续实际观察的一次性消费，以及历史 candidate、release control/candidate 与必要 Golden reader 闭包；不是全部消费者、V2原件HTTP/SDK/UI/Native或完整PDF/V1交付。

真实历史S2仅在私有SQLite/ObjectStore离线重放，经actual child和returned receipt。私有adapter ready、mapping/deployment/directory、Golden签名均为合成授权fixture，不代表新在线capture、首代生产ready、正式release或外部真人Golden资格。正常库未连接启动，真实Provider/receiver调用0；数据库InterestEvent/InterestNotification和INSERT原子性不称外部推送验收。

## 唯一受管运行与实际分账

Root已独立核实际result、安全reports/JUnit、三阶段、680输入首尾/live pins及显式S2采样。唯一run为`.artifacts/r90-t-3e8a1c7b6904/result.json`，21899B / SHA256 `e5878c4784cc7157c5d0e41c6a95d270ef1e20e9ffd0449be3058090cc4e9451`；自然终态PASS，runner0、pytest0。实际collected/protocol/executed/unique均381，JUnit同为381；setup/call/teardown各381通过，0fail/skip/incomplete，subtest为0。381只计唯一测试目标，不能把三个测试阶段相加为1143项。

| 实际模块 | 本run范围 | call通过 |
| --- | --- | ---: |
| `test_golden.py` | 整模块 | 20 |
| `test_golden_checks.py` | 整模块 | 60 |
| `test_golden_release_gate.py` | 整模块 | 15 |
| `test_interest_events.py` | vehicle axle/size 精确目标 | 1 |
| `test_interest_review.py` | reviewed chain/通知回滚两精确目标 | 2 |
| `test_parser_releases.py` | 整模块 | 12 |
| `test_quarantine_review.py` | 整模块 | 19 |
| `test_recall_parser_releases.py` | 整模块 | 16 |
| `test_recall_reparse.py` | 整模块 | 39 |
| `test_reparse.py` | 整模块 | 34 |
| `test_vehicle_binary_approval.py` | 整模块 | 29 |
| `test_vehicle_binary_ingestion.py` | 整模块 | 21 |
| `test_vehicle_binary_reparse.py` | 整模块 | 21 |
| `test_vehicle_quality.py` | 整模块 | 12 |
| `test_vehicle_raw.py` | 整模块 | 51 |
| `test_vehicles.py` | 整模块 | 29 |

实际为14个整模块＋3个精确目标＝17个target条目、16个模块。**156仅当前注册manifest长度，未运行全156。**新审批29＋新历史21＝50个新增目标，其余331为本run既有回归；R89的118或更早结果不累加为本轮覆盖。

680个源码输入before/after相同，Root对每项重新hash确认与live一致。相对R89的678个旧输入，精确为7变更、671不变，另增2个测试、零移除；7变更为六生产＋runner。文档和显式S2采样不属于680源码清单，正式文档增量另由新seal绑定。

## binary质量审批与实际观察消费

- binary VehicleQuarantine GET/POST须显式`format=raw-evidence-v2`与`mode=history`，独立请求/响应模型保持`extra=forbid`。无format的binary仍固定409 `binary_evidence_format_required`；协商、body或目标错配422。新POST必须带64hex `expected_binding_hash`，不接收caller raw、capture、payload、mapping或provenance；旧UTF8合同保持。
- `vehicle-binary@1` binding精确15键，绑定source/query、正式baseline、事实/候选解析身份，排除capture/time。响应只在原十二键上加evidence format、binding contract、binding hash、raw evidence；不改原文本binding/hash或向旧历史补字段。
- 审批GET/POST只记元数据，不执行child、不立即采纳事实。binary与原review共享revision/TTL/latest keep/once状态，过期不自动续期；消费须是审批后创建的新QueryRun和新capture。已在途run、原quarantine capture、变更mapping/parser身份及ABA不能借旧批准消费。
- review与消费都重核原quarantine的原件/对象、completed execution/receipt、schema、quality和六键provenance；正式baseline再核fact hash、VehicleVerification的精确QueryRun/Selection及descriptor bundle身份。合法存储CHECK允许的encoding降级、同长原件破坏、对象损坏和冻结身份破坏均失败关闭，不能只比较新raw hash。
- 消费复用既有ingestion lock，无第二锁或consumer commit；approval use与正式snapshot/verification、InterestEvent/InterestNotification同一事务。实际并发审批/查询的一次性消费、source/selection fence，以及真实通知INSERT失败使use和域写入整体回滚，均在本run中通过。独立capture/execution journal保持其原事务边界。

## 历史candidate与release/Golden闭包

合法binary capture可尝试历史child，不以原execution失败或无accepted snapshot作为原件资格拒绝。reader仍fresh重核capture、query/selection、object、byte/hash及可信context；未知PDF的原failed child和历史failed child均保留真实receipt。当前目标仍S2-only，允许尝试不等于unknown成功。

新binary reparse必须显式registered bundle，缺失在reserve/child前422 `binary_reparse_bundle_required`。`source_input`仅在旧键集上加`body_encoding='binary'`与`original_mapping_status='not_attested'`；后者精确表示该input未附原mapping成功证明，不能推断原child是否执行或成功，不放目标mapping或空mapping_id。目标六键`parse_provenance`只在actual child成功后，由所选registered manifest、actual receipt与sealed mapping服务端构建，进入各candidate及原completion fingerprint；追加后继续检查最终candidate预算。

reserve后重新核frozen capture，missing capture固定503 `capture_integrity_failed`。binary baseline完整核schema、fitment重复/trim引用/fact hash及正式Verification/QueryRun/Selection；release reference精确Verification缺失时固定503，禁止借helper默认fallback改关联另一QueryRun。旧UTF8 input/parser/baseline不加defaults，旧记录read/list/replay不补provenance。

release的control/candidate同raw但各绑定自身包/receipt/mapping。旧1.0.1即使包含mapping文件仍真实control失败，保留failed receipt、实际`control_capability_gap`，并加不可acknowledge的`binary_control_failed` hard block；accepted_same_raw reference和Golden都不能豁免。required Golden、review/deployment revision和CAS原门保持。`golden.py`只替换capture reader；`golden_checks.py`仍只投影vehicle/trims/fitments比较事实，目标provenance不进入事实比较。

新21项实际覆盖S2 history/review仅候选且正式计数不变、未知原failed/无snapshot尝试、mapping A→B候选身份变而旧snapshot/input不回写、缺bundle、baseline/原件/receipt/caller provenance/最终预算、missing frozen capture和精确reference缺失。合成私有Golden正向review/activate Gate可达，missing/mismatch/revoked及旧control失败不可ack豁免，均已实际通过。

## 旧算法、事务与静态证据边界

双方互审和标准库AST/diff/hash核验绑定最终六生产与两新测试。历史owner25个既有函数、审批owner6个既有函数，共31个旧函数源码逐字节保持，原状态formatter body另有保真证据；包括旧input/completion、evaluation/Golden hash/review、原件和文本审批关键函数。固定legacy vectors的测试在本run通过，预期值来自pre-R90键集和canonical JSON算法，**不是改动前实际运行回执，不称pre/post runtime等价验证。**

已实核`db.py:508`使用`sessionmaker(expire_on_commit=False)`；旧reparse commit后访问`capture.source_id`不是已证实的隐式重开事务缺陷。binary改用frozen source原语用于固定执行身份。release新增attestation读库则使用每arm独立、绑定Engine并复制db.info的Session，关闭自身只读事务，避免parent读事务跨下一child，不新增caller commit/rollback。实际S2 reparse与双arm release测试已在child前断言parent无active transaction、pool checkedout为0并通过。

| 静态/互审回执 | bytes | SHA256 |
| --- | ---: | --- |
| `.artifacts/r90-history-impl-2939f51baf8c/static-final-verification.json` | 5944 | `76e398c616823b9d4577a078d2a4a0e36ad155e41cc3992761bbecd45eb5d765` |
| `.artifacts/r90-approval-final-120c4c87eaf1/verification-static.json` | 3923 | `ded2084c47f244ec1ffc2f5adf9efa26492692feab07173757da0361aef0549e` |
| `.artifacts/r90-approval-final-120c4c87eaf1/history-cross-review-final.json` | 6424 | `e1d3b55423ba2bf1ea1ecb32187a801fdfa3d7de77cd59a5ca4f6025dc7a3eea` |
| `.artifacts/r90-history-impl-2939f51baf8c/approval-cross-review-final.json` | 1911 | `5c46881632a8af295bcb0b2de99df7778acc7231955af0182f4461d981cb258c` |

静审本身零产品import、pytest或SQL；本轮测试的产品导入和私库运行仅发生在受管进程内，不能把静审零import扩成测试零app import。

## S2资格与运行边界

历史S2为3240150B / SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`。每次pre-use核大小/SHA，actual child/receipt已受测；旧raw/helper中的合成completed receipt反例仍只证明冻结身份校验，不把所有旧例称为真实执行。

| 显式metadata回执 | sampled UTC | receipt bytes / SHA256 |
| --- | --- | --- |
| `.artifacts/r90-meta-3e8a1c7b6904/s2-before.json` | `2026-10-19T04:52:27.495386Z` | 294 / `6ba98a257752e1a79f7137eac3cda049682c1d1f10a522fb80cf1c3106c56e9e` |
| `.artifacts/r90-meta-3e8a1c7b6904/s2-after.json` | `2026-10-19T05:38:18.318982Z` | 294 / `d952adc6dfd72d0376c1dc74ad5216c2cf82947d6c999d14cc9f16ac51155477` |

两份显式采样包围actual run，均为同一历史S2；Root另重新hash原件。显式before/after、每次pre-use核和680源码稳定是独立证据，不混称一次清单观测。

本run240个aggregate managed-parser child均exit0，live child0、资源关闭，active listeners/retained endpoints metrics0。预期selfcheck拒绝单列通过；所有非selfcheck拒绝、已知IPv6 import probe与其他意外拒绝均0，正常DB false，真实Provider/receiver0。R38备份before/after metadata相同；本轮只核metadata，不打开历史备份。Python Guard不等于OS/native syscall保证；合成fixture授权不提升生产来源用途许可。

## 正式文件与封存入口

| 当前文件 | bytes | SHA256 |
| --- | ---: | --- |
| `apps/api/tire_api/vehicles.py` | 33642 | `3fab18dcd85378b406439bbe286ee302042871f3c30df65b0cf25fbf1b4af417` |
| `apps/api/tire_api/quarantine_review.py` | 24201 | `126f40037f4bf627a0b59c68dbe88a3c1a8cbf141b82d39b6c28f9a526bd83b7` |
| `apps/api/tire_api/vehicle_raw.py` | 26729 | `e49664b83fe307c13fe9c11a8d8f1f28748b2ca0947c34dbe0c250f131a787d7` |
| `apps/api/tire_api/reparse.py` | 31889 | `e3ece9b3c202b8b3e4ea9996cbb0d2a741f91193ebd2dd4ae4af038248cb9087` |
| `apps/api/tire_api/parser_releases.py` | 52529 | `ee31654bd8fdb34f279be8c7b839f8635ef8370577bad2206c0637347d1d062c` |
| `apps/api/tire_api/golden.py` | 31291 | `3bb0f7a48234c883250136cfb1479ca523dc3931f3055985bfefc0822c4f3753` |
| `apps/api/tests/test_vehicle_binary_approval.py` | 27981 | `bfe1e1acae0a2013ed51e2b503e68243ec1c6476d3b17be73c917df118372e84` |
| `apps/api/tests/test_vehicle_binary_reparse.py` | 27766 | `8d4bea85844d7383b1204b6dab93ec25d21ba855f2af19cdd13f3401044d2492` |
| `scripts/run_api_worker_regression.py` | 42626 | `d8e74c7e6ba3f95fdcce9d3796d95d1d7d6cfbe7eea61c01ede1f80767e48339` |
| `scripts/regression_children.py` | 27470 | `c45982002e0c289529b03a371ce5b7696666d4239b82323d6e35b5837b7a4f7d` |
| `scripts/regression_guard.py` | 26536 | `23f34b2e58bd5fdc200e6c812df43632c96b1fff5d538ff307ef84cf9b592629` |

runner只登记两新module及相应manifest计数，ChildPolicy/Guard整文件保持原字节，未放宽类别、策略、权限或预算。相对R89的正式变更还包括三入口、新报告及冻结R90设计卡，新增卡不能漏计；完整增变清单以新机器seal为准。

唯一新封存入口为`.artifacts/r90-close-6f2a9b40c783/verification-final.json`，以实际生成和Root独立复核为准，此处不预填seal hash。R89及更早报告/旧seal、冻结R90设计、原PDF合同和五023fixture保持原字节；未知dirty不回退。未提交或推送。

## 下一精确入口与仍开放Gate

本轮另有只读consumer地图：`.artifacts/r90-next-consumers-596bc2e731d4/investigation.md`，13191B / SHA256 `def3b6efb9694767e0e36834f64ec8ea34026ff69185a296cdac4177727fcf51`；绑定`.artifacts/r90-next-consumers-596bc2e731d4/source-pins-and-boundary.json`，25096B / SHA256 `42bbe819bc709b1124fb5001fcfa2b863fd89ab3fa05fbd65b316fb097bf7550`。仅静态读7指定文件＋6个必要直接consumer，未实施、未运行测试/HTTP/Provider，不称全消费者清单。

下一最小slice优先闭合`fitment_relations`所选accepted snapshot、列表/详情/preview/revision、current head/staleness的原件门：当前`verify_raw/accepted_vehicle`对合法binary body=None走encode异常在静态可达，不等于已实测HTTP500。`ai_evidence.prepare_pack`的vehicle路径仍直接复制payload；`ai_analysis.prepare_analysis`及普通`reserve_response`缺vehicle原件重核，`reports.freeze_body`仅对recall重载。新包/分析/报告/导出及旧冻结产物的新消费须明确失败关闭，generic `allow_external_processing`不能替代来源`provider_use/export_or_redistribution=false`。旧完成产物保持只读原字节；不把结构化用途缺门称为已证实PDF全文外泄。

通常不必为车辆binary修改`interest_applicability`的轮胎原文检查、纯冻结JSON matcher或报告renderer；若需要统一accepted只读capsule，另审`vehicle_raw`最小依赖。地图未完成全AI stream、Device/offline/garage/SDK/Native/UI闭包，不扩冻结source八键或生产用途授权。

生产adapter在线fetch、首代ready、V2原件HTTP/SDK/UI/Native及全部消费者仍未验收；许可pending、provider_use/export=false、requires_source_verification保持。PG旧库受控迁移/活PG、正常库保全升级、正式外部真人Golden、专业性能C/真实Responses、完整PDF与完整V1各Gate继续开放，原Goal继续active。无需重做本轮切片或再索要Key/URL。
