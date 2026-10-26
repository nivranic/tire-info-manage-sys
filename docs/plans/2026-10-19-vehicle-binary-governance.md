# 车辆 PDF 二进制治理闭环实施卡（R90）

日期：2026-10-19。状态：设计已收口；本卡提交 Root 冻结，实际源码与测试仍待统一实施 Gate。本轮实施授权来源为用户的持续 goal；本卡不扩大该授权范围。编写本卡期间未运行产品 import、pytest、collection、数据库、Provider、receiver 或真实网络。

本卡承接 [原 PDF 冻结合同](2026-10-19-official-vehicle-pdf-contract.md)，不修改该合同，不重写 R89 运行、报告或封存历史。当前只补齐二进制质量审批与历史重解析／发布治理；审批决定、历史候选和发布评估均不直接写入在线正式事实。

## 方案与范围

| 方案 | 具体做法 | 取舍 |
| --- | --- | --- |
| A：各入口独立实现 | 新建 binary 审批路由，并在重解析、发布、Golden 各复制原件与 mapping 核验 | 路由与完整性规则重复，旧文本兼容和安全门容易漂移；不采用 |
| B：显式协商与共同历史核验 | 复用 review 路由，新增闭合 binary DTO／binding；历史入口共用独立 reader／builder，保留在线 helper 语义 | 不需要迁移，范围可审查；采用 |
| C：先做完整 V2 产品面 | 同步交付正文下载、SDK、UI、Native 和新治理表 | 混入内容权限与客户端改造，当前没有必要收益；延后独立规划 |

六个生产文件与两个新测试按下表分工。参与者共享工作区，不回退其他人的 dirty 修改，不跨 ownership 写文件；原文件副本直接使用已核 [R90 基线清单](../../.artifacts/r90-baseline-4c71d9e50b62/baseline.json)。

| 负责人 | 文件 | 本轮责任 |
| --- | --- | --- |
| 审批 worker | `apps/api/tire_api/quarantine_review.py` | 闭合 DTO、显式分派、binary context／binding／一次消费、共用状态格式化 |
| 审批 worker | `apps/api/tire_api/vehicles.py` | 仅接入已核新观察的 binary loss 消费；保留锁、source／selection fence 和事务 |
| 审批 worker | `apps/api/tests/test_vehicle_binary_approval.py`（新增） | 质量审批、一次消费、并发和真实下游失败回滚 |
| 历史 worker | `apps/api/tire_api/vehicle_raw.py` | 独立历史 reader／builder，共用 sealed mapping 核验 primitive |
| 历史 worker | `apps/api/tire_api/reparse.py` | binary input、显式 bundle、reserve 后再核原件、候选 provenance 与基线校验 |
| 历史 worker | `apps/api/tire_api/parser_releases.py` | 原件／reference／各 arm provenance、control 不支持的 hard block |
| 历史 worker | `apps/api/tire_api/golden.py` | `_capture` 共同历史原件门的必要闭包；保留 required gate |
| 历史 worker | `apps/api/tests/test_vehicle_binary_reparse.py`（新增） | 历史执行、Golden／release 正反门与旧指纹兼容 |
| seal worker | 现有受管 runner 的精确模块登记与 metadata | 独立审查、Root Gate 后的唯一受管运行和封存；不改 Guard／ChildPolicy／预算 |

不改 models、DB／迁移、quality 算法、runtime／child／bundles、`golden_checks.py`、原 PDF 合同或 R89 测试。七文件基线包含六生产与 runner；新测试先确认不存在再创建。

## 二进制质量审批合同

### 协商和闭合 DTO

GET `/v1/quarantines/{id}/review?mode=history&format=raw-evidence-v2`；POST `/v1/quarantines/{id}/reviews?mode=history&format=raw-evidence-v2`。保持 admin guard 和 POST 201。binary 候选为 `body_encoding == 'binary'`，或固定 `source_id == SOURCE_ID and vehicle_id == FIRST_GENERATION_ID`；固定首代伪降 UTF8 必须进入完整性门。

binary 无 format 仍返回 409 `binary_evidence_format_required`；格式、body、目标分支或必需 mode 错配返回 422。POST 的 mode 仅为兼容旧文本可在参数层 optional，binary V2 必须显式 history。普通文本无 format 的请求、响应、binding、hash 和错误合同不变。RejectedObservation 不进入质量批准。

新 BinaryReviewRequest 为原五键 `action/expected_revision/operator/reason/confirmed_loss` 加 required `expected_binding_hash`（64hex）。两个请求模型独立且 `extra=forbid`，由服务端目标与协商显式分派；不接收 caller raw、capture、payload、mapping 或 provenance。

binary 响应保留原十二键：`quarantine_id/scope/state/revision/can_approve/restriction/baseline_snapshot_id/current_snapshot_id/applied_query_id/comparison/history/history_truncated`；恰新增 `evidence_format='raw-evidence-v2'`、`binding_contract='vehicle-binary@1'`、`binding_hash`、`raw_evidence`。

