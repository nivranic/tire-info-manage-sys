# 专业Golden的PDF成绩与R74恢复验收

2026-11-15，基线33b2807。需求继续覆盖精确SKU、来源证据、同场成绩和人工Golden。本阶段补齐独立PDF成绩合同并恢复历史观察目录所需材料。[计划](../../plans/2026-11-15-professional-golden-pdf.md)

## 合同与正常入口

- MeasurementLiteral增加可选PDF引用，使用材料标签、冻结提取器版本、页码和码点区间。独立比较器按原件字面量摘要及正常上传绑定解析document_id、document_fingerprint和chunk_id。引用区间遵循1200码点、1080步长合同，材料需存在。
- EventLiteral保留出版物角色及依据。缺省PDF引用和出版物角色序列化时省略，7份历史案例逐字面量复验。
- 增加test_event_http模式，SKU、R71桥及候选范围显式为空。既有private_http继续要求完整桥输入，正常上传和私有环境核对由两入口共用。
- 新增真实滚阻论文的独立22成绩字面量，保留原4胎范围、选录状态、混合尺寸、PDF第4页、表2、原名次null、方法及50 km/h例外。数据与署名按出版方CC BY 4.0留存。[数据及入口](../../../packages/domain-types/fixtures/professional-test-pdf-v1/README.md)
- 数据文件SHA-256为c6a2653c02618cb2dcf61577c7adbef15832bb5c5702bc020096ba446cb3dcb4，Git按原字节保存。正常受管回归入口可上传原件、保存／读取场次，再由独立比较器核对。

纯比较结果的evaluation_mode仍为offline_bound_snapshot，当前HTTP执行由受管回归及actual.execution记录。工程验收和发布Gate均保留各自实际状态。

## R74材料恢复

原清单缺失的捕获回执和agent复核记录从历史工具回执恢复。恢复按原输出与换行格式核对，文件字节数及SHA-256完全匹配冻结清单。

| 材料 | 字节数 | SHA-256 |
| --- | --- | --- |
| capture-response.json | 5,395 | f783be6bb8a1dd10631e4e297df8104f238297db39c8e73eaa3f0cf5761547da |
| findings.json | 6,583 | 3387534e41103f9b2d4e34b92631f2e9661243a1ceacb3f8fe0bc08eca0692c8 |
| review-original.pdf | 3,302,848 | 33471a0b0d0a8c2f172b61b034a8300c65e3ff2372c79782562048133606f635 |

PDF通过新隔离库的正常来源捕获取得，固定HTTPS出版地址、robots、原件大小、类型和摘要通过现有传输检查，字节与冻结原件完全一致。沿既有70秒策略总期限捕获。三份材料恢复到清单路径后，完整9个外部文件绑定均通过。[R74出版原文](https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2023.1258922/full)

## 实际验证

| 验证 | 结果 |
| --- | --- |
| 新合同红批 | 1项失败，复现旧合同拒绝新形状 |
| 新合同与旧序列化专项 | 13项通过 |
| PDF正常HTTP及篡改专项 | 14项通过，含真实22成绩与重算摘要的反例 |
| 既有6组合成SKU桥及新模式边界 | 7项通过 |
| 完整专业Golden观察器 | 7案例完成，工程state=passed，release_gate=inconclusive |
| 观察器资源与来源绑定 | 源码稳定，网络、子进程及常规数据库尝试均0，26次内部socketpair |
| 最终6模块受管回归 | 243通过，0失败、0跳过、0不完整，869输入稳定 |
| 原54条件用例 | 按历史nodeid及计数交叉核对，54项全部执行通过 |
| 资源关闭 | 25个受管子进程全部exit 0并回收，resources_closed=true，捕获库关闭 |

观察器的真人资格保持pending_external_review。真实2017年成绩保持manual_transcription／unverified，精确SKU及真人Golden数量均为0。旧7案例清单与原始字节保持冻结，新场次字面量另有明确文件摘要。

最终批覆盖professional_golden_checks、professional_golden_bindings、professional_golden_review、professional_golden_corpus、professional_golden_cli及test_test_events六模块。原54项分布为checks 20、bindings 10、review 24。关闭核对确认9个外部绑定有效、观察器源码稳定、受管资源已关闭，真实Provider调用0。

## 范围与继续工作

数据库迁移仍为036。本阶段修改独立比较器、HTTP验收支持和字面量。实际PG部署仍按目标catalog与当前API源码生成批准合同。

真实SKU、真人Golden、真实Responses／Embeddings、EPREL、Android instrumentation／设备、Native宿主、跨设备、自然长周期监控、WCAG、生产恢复及SLO继续待验。前阶段首次6项PDF回归和浏览器409的原因继续待确认，已保留其后复跑通过的证据。

恢复的原件、回执、复核记录、隔离库和HTTP实际记录位于Git忽略目录。clone须按原摘要取得这些资料后重放对应验收。旧KIT C2沿历史封存状态处理。

用户要求完成本轮、更新交接并暂停推进。完成提交与远端核对后暂停完整目标，待用户明确接续再开展后续实施。[本轮交接](../../AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md)

## 回执索引

| 回执 | SHA-256 |
| --- | --- |
| golden-pdf-20261115-red/result.json | cb8192259eab98c3c30cec97e0a9b9a5f6db9dc569a14e3251a3ba948c7daceb |
| golden-pdf-20261115-contract/result.json | 8b1aaf3fc883e20f47a4878d3b5145615068074e81383cc58b2165333efe3127 |
| golden-pdf-20261115-http/result.json | fd621777e4db8e11206affdd23767037cdf9f36f02bb158ed164c825d62c699e |
| golden-pdf-20261115-legacy/result.json | 072fdb7d5038de01acf25f338bb8c03ee395b73e5d4aa3c9307c86bea561a58b |
| golden-pdf-20261115/r74-restoration.json | e41e6af7d7f51bff4c8c02e4d824a525b7139227c4afc4116a051473ce314c2a |
| r74-original-recovery-20261115/result.json | 2370df9f5db492d1802f331b5064f8bc37b59bac73c26955098916cdd8d985b1 |
| r76-http-golden-pdf-20261115/report.json | aa5f8e15687017a11d4d12c9bbb2addd4cc56a4acf228ea821d1e892ce5c8ca0 |
| r76-http-golden-pdf-20261115/execution-receipt.json | 4aa654662351657d534f2358a33adf52f30d95ddd9ab1f1cc9b6e6d4abf48b47 |
| golden-pdf-20261115-final/result.json | fd8fa5ad138cb66b8b3aec64ea6072dad8d778b86d488b1fb06a347bc0bf2789 |
| golden-pdf-20261115/formerly-skipped.json | 6d5c17d3fae5bce3990e7624927aa5e8b6b487420db6401bc3d56254e2dddddb |
| golden-pdf-20261115/resource-audit.json | 9f12d161b74ee6469279b326b5e81ffb39a4bf4e0d44f390737feee0f58e5f2d |