review 专用 `raw_evidence` 恰十键：`body_encoding='binary'`、`body=null`、`raw_capture_id`、`raw_hash`、`byte_count`、`content_type='application/pdf'`、`source_url`、`parser_version`、原三键 `parser_identity`、原六键 `parse_provenance`。不返回正文、content_path、base64 或本机路径，不增加下载路由；它不代表主 evidence V2／content 已交付。comparison 保持 before／candidate 语义。

### 原 Q、基线和 binding

保留 legacy context 五元组，新增具名 BinaryReviewContext。提取共用的 state／history／revision formatter，不能复制整份 legacy 状态实现；状态优先序、can_approve、24h TTL、latest revision 和过期后显式新 review 的政策不变。

binary context 按顺序核验：

1. 原 Q／QueryRun 的 source、query、query_key、vehicle、previous_snapshot 对应；仅加载该原件链，不从其他 capture 补证据。
2. 通过现有在线 checked helper 核真实 bytes、对象、capture、原 completed receipt、原 bundle 与原六键 provenance。完整性失败固定抛 VehicleRawIntegrityError，不降格为可批准的 field loss。
3. 原 Q payload 必须执行与 R89 `_execute` 同等的 WheelFitmentSpecification、`validate_vehicle_structure`、重复 fitment／trim 引用校验；`_payload_identity` 和质量评估不能代替 schema 校验。只核验，不回写原 Q。
4. 基线须存在正式 VehicleVerification，并实际联 QueryRun 核 source／query／query_key／vehicle 对应；验证原件链及 `fitment_fact_hash(payload) == snapshot.fact_hash`。binary／固定首代候选始终走相同完整性门，不能只数一条 Verification。
5. 使用原 `assess_vehicle_quality`／restriction 重算，要求与 stored quality 精确一致，仅 field_loss_threshold／row_loss_threshold 可批。当前 snapshot ID 与原 baseline 不同仍 stale_baseline，不用相同事实 hash 偷换基线。

新 binary binding 恰十五键：

```text
binding_contract='vehicle-binary@1', target='vehicle',
source, query_key, baseline, raw_hash, url, parser, content_type,
payload, quality, parser_identity, body_encoding='binary', byte_count, mapping_id
```

mapping_id 来自已核冻结块；payload 中原六键 provenance 自然绑定 bundle／mapping SHA。禁止读当前源码常量补旧身份。capture ID、QueryRun ID、receipt run_id、时间、source generation 不进入可复用 binding。source generation 仅保留新 QueryRun 的原在途 fence；不新增历史 approval 过期政策。Parser A→B→A 由 deployment_revision 自然不匹配。

### POST 和一次消费

POST 在原 ingestion 锁内重建 context，核 expected binding／revision，只 append review／audit；不 fetch、parse、采纳或消费。保留共享 binding 的 latest revision：新的 keep_quarantined 可撤销同 binding 的待用批准。

后续新在线观察保留现有锁、source／selection fence、独立 durable capture 和 actual completed child；已核新 provenance capsule 传给 binary consumer，不能将含 server provenance 的 payload 再传给禁止预带块的在线 builder。

consumer 核 approve／24h TTL／unused／`newrun.created_at > review.created_at`，并重新加载 `event.quarantine_id` 的原 Q，执行上述全套 context。要求原 Q key、event key、新 key 三者一致，baseline ID 一致，原／新 capture 不同，new capture.query_id 为新 QueryRun，真实 bytes 相同。不能只对新 payload hash 命中就消费。

append ApprovalUse／audit 后不 commit、不取第二把锁。use 与 Snapshot／Verification／Fitment／InterestEvent／Notification 同一事务；下游失败整体 rollback，已独立持久化的 capture／completed execution 保留。无可用批准继续隔离，完整性异常不可吞掉。review_id 主键、query_id UNIQUE 和现锁兜并发。

## 历史重解析与发布合同

新增 `checked_vehicle_history_capture_bytes(db, cap)`，只核合法原件链，不要求原 ParserExecution completed；unknown PDF、原 child failed 或无 accepted snapshot 不自动失去历史输入资格。现 online helper 的成功／失败语义不变，binary authoritative object 不从 retained DB 补过。

新增 `build_vehicle_history_parse_provenance(db, *, source_input, raw, payload, bundle_manifest, receipt, deployment_revision)`。核已登记 target manifest／完整 sealed tree、实际 target receipt、完整 input_hash／身份／run_id／exit／reaped，再复用共同 mapping AST primitive 构造目标六键。caller／child 预带 provenance 拒绝；不把当前工作区 mapping 补给旧观察。

binary 新 reparse 必须显式 bundle_id，缺失在 reserve／child 前返回 422 `binary_reparse_bundle_required`。binary source_input 在旧原观察键集上只加 `body_encoding='binary'` 与固定 `original_mapping_status='not_attested'`；后者仅表示本 input 未附原 mapping 成功证明，不推断原 child 是否执行或成功。目标六键仅进入各自 candidate／completion，不进入原 input；control／candidate 同 raw，分别绑定自身 manifest／receipt。

reserve commit 后重新读取原件并逐项匹配 frozen input 的 encoding／source／query／URL／MIME／hash／count／原 parser 身份，不能让 identity map 的旧对象掩盖间隙改件。latest_baseline／reference 返回 binary 或固定首代候选前重核 helper、正式事实关联和 fact_hash；不修补旧 payload。

旧 control 不支持 PDF 必须保留真实 failed receipt、能力缺口和不可 acknowledge 豁免的 binary hard_block；已有 accepted reference 不能绕过。unknown／candidate failed 同样 block。正向 release 使用均支持 raw 的 control／target，并完整通过 required Golden、review、revision；私有合成 Golden 仅证明工程正向门，不称外部真人或生产 Golden。

Golden `_capture` 接共同 reader；事实 projection 仍仅 vehicle／trims／fitments。保留 case／review／set、completion 与 release 原指纹算法和 required gate，不以弱 receipt_matches 代替 target provenance／sealed manifest 核验。source_input 与 target 无关，Golden input 等值不因换目标 bundle 天然失败。

普通 UTF8 不加默认 encoding／mapping 键，不在 read／list／replay 时补块或重建旧 completion。不改旧 request_hash、completion_binding、evaluation input／completion hash、Golden content／review／set hash 算法；新增 binary 字段自然进入原 digest。

## 实施顺序、验收与回退

1. Root 冻结本卡和已独立核过的七文件 baseline 后，统一发实现 Gate；审批／历史 worker 在上述独占文件并行。当前阶段源码与测试均未执行。
2. 各 worker 完成静态核对和精确 diff，双方独立 cross-review；审批重点原 Q schema／正式基线／once／rollback，历史重点 manifest／receipt／unknown／control hard block／required Golden／旧 hash。
3. seal worker 登记两个精确新模块，独立审查 runner，Root Gate 后唯一受管验证；禁止裸 pytest、先 collection 或额外产品 import 实验。失败只在 Root 批准的窄修复后定向复验，首红与复验分开保留。
4. 文档与 metadata 以实际结果收口；未实际运行不能声称通过。回退仅按本轮基线精确撤销本轮改动，不 reset／clean／stash，不覆盖其他 dirty；测试私有库及对象不接正常库。

| 验收组 | 必须观察到的行为 |
| --- | --- |
| 审批协议 | 旧 binary 无协商 409，错配 422，闭合键集、body null、无正文／路径；旧文本合同原样 |
| 审批与消费 | POST 仅决定；新 QueryRun／新 capture／actual child 一次采纳；原 Q 原字节不变；在途旧 query／重复 use 拒绝 |
| 原件和结构 | 原 Q／新链对象、同长损坏、receipt、provenance、encoding 降级、重复 fitment／trim 引用、错误正式基线均完整性失败 |
| 时序与事务 | TTL／latest keep／共享 revision／错误 hash／ABA／并发正确；实际 Notification INSERT 失败时 use 和领域写一起回滚，capture／execution 保留 |
| 历史执行 | binary 必须 bundle；unknown／原 failed 无 snapshot 仍可实际尝试；reserve 后再核；候选六键属所选 bundle；正式事实表不增 |
| 发布与 Golden | 不支持 PDF 的 control 不可豁免；支持双方＋有效私有 Golden 的工程正向可达；missing／revoked／stale／mismatch Golden 阻断 |
| 兼容 | 修改前冻结的旧 UTF8 input／parser／baseline／completion／Golden／release 指纹与修改后精确一致；不只验证新算法自洽 |

真实 S2 fixture 每次先硬核 3240150 bytes／SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，缺失或不匹配直接失败，无 skip。使用私有 file SQLite 与真实 isolated child；合成私有 bundle／Golden 明确标注，不提升为生产发布证明。

预计回归由 Root 合并去重后交 seal worker：`test_quarantine_review.py`、`test_vehicle_binary_ingestion.py`、`test_vehicles.py`、`test_vehicle_quality.py`、实际 interest 相关目标；历史侧 `test_reparse.py`、`test_parser_releases.py`、`test_golden.py`、`test_golden_checks.py`、`test_golden_release_gate.py`、`test_vehicle_raw.py`、`test_vehicle_pdf_runtime.py`，必要 recall 兼容由实际 diff 决定。目标清单不是运行记录。

## 证据与未覆盖边界

设计输入为 [审批只读设计](../../.artifacts/r90-approval-15ce7f8ba168/design.md)、[历史只读设计](../../.artifacts/r90-history-design-c7efed4a1138/review.md) 与 [Root 字段裁决](../../.artifacts/r90-history-design-c7efed4a1138/root-decision.md)。Root 后续明确的原 Q schema／正式 Verification 联 QueryRun 要求已在本卡合并；原设计 artifact 保留原字节。

本卡不关闭正常数据库／PostgreSQL、生产采集／ready、实网 Provider／receiver、全部消费者、完整 V1、用途许可、主 V2 正文下载／SDK／UI／Native、专业事实与外部真人 Golden 验收。质量损失确认不授予下载、外发或再分发许可。
