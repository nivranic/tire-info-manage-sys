# 首代 SU7 官方 PDF 可执行合同

日期：2026-10-19。状态：**待实现合同，不是功能、迁移或上线验收回执**。本文细化同日《首代 SU7 官方 PDF 接入与当前集成回归计划》的 Phase 2，并冻结 Phase 3–5 必须共同满足的存储、读取和验收接口。

本次只新增本文和独立阅读证据目录。正在运行的 148 模块回归要求代码冻结：本合同不授权在该运行结束前修改生产、测试、scripts 或包配置；不执行迁移、正常数据库、Provider、网络或测试。完整 V1、真实专业精确 SKU、外部真人 Golden、EPREL、生产部署与六平台 Gate 均保持原边界。

## 0. 发现依据与可复用接口

R81 的发现已完成，不重新联网或重新声称目视复核。本文继承以下准确证据：

| 依据 | 用途与边界 |
| --- | --- |
| `docs/plans/2026-10-19-official-vehicle-pdf.md` Phase 2–5 | Root 已选 nullable 文本＋capture 引用；不能改为占位文本、隐含 base64 或平行 sidecar |
| `.artifacts/r81-su7-binary-architecture-828ba44b291848aabaac332656e0bd0a/PHASE0.md`、`source-index.json`、`verification.json` | 46 项来源的既有架构审计；是历史读取证据，不是当前二进制实现通过 |
| `.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-pdf-observations.json` | 两次实际 200、MIME、原件大小/SHA、用途边界；不是生产 capture |
| `.artifacts/r81-su7-visual-review-7ce747a644e64296b051f815a0d7fe39/VISUAL_MATRIX.json`、`REPORT.md` | 两个已绑定文件第 3 页的五行×三配置、轴位、条件、图例、CLTC 脚注及坐标；是 agent 视觉复核，不能改称外部真人 Golden |

定向核对的现有 API 可以直接复用；以下未标“新增”的名字均已存在：

| 文件/定位 | 现有接口或模式 | 本合同使用方式 |
| --- | --- | --- |
| `apps/api/tire_api/adapters/transport.py:154` | `SafeHttpClient.get_bytes(url, **kwargs) -> BinaryFetchResult` | 保留既有固定 host、逐跳 URL、DNS/IP、大小和超时控制，不另写下载器 |
| `apps/api/tire_api/captures.py:31/55/92` | `checked_capture_bytes(db,row)`、`validated_observation(observation)`、`before_parse_recorder(db,run)` | 保留捕获先提交、对象有引用时不回退 DB 副本的顺序；新增编码分支与可信 run 校验 |
| `apps/api/tire_api/documents.py:21/119` | `record_object(db,data,store=None)`；既有 PDF 内容响应 | 只复用低层 bytes 存储/响应头，不创建用户上传文档来冒充官方车型 capture |
| `apps/api/tire_api/object_store.py:23` | `checked(data,digest,size)`；store `put/get` | 原字节 SHA、长度和 8 MiB 上限；原子无覆盖写与失败关闭 |
| `apps/api/tire_api/vehicles.py:94/111/340` | `VehicleSnapshot`、`VehicleQuarantine`、`VehicleService.persist(...)` | 扩展 nullable 原文及引用；保留采集锁、source generation、Parser selection、质量隔离 |
| `apps/api/tire_api/vehicles.py:159/201` | `fitment_fact_hash(payload)`、`vehicle_provenance(snapshot)` | 原文观察与事实版本分离；修正首代 source_page，避免沿用当前 JSON 页面 |
| `apps/api/tire_api/reparse.py:110/146` | `capture_input(db,capture,entries)`、`validate_candidate(payload,source_input,raw)` | 增加首代固定来源合同；历史候选仍不自动成为在线事实 |
| `apps/api/tire_api/quarantine_review.py:37/76/124` | `binding(...)`、`context(...)`、`consume_approval(...)` | UTF-8 旧 binding 字节不变；binary 使用显式新 binding，保持新在线观察才消费审批 |
| `apps/api/tire_api/parser_releases.py:224/267/496` | `pin_selection`、`assert_selection_current`、`create_evaluation` | 继续绑定 source/bundle/deployment 与同一 capture，不能绕过发布评估 |
| `apps/api/tire_api/db.py:520`、`migrations.py:96` | `Database.initialize` 在锁事务内 `create_all→upgrade` | 这是需谨慎调整的真实入口，不能在已有事务里尝试关闭 SQLite 外键 |
| `apps/web/components/evidence-documents.tsx:46`、SDK `documentContent` | Blob MIME/大小/SHA 校验与 `platform.saveDownload` | 复制现有下载流程，不默认内嵌执行 PDF |

下文 `vehicle_raw.py`、来源专用 PDF mapping、`RawEvidenceV2` 和新 `/content` 路由都是**拟新增接口**，不能在实现前当成可调用功能。

## 1. 原件与来源事实冻结

### 1.1 唯一首批版本

正式首批选择 R81 的 S2：固定来源为 `xiaomi.FIRST_GENERATION_SOURCE_PAGE`，即小米 `s1.xiaomiev.com` 下 `/activity-outer-assets/0328/env/SU7%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%A1%A8.pdf`。

- 原件字节数：`3240150`。
- 原件 SHA-256：`0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`。
- 第 3 页渲染尺寸：`1272×1800`；S2 页图 SHA：`e1c460e35440bb2cef1bdfb4269659971cfbc64821b4b58f915264235967c36c`。
- S1 的 `8260598` 字节、SHA `a08dd8f801c96d730843d1d68e9f7603f8962a9fb063d3229a4934a14e663472` 仅为独立对照，**不进入首批生产接受清单**，不把两份正文拼合，也不悄悄切换较大原件。

这些是 R81 已封存的观察值；本次文档没有重新下载或视觉核验。正式每次在线查询须重新取得当次原始 bytes 并先留 capture，随后才比对已审 SHA。网络失败不能返回本机研究 PDF 假装新在线结果；用户未同意时不得读取历史代替。

### 1.2 解析方法与稳定标识

拟新增 `adapters/xiaomi_first_generation_pdf.py`，方法名冻结为 `parse_reviewed_pdf(raw: bytes, vehicle_id: str) -> dict`。公开说明固定为“**SHA-256 绑定的已复核历史 PDF 映射**”；机器方法名 `sha256_bound_reviewed_mapping`，mapping ID `xiaomi-su7-first-generation-pdf@1`。这是已审版本解析，不是 OCR，也不是首代当前配置全集。

纯函数只验证 `vehicle_id == FIRST_GENERATION_ID`、bytes 类型、`1..8388608` 字节、`%PDF-` 文件签名、固定长度与固定 SHA，全部成功后才实例化受信映射。它不接收 URL/MIME，也不能虚构这些校验已由自己完成；来源/source/URL/MIME/用途由第 3.1 节可信 context 入口在调用前核对。整链对任何单字节修改、未知 SHA、其他车型/代际、替代 URL 或 MIME 不匹配均失败关闭。未知合法 PDF 可以保留为失败观察，但不能套用旧映射。

映射以受绑定 `.py` 数据/纯函数保存进 Parser 源码包，首批不新增 PDF/OCR 运行依赖：当前 `parser_bundles._tree` 只接收 `.py`，直接复用其 manifest 封存即可。不能在运行时读取 `.artifacts`、可变 Markdown/JSON 矩阵或未纳入 bundle 的 sidecar；不能把研究 PDF、商标页图或不可再分发正文提交到 Git corpus。

沿用现有 `vehicle/trims/fitments/footnotes/documents/coverage` 结构，首批输出 3 trim、15 fitment（含不可用格）。本地标识与来源官方 ID 分开说明：`source_vehicle_id` 使用固定本地来源选择器 `su7-first-generation`，`source_trim_id` 使用已印列名的规范化 `su7/su7-pro/su7-max`；不伪造官方数值 ID。`vehicle.source_version` 使用 `pdf-sha256:<完整SHA>`。车型及所有 trim 的 `model_year=null`。

fitment ID 由 `digest({vehicle_id, trim_id, reviewed_row_id})[:24]` 决定，`reviewed_row_id` 为 `W1..W5`；它是本地行标识，不是厂商产品码。每个 trim 的 `wheel_option_ids` 精确包含其五格，顺序固定，不丢不可用项。沿用轴位 schema，`load_index/speed_rating/oe_mark/manufacturer_product_code/matched_tire_variant_id` 全部为 null；未表示的 GTIN、XL/HL、静音/缺气保用等仍未知，不新增推断事实。

| 行 | 轮毂及原始系列描述 | 前轴 | 后轴 | SU7 / Pro / Max | 必须保留的条件 |
| --- | --- | --- | --- | --- | --- |
| W1 | 19 英寸低风阻；米其林 e·Primacy | 245/45R19 | 245/45R19 | standard / standard / optional | 只有 Max 格明确“免费选装” |
| W2 | 19 英寸运动；普利司通 TURANZA 6 | 245/45R19 | 245/45R19 | unavailable / unavailable / standard | 原文“前后”，不能漏后轴 |
| W3 | 20 英寸运动＋前 Brembo 四活塞固定卡钳＋打孔通风盘；米其林 Pilot Sport EV | 245/40R20 | 245/40R20 | optional / optional / unavailable | 套装行保留制动配置条件；不是 Max 的 265 后轴 |
| W4 | 20 英寸运动；米其林 Pilot Sport EV | 245/40R20 | 265/40R20 | unavailable / unavailable / optional | 独立 Max 行，不与 W3 合并 |
| W5 | 21 英寸运动；倍耐力 P ZERO | 245/35R21 | 265/35R21 | unavailable / unavailable / optional | 只保留印刷系列名，不展开未出现的子款 |

`staggered` 必须等于前后尺寸是否不同。CLTC 按原三条脚注保留：SU7 700/628 km；Pro 830/758 km；Max 800/810/750/725 km，分别对应矩阵中的原胎系列顺序。它们属于整车 CLTC 配置说明，不能生成专业轮胎 `TestEvent`、七维性能评分或安装安全结论。

### 1.3 locator

继续使用既有 `evidence_locator: str`，冻结可解析格式：

```text
pdf-sha256:<64hex>#page=3&row=W3&trim=su7-pro&bbox=590,975,887,1161&canvas=1272,1800
```

这是左上原点的行/单元格区域，不是字形/OCR 边界。W1..W5 的 y 区间分别为 `715..835`、`835..975`、`975..1161`、`1161..1322`、`1322..1463`；原描述列 x=`86..293`，三个 trim 列分别 `293..590`、`590..887`、`887..1186`。详细复核记录还须包含行区域及原灰字描述区域；UI 只在对应 SHA 原件上使用该 locator。首批下载无需自动生成新页图。坐标、PDF 页号 3、纸面页码 3、映射版本和复核出处须一并进入映射源码；不声称整份 PDF 或其他页内容已复核。

## 2. 编码、数据库与引用约束

### 2.1 唯一编码枚举

服务器/内部观察使用 `body_encoding ∈ {"utf-8", "binary"}`。`binary` 在本轮仅允许首代小米 `application/pdf`，不是任意二进制文件开关。缺少该字段的既有 Adapter 只按旧 UTF-8 分支解释，不能根据 MIME 或 Python 类型自动猜 binary。

| 层 | UTF-8 | Binary PDF |
| --- | --- | --- |
| Adapter observation | `body: str`，显式或旧兼容 `body_encoding="utf-8"` | `body: bytes`，必须显式 `body_encoding="binary"` |
| 原字节 | `body.encode("utf-8", errors="strict")` | `body` 原 bytes，不 decode，不重新导出 |
| `RawCapture` | `raw_body: bytes`、编码 utf-8 | 同列保存原 bytes、编码 binary；必须存在对象映射 |
| `VehicleSnapshot/VehicleQuarantine` | `body: str` 非空；编码 utf-8；`raw_capture_id` 可空以兼容旧行 | `body: NULL`；编码 binary；`raw_capture_id` 必须非空 |
| 新 metadata wire | `body: str` | `body: null`，内容通过受限 `/content` 读取 |

禁止空字符串替代 PDF、`latin1` 可逆伪文本、JSON 中未声明的 base64、把抽取文字 SHA 称作原 PDF SHA。IPC 的 `body_base64` 继续只是原 bytes 传输容器，不改变上述存储/接口语义。

### 2.2 拟定模型变更

1. `vehicles.py` 两模型：`body: Mapped[str | None]`；`body_encoding` 为 `String(16) NOT NULL DEFAULT 'utf-8'`；`raw_capture_id` 为 nullable `String(64)` 外键到 `raw_captures.id`，`ON DELETE RESTRICT`，普通索引，**不设 UNIQUE**。
2. `db.py` 的 `RawCapture` 与 `RejectedObservation`：新增相同 `body_encoding NOT NULL DEFAULT 'utf-8'`。保留原 `raw_body` bytes，不新建 PDF blob 表。RejectedObservation 的现有唯一 `query_id` 连接同 query 的 RawCapture；本轮不再新增第二条冗余 capture ID 列。
3. `VehicleVerification` 不增加重复引用：现有 `query_id → RawCapture.query_id` 已唯一定位本次接收。snapshot 的 `raw_capture_id` 表示创建该观察快照的原件；重复核验的 capture 由该 verification 的 query 定位，二者不能被混同。
4. `CaptureObject`、`EvidenceObject`、对象 key/hash 协议保持。binary 必须拥有完整 `RawCapture → CaptureObject → EvidenceObject → store.get` 链；有对象引用而对象缺失/损坏时禁止回退 `RawCapture.raw_body`。

车辆两表的本地 CHECK 冻结为以下逻辑（实现时按 dialect 使用合法 SQL，不复制成跨库原生 enum）：

```sql
CHECK (body_encoding IN ('utf-8', 'binary'))
CHECK (
  (body_encoding = 'utf-8' AND body IS NOT NULL AND length(body) > 0
     AND content_type = 'application/json')
  OR
  (body_encoding = 'binary' AND body IS NULL AND raw_capture_id IS NOT NULL
     AND content_type = 'application/pdf'
     AND source_id = 'xiaomi-cn-vehicles'
     AND vehicle_id = 'xiaomi-su7-first-generation')
)
```

RawCapture/RejectedObservation 的 CHECK 至少要求合法编码，binary 分支只能为上述 source、`target_kind='vehicle'`、`content_type='application/pdf'`。RawCapture 的 `byte_count` 必须 `1..8388608` 且等于 BLOB 长度。旧文本 MIME 白名单不在本轮泛化；旧行若不满足合法正文/历史 MIME，迁移预检报告并拒绝，不能静默转换或修复原证据。

外键/CHECK 不能表达跨表的 source/query/哈希等价；这些由下面统一 helper 在写入和读取时检查。ORM 只追加保护继续存在；不把这些约束宣传为防管理员直接篡改所有存储的完整保障。

### 2.3 统一原件 helper（拟新增）

新增小模块 `apps/api/tire_api/vehicle_raw.py`，只处理两种车型编码，禁止变成通用媒体平台。拟定入口：

```python
def checked_vehicle_bytes(db: Session, row: VehicleSnapshot | VehicleQuarantine) -> bytes: ...
def checked_vehicle_capture(db: Session, run: QueryRun, observation: dict) -> RawCapture: ...
def vehicle_raw_metadata(db: Session, row) -> dict: ...
```

`checked_vehicle_bytes` 检查顺序：本地编码约束 → 对应 source/vehicle 固定来源合同 → capture/FK 与 query 身份 → hash/length/MIME → 对象映射 → 实际原 bytes → 受支持 PDF 版本（需要结构化事实时）。任何一步失败返回固定完整性错误，禁止换最近快照或读取研究目录。

binary 快照必须与其 capture 的 `source_id/source_url/content_type/raw_hash/body_encoding` 一致，capture 的 QueryRun 为精确 `{"vehicle_id": row.vehicle_id}`，`query_key == digest(query)`，target_kind=vehicle。quarantine 还必须 `capture.query_id == row.query_id`。Parser version/identity 依据该 capture 的原观察和已登记执行链核对，不能将当前 Parser 身份倒填历史。

UTF-8 旧行 `raw_capture_id=NULL` 时直接严格编码旧 `body` 并核 SHA；若旧行确有引用则同样检查引用。不为迁移制造不存在的 RawCapture/Verification。legacy RawCapture 缺对象时仅 UTF-8 分支保留既有 `database_legacy` 读取；新 binary 禁止此退路。RejectedObservation binary 通过现有唯一 query 寻得匹配 capture、核两处 raw hash/bytes，再由 authoritative 对象取原件；失败原件不因此获得 accepted 状态。

### 2.4 映射身份必须随历史冻结

不新增 provenance 表/列：新 binary 的 `VehicleSnapshot.payload` 与 `VehicleQuarantine.payload` 内保存一个**服务端专用** `parse_provenance` 闭合块，恰含 `contract="vehicle-pdf-parse@1"`、`method="sha256_bound_reviewed_mapping"`、`mapping_id`、`source_raw_hash`、`bundle_id`、`mapping_file_sha256` 六键。pure Parser 返回方法/mapping 声明；写入端结合当次 pinned selection、实际 parser receipt 和封存 manifest 中 `adapters/xiaomi_first_generation_pdf.py` 的源码 SHA 核验后形成完整块。调用者传来的 method/mapping 声明不能绕过这项检查；不能读取当前工作区常量给旧执行补身份。

该块和原 payload 一起只追加，`source_raw_hash` 必须等于本行/对应 capture 的原件 SHA，`bundle_id` 必须等于该次已验证 `parser_identity.bundle_id`，mapping 文件 SHA 必须与该已登记 bundle 相符。新 binary 若缺块、字段多/少、版本或摘要错配均按完整性错误拒绝；旧 UTF-8 行无该块是合法历史，不能倒填。历史重解析的候选块由其所选 bundle 同样绑定，再进入原 completion fingerprint，不自动写回旧 snapshot。

V2 的 `parse_method/mapping_id` 与 binary 审批 binding 从这个冻结块读取，并核对已登记身份；需要从封存源复核时只能读取原 bundle 的已验文件，不执行任意代码，也不使用“当前 raw SHA→mapping 常量”重建。若同一原 PDF 在 mapping 修订后重新解析，新 snapshot 使用新块；旧 snapshot/隔离/V2/审批仍保持原 mapping 身份。专门反例须覆盖同 SHA 不同 mapping、当前部署变化、原 bundle 缺失/被篡改、伪造 mapping_id，以及旧审批不得被新 mapping 自动消费。

该块不进入 `fitment_fact_hash` 的四个业务投影、不进入既有 vehicle provenance/source 八键，也不进入 normalized 离线 payload、Host DTO 或 Provider 材料。第 6 节离线投影继续只取原四类结构化事实；新服务端 metadata 与历史身份留存不能成为外发 raw/额外字段的通道。

## 3. 捕获、Parser 与版本闭合

### 3.1 可信来源合同

新增来源专用轻量合同定义（可放 `adapters/xiaomi_first_generation_pdf.py` 的纯常量，不能引入 DB）：精确 source、vehicle、固定 URL、MIME、编码、大小、SHA、mapping ID 与用途政策 ID。`validated_observation` 新增可选 keyword-only 可信 context（拟定 `source_id/query`），旧单参调用仍只接 UTF-8；binary 无 context 立即拒绝。`before_parse_recorder`、`retain_rejected_response`、VehicleService 传入已有 QueryRun 的 context，不能信任 observation 自报 source/query 作为唯一依据。

固定流程：提交 QueryRun 和 source/Parser pin → 已授权固定 URL 的 `get_bytes` → 以实际返回原 bytes 构建 binary observation → 同步 `before_parse_recorder` 独立事务写对象/RawCapture/CaptureObject 并提交 → Parser → 再次锁内核 source/Parser generation → 快照/隔离/核验事务。捕获提交失败不得调用 Parser。Parser 或领域事务失败时捕获仍可追溯；对象写成功但 DB 事务失败可能留下未引用对象，只能由另行受管回收流程处理，不能称零孤儿或顺手清理历史对象。

捕获准入核固定 URL/MIME、bytes/容量和基础 `%PDF-` 签名，**不以前置固定 SHA 匹配代替捕获**；通过基础准入的未知修订先保存再由 Parser 拒绝。不满足 PDF 基础类型的响应只记安全失败元数据，不能作为 application/pdf 原件下载；“合法拒绝原件”不意味着允许任意响应体突破准入。

合法来源但未知 SHA/错误 PDF 结构：保留受大小限制且已获存储许可的 capture，记录固定失败码 `vehicle_pdf_revision_unreviewed`（拟新增并加入现有 safe-code 白名单）或 `vehicle_pdf_invalid`；不保存快照、不生成 fitment、不把新原文与旧事实绑定。超限/错误 host/未获保存许可在接收持久化前拒绝，不为“失败证据”突破权限和容量上限。

### 3.2 Parser 协议与兼容

- 保持现有 IPC 字段集合与 `body_base64`，首批不新增通用 encoding 字段到旧 closed envelope；trusted source＋query.vehicle_id＋受版本绑定的分派决定 JSON/PDF 两支。
- `parse_isolated` 原 bytes 输入哈希、GO gate、8 MiB/协议上限、超时/CPU/内存、Job/reap 都保留。
- 当前 `parser_child.py` 无条件 UTF-8 decode 改为分派后 decode：原所有文本 Parser 严格 UTF-8；只有首代固定 PDF 分支原 bytes。不得全局 `errors=ignore/replace`。
- `source_catalog` 的 xiaomi 依赖闭包必须纳入新 `.py` mapping；新共享 Xiaomi Parser 版本必须递增并明确支持两种车型输入。不能用“包 digest 变了”掩盖版本语义变化，也不能让旧 bundle 自动读取新工作区 mapping。
- 老包重放原 JSON 继续成功；老包收到 PDF 明确 unsupported/受控失败，不能被算候选解析成功。发布评估记录 control 不支持 PDF 的能力缺口；不能借机豁免原有 release gate 或伪造 Golden 引用。启用首代前必须证明选定 active bundle 支持 binary，回滚老包时先关闭首代在线能力。

### 3.3 相同原件、事实版本与重新审核

`raw_hash = SHA256(actual bytes)`；`fact_hash` 继续用现有 `fitment_fact_hash`，不把 encoding/capture ID/下载时间/locator/mapping ID 混入事实。mapping 身份按第 2.4 节冻结到服务端 payload 并绑定原 Parser bundle，不扩充既有闭合 `parser_identity` 对象；`source_version` 使用现有排除规则。

| 新观察 | 应有行为 |
| --- | --- |
| 同原件、同 Parser identity、同事实 | 新 RawCapture、新 QueryRun、新 VehicleVerification；可复用现有 Snapshot/fact_version；核本次 capture 同字节，不覆盖旧 snapshot.raw_capture_id |
| 原件变化、事实相同（未来另一个明确审过的版本） | 新 Snapshot/原件引用，fact_version 不变；不得覆盖原观察或仅更新 observed_at |
| 事实变化且通过质量门 | 新 Snapshot，fact_version＋1；新增对应 WheelFitment 与既有 interest 事件 |
| Parser/mapping 变化、原件相同 | 依现有 parser_version/identity 条件追加 Snapshot；事实未变不增 fact_version；记录真实执行身份 |
| 质量损失 | 新 VehicleQuarantine，`body=NULL`、capture 引用完整；无正式事实/关系提升 |
| 非支持版本、Parser/结构失败 | RawCapture＋允许的 RejectedObservation；不是质量审批可以越过的可接受候选 |

binary quarantine binding 使用显式 `binding_contract="vehicle-binary@1"`，在原 source/query/baseline/url/parser/payload/quality/Parser identity 基础上绑定 `body_encoding/raw_hash/byte_count/mapping_id`。**不把本次 capture ID 纳入可复用审批比较 hash**：批准后须重新在线取得另一个 capture，只有同 bytes、同身份/基线/质量才可一次消费。旧 UTF-8 binding 的键集/哈希算法保持原样，以免历史审批失效或被误认新审批。

`reparse.capture_input` 新 binary 输入记录增加 encoding/mapping 事实，保留原 input 的旧 text 结构/哈希兼容；读旧 ReparseRun 不重写 input 或 completion fingerprint。历史重解析可验证/比较候选，不能仅因重新解析成功就更新旧 Snapshot、使用一次在线授权或生成新在线 Verification。`parser_releases.create_evaluation` 的 candidate/control 都读取同一经核 capture bytes；损坏对象直接 hard block，不从 DB 副本补过。

## 4. 最小迁移、保全与回滚

当前最大迁移标识为 `023_external_api_keys`。拟使用 `024_vehicle_binary_raw`；实现开始时重新核占用，若已被其他正式迁移使用须分配下一个号，不覆盖既有记录。

### 4.1 新私库的迁移前置

先构造当前 schema 的代表私库，含真实旧 JSON bytes、快照、隔离、核验、外键引用、重复事实、旧审批/reparse/release/关系/车库/离线引用。保全清单必须含数据库一致性备份、对象目录、Parser bundle、迁移版本、表/索引/触发器/视图、行数与关键列逐行摘要；原始凭据/连接串不写日志。复用 `scripts/backup_dev.py` 的保全结构前先读其真实 CLI；不要猜参数或把在线复制主 SQLite 文件当完整 WAL 备份。

必须显式列出引用车辆两表的入向外键，不能只备份待改两表。SQLite 检查 `integrity_check`、`foreign_key_check`、`table_info/foreign_key_list/index_list` 和 `sqlite_schema`；PostgreSQL 在独立私库核 constraints/indexes/sequences。发现旧空正文、错误 MIME/哈希或悬空引用时输出受限报告并停止，不自动“修数据”。

**当前源码已核的依赖最低清单**（未连接任何数据库；正式迁移仍须按目标库实际 schema 补齐）：

| 依赖 | 当前声明 | 迁移中必须证明 |
| --- | --- | --- |
| `vehicle_quarantines.previous_snapshot_id` | `vehicles.py:117` → `vehicle_snapshots.id` 的 FK | 两张重建表同事务完成；原 baseline ID 与原 payload/quality 不变 |
| `vehicle_verifications.snapshot_id` | `vehicles.py:132` → `vehicle_snapshots.id` 的 FK | 所有原 verification/query/identity/时间仍指向原 ID；不复制出“新核验” |
| `vehicle_wheel_fitments.snapshot_id` | `vehicles.py:144` → `vehicle_snapshots.id` 的 FK | 原 option/trim/version/specification 对应关系、索引和数量不变 |
| `quarantine_reviews.quarantine_id` | `db.py:205` 是普通 String/index，**没有**指向车辆隔离表的 SQL FK | 除 FK 检查外另作语义连接校验；保存原 quarantine ID、binding_hash、revision，不能因重建生成新 ID |
| `quarantine_approval_uses` | `db.py:218/219` 分别 FK 到 review 和 query；query_id 唯一 | 原批准/消费次数和关联不变；重建不能让已用审批再次可用 |
| 关系/车库/重解析/发布/兴趣引用 | `FitmentRelationRevision.selection/vehicle_evidence/binding`、`GarageRevision.fitment_reference`、`ReparseRun.baseline`、`ParserEvaluation.bindings`、`InterestEvent.origin_id/payload` 存于 String/JSON | 对这些逻辑引用另核原 JSON/指纹和 ID；`foreign_key_check` 通过不足以证明未破坏这些引用 |

定向搜索当前模型只发现上述三条指向 `vehicle_snapshots` 的 SQL 入向 FK，未发现指向 `vehicle_quarantines` 的 SQL FK。车辆模型的只追加保护来自 `vehicles.py:149/153` 的 `Session.before_flush`；捕获、审批和车库来自 `db.py:437/440`，关系/重解析/Parser/兴趣模型另有相同 ORM guard。当前迁移源码未为车辆两表声明数据库级只追加触发器，不能声称直接 SQL 已受这些 ORM 钩子保护。低层迁移只复制相同历史数据，不移除应用 guard；若目标库实际另有 trigger/index/view，必须按已备份 SQL 恢复并核对。迁移后的最小验收要同时覆盖 ORM update/delete 仍拒绝、原 review binding 不变、已消费 approval 不可重用，以及原逻辑引用可读。

**独立 expected 与历史增量保证：**在生产模型修改前，冻结并人工核对版本 `023` 的私库基线 DDL/合成历史行/预期索引与触发器清单，作为新的、带源码版本与 SHA 的迁移 fixture；预期结果由该基线加本合同声明的 `024` delta 明确组成。不能在测试中用修改后的 `Base.metadata.create_all()` 生成“旧库”，也不能读取迁移后的当前 schema 动态充当 expected。当前模型的 `after_create` 等事件可能把较新触发器注入旧版本 fixture；构造历史 fixture 应使用已审版本限定的 DDL，隔离这种测试准备污染，而不是删除生产触发器、跳过不可变性断言或把污染后的 schema 宣称旧版本。

保留现有**每一个历史 migration 的专属增量、数据保全及既有 rollback/失败原子性断言**，不能用一个最终版本号/总行数检查替换。新增 `023→024` 私库用例覆盖两张 nullable 重建、两张编码增量、入向 FK/逻辑引用和失败回滚；另设独立“全链 preservation”用例，从冻结历史基线逐步到最终 schema，比对每个阶段已存在的原列、约束、索引/触发器和内容摘要。专属切片证明本次 delta，全链证明没有破坏早期保证，二者互不代替。若某历史迁移本来只支持备份恢复而无 down migration，继续如实记录这一边界，不因本合同虚构可逆能力。

### 4.2 执行设计

RawCapture/RejectedObservation 的编码列可添加并默认 utf-8。车辆两表要让旧 `body NOT NULL` 变 nullable，SQLite 必须按受审重建方案处理，不能以“只加列”假装完成。

SQLite 采用受控连接：在事务外设置 `PRAGMA foreign_keys=OFF`，取得 `BEGIN IMMEDIATE` 独占写锁；创建临时新表并完整复制原列与 `utf-8/NULL` 新列；比较行数/主键/原列内容；按 SQLite generalized ALTER 模式 drop 原表、rename 新表到原名称，重建准确索引/触发器，**不先把原表 rename 成 backup 名称**；在同事务内执行 `foreign_key_check`、schema 对照和数据比对，通过后才记版本/commit。异常 rollback；finally 在事务外恢复 `foreign_keys=ON` 并验证。不能在现有 BEGIN 内切换 foreign_keys，因为该 PRAGMA 不会达到目的。

因此需要在 `Database.initialize` 的现有 `create_all→upgrade` 前增加 schema preflight：新空库正常创建最终 schema；已有库若 pending 此重建迁移而未走受控迁移入口，明确拒绝启动并提示私库演练/保全步骤。不能由模块 import 的全局 app 静默执行重建。拟新增局部迁移 helper 供专用私库执行入口调用；不是改造整个迁移框架。具体 DDL 要从当前表对象及已封存旧 schema 对照生成，保留所有 inbound FK、索引和触发器，禁止盲拼通用 `CREATE TABLE AS SELECT`。

PostgreSQL 使用独立私库、事务锁、`ALTER COLUMN body DROP NOT NULL`、新字段/FK/CHECK/index；旧原文及所有历史 ID 不变。SQLite 通过不能替代 PostgreSQL 实测；没有私 PG 的回执时标记未验证，不为赶工启动正常 PG。

### 4.3 回滚合同

- 迁移事务中失败：回滚到迁移前 schema/data，版本号不出现；验证仍可由旧 reader 读取原 JSON。
- 迁移后尚无 binary 行：可按受审逆向 schema 或完整备份恢复在私库演练；恢复前后旧列/关系/原件 SHA 一致。
- 已有 binary capture/snapshot/quarantine：禁止回退到只懂文本的 schema/应用并丢引用。优先关闭首代在线能力、回滚 Parser 选择，同时保留新 reader 和数据库兼容层。确需灾难恢复，必须按完整 DB＋对象＋bundle 一致备份恢复，并明示可能丢失备份后记录，不能自动执行。
- 不删 binary 证据、不把 PDF 变空正文、不重写旧封存来“恢复兼容”。正常库迁移的保全/授权边界继续独立，不被本文待办替代。

## 5. HTTP 原件与 SDK 合同

新增服务端格式 `format=raw-evidence-v2`，用于现有 `/v1/vehicle-evidence/{id}`、`/v1/captures/{id}`、`/v1/quarantines/{id}`。新格式必须显式 `mode=history`。旧 vehicle text 调用无 mode 的现有行为保持兼容；旧 text envelope 不强塞新字段。binary 若没有新格式协商，返回 409 固定码 `binary_evidence_format_required`，不能返回空 body 假成功。

V2 在各现有 endpoint 元数据基础上固定以下新增/替换字段；SDK 为各 endpoint 保留独立闭合 schema，不套一个允许任意键的大字典：

| 键 | 合同 |
| --- | --- |
| `evidence_format` | 固定 `raw-evidence-v2` |
| `body_encoding` | `utf-8` 或 `binary` |
| `body` | text 为 string；binary 必须 null |
| `raw_capture_id` | 已关联/派生 capture ID；旧 text 无真实 capture 时 null，不补造 |
| `raw_hash` / `byte_count` | 实际原 bytes 的 64hex SHA 与 `1..8388608` 整数 |
| `content_type` | binary 固定 application/pdf；text 沿既有白名单 |
| `content_path` | binary 为本 API 固定 ID 路由，text 为 null；不得任意外链或本机路径 |
| `parse_method` / `mapping_id` | 已成功解析的首代 Snapshot/VehicleQuarantine 为本文已冻结值（quarantine 仍未 accepted）；未解析/未知版本 capture、RejectedObservation 或旧 text 为 null，不制造解析成功 |

拟新增 GET：`/v1/vehicle-evidence/{id}/content?mode=history`、`/v1/captures/{id}/content?mode=history`、`/v1/quarantines/{id}/content?mode=history`。后者须正确区分 VehicleQuarantine 与 RejectedObservation，不能把质量隔离/失败原件改为 accepted。复用各自历史可见范围、会话审计与权限门；来源暂停采集本身不自动改变历史读权限，用途限制另行检查。

内容端点返回经 helper 验证的原 bytes，`application/pdf`、固定不含用户输入的 attachment 文件名、`Cache-Control:no-store`、`X-Content-Type-Options:nosniff`、`Content-Security-Policy:sandbox; default-src 'none'`。对象缺失/损坏用 503 固定完整性码；未知 ID 404；许可不允许下载为 403 固定用途码。首批不实现 range/部分响应、缩略图或内嵌 PDF viewer，不转发上游任意响应头。

SDK 新方法使用现成 `request<Blob>(..., "blob")`，新 V2 decoder 与旧 text 方法分别兼容；取得 metadata 后核 Blob 的 MIME、byte_count、SHA、签名，并处理 abort/账户 epoch，才调用 `platform.saveDownload`。重复点击/账户切换/组件卸载不得把迟到下载交给另一上下文。Header 中的 hash 不是唯一完整性依据，Native 已有限制时用 metadata SHA。

## 6. 消费者闭包矩阵

| 入口 | 文件/现有位置 | Binary 必须做什么 | 保持的界限 |
| --- | --- | --- | --- |
| 历史车型与原件 | `vehicles.py:452/513`、`captures.py:31/179`、`quality.py:326` | 先 helper 核真实原件/正式性，再输出结构或 V2；质量/失败分支不 decode PDF | 不把 history 标 live，不以新 mapping 改旧 payload |
| 重解析、审批、发布 | `reparse.py:110/146`、`quarantine_review.py:37/76`、`parser_releases.py:386/496` | 同 capture bytes、明确 encoding、旧 binding/completion 兼容 | 不自动应用候选、不把 control 不支持视为通过 |
| 人工适配关系 | `fitment_relations.py:45 verify_raw` | 调整调用为带 db 的车型原件校验；轮胎文本路径仍旧合同 | 不自动建立 OE/SKU 关系；unavailable 格不能成为可用安装项 |
| 兴趣/候选 | `interest_events.py:80`、`recommendation_candidates.py:44`、`candidate_ai.py` | vehicle side 用 helper；通过关系/事实版本门后才投影 | 不把 PDF 家族名变专业性能/精确身份，不新增 raw 到候选 DTO |
| AI 最小包 | `ai_evidence.py:380` | 加车型原件/核验检查，只送已许可最小结构化字段＋locator/reference | 原 PDF/全文/base64 不送 Provider；provider_use 默认 false |
| 知识索引 | `knowledge_index.py:208 _vehicle_documents` | 同 helper 后生成现有结构化文档；坏原件拒绝或明确不可用 | 不索引 PDF bytes/抽取全文，不静默保留“已核有效”标记 |
| 车库 | `garage.py:157` | 来源车辆/fitment 必须有正式核验且原件完整；复制选择时保存原证据引用 | 保存车库不触发网络/PDF解析，不推断年款/适配安全 |
| 报告/导出 | `reports.py:112/335` | 构建冻结 pack 前核原件与用途，只输出允许的结构化事实/引用 | 报告 SHA 是报告自身；不嵌入原 PDF，export 默认关闭相关未许可内容 |
| 离线包 | `offline_evidence.py:65/166`、`offline_packs.py` | 服务器先核 PDF 与正式 receipt，再只投影原有 vehicle/trims/fitments/footnotes | `raw_included=false`；documents 继续只计排除数，不离线分发原 PDF |
| DeviceAI/Host | `device-ai-projection.ts:204`、Rust `offline/wire.rs`、Android `OfflinePackageValidator.java` | 新 PDF-backed 例子仍通过现有规范化协议；原件只留服务器 | 不加 body_encoding/raw_capture_id/mapping_id 到冻结 source；不改 E1、包 v1/v2 或 Host DTO |
| Native 在线字节桥 | `packages/native-client/src/index.ts:263`、Rust `bridge.rs`、Android `NativeHttpBridge.java` | 复用 bytes↔base64 封送和保存；只在现有白名单不涵盖时精确增加上述 GET 内容路径 | 不新增原件 IPC 协议、任意路径或头权限；API 8 MiB 上限更严 |
| Web 界面 | `workbench.tsx` 的 evidence/capture/quarantine 展示、`evidence-documents.tsx` | 标注历史已核版本/原件大小/hash，提供安全下载与 locator 文本 | 不把 binary 显示为 TEXT，不把 agent 复核标人审验收 |

冻结的 offline/DeviceAI `source` **仅有八键**：`source_id/source_url/raw_hash/parser_version/parser_identity/observed_at/verified_at/verification_id`。其中 raw_hash 本来就可引用任意真实原件 bytes，无需加编码键。`parser_identity` 仍为现有闭合三键投影。新增服务端 evidence metadata 不得泄漏进 normalized source。原件损坏时，关系/AI/知识/车库/离线任一路径都不能继续生成“已核验”正例；旧冻结产物的读取和当前可再使用状态应区分，不能重写既有历史。

`webhook_delivery.py` 的 envelope.body 是通知 JSON，不是来源原文；本轮不改其 UTF-8 hash，也不把 PDF 塞进通知。

## 7. 用途许可与能力状态

R81 原件只有本机研究用途，开放许可未建立。`source_settings.py` 明确只管理采集开关，不授予版权、Provider 或再分发权限；不能把 enable 当许可。

来源专用用途描述至少区分 `capture_storage/local_original_read/structured_fact_use/provider_use/export_or_redistribution`，绑定政策版本、证据出处、适用对象/范围及期限（若有）。实现可复制既有 `material_source_policy.py` 的逐用途检查思路，但不能复用专业材料 capture 身份或继承其授权。

首批 `provider_use=false`、`export_or_redistribution=false`；capture_storage/local_original_read/structured_fact_use 的当前状态须如实为 `pending_review`，直到有该来源适用依据。管线与私有已授权原件重放可以先实现/验证，正式在线保存和用户原件下载必须等待各自用途依据明确。公开 URL、200、robots 允许、用户同意分析都不能单独替代版权/来源用途依据。后续自主核条款，不要求用户重复给 URL 或 Key。

政策限制/撤回后，新抓取、原件下载、AI、导出和新离线包分别应用对应用途门；暂停采集不会自动删除历史，历史保留/限制/删除按政策履行。不要在本次 bytes 改造里偷偷默认允许全部用途。所有条件完成前，首代仍是 `requires_source_verification`；文案可说明工程完成/许可待核，但不得 ready。

## 8. 逐文件实施顺序与验收

所有步骤均在当前全套回归结束、源码解冻后执行。每一步需先读所列现有模式，完成最小相关验证并封存原失败；表中“新增”文件与命令是待实现，不是已有完成项。

| 顺序 | 责任文件/复制模式 | 必要验收与反模式门 |
| --- | --- | --- |
| P1 原件纯合同 | 新 `adapters/xiaomi_first_generation_pdf.py`；复制 `VISUAL_MATRIX` 的已核事实/locator和现有 `parse_config` 输出形状 | 真实 S2 bytes→3 trim/15格；单字节、错误代际/URL/MIME、W3/W4混轴拒绝；null年款/SKU；不读artifact运行时、不引入OCR |
| P2 编码/存储 | 新 `vehicle_raw.py`；`captures.py`、`db.py`、`vehicles.py` 模型、`migrations.py`、`Database.initialize` preflight | 旧text原列/bytes/hash不变；新binary body=NULL+FK+CHECK；对象先存；错capture/错对象/缺对象/同长度损坏/错误编码全部拒；私库迁移失败回滚/FK/index/trigger保全 |
| P3 Parser/采集 | `adapters/xiaomi.py`、`parser_runtime.py`、`parser_child.py`、`parser_bundles.py` 的真实固定派发与依赖列表 | GET真实原bytes且callback先提交；JSON旧包回归；新PDF对旧包受控拒；取消/超限/Job/reap、selection/source ABA不变；不提高预算掩盖失败 |
| P4 写入治理 | `VehicleService._execute/persist`、`quality.py`、`quarantine_review.py`、`reparse.py`、`parser_releases.py` | 原capture崩溃后可读；相同raw多receipt、事实不变不涨version、批准后新capture同bytes一次消费；旧text审批/reparse哈希不变；质量/Parser失败不成事实 |
| P5 所有消费门 | 表6全部服务器消费文件；复用同helper，不逐处发明编码规则 | 对每个入口注入缺对象/错引用/错hash，均不产有效关系/AI/索引/车库/离线输出；文本轮胎/召回不变；raw/provider/export不扩权 |
| P6 API/SDK/UI | `domain-types/src/index.ts`、SDK `index.ts`＋新严格 V2 decoder、workbench展示；复用document Blob下载 | 旧text客户端不变；旧client遇binary明确409；V2元数据闭合、Blob签名/大小/SHA/取消/账户迟到；真实私HTTP→SDK→React桌面/窄屏 |
| P7 Native/离线/发布 | 精确Native GET策略（确有缺口才改），现有离线validator定向例；来源用途与ready条件 | source八键/raw_included=false保持；TS/Rust/Java规范化消费；三端前端构建≠原生运行；许可、真实捕获与完整子链齐备才打开首代 |

新增测试建议明确分组：`test_vehicle_raw.py`、`test_vehicle_pdf.py`、`test_vehicle_binary_migration.py`（拟新增；纳入显式 runner target manifest 并经精确子进程策略复核后才可运行）。既有最小回归范围以实际改动决定，包括 raw_captures/object_store/vehicles/vehicle_quality/quarantine_review/reparse/parser_runtime/parser_bundles/parser_releases/fitment_relations/interest/garage/AI/knowledge/offline 两版本；不能用几十项替代之后当前全 API/Worker 回归。

必须有“非合法 UTF-8 的真实 S2 原件”正例；只有 ASCII `%PDF` 合成样本不能证明消除了 UTF-8 假设。证据标签分别标真实在线、已核原件离线重放、合成反例、SDK、浏览器、原生；三配置和图像事实的 agent 复核不提升为真人 Golden。

## 9. 待执行命令与关闭条件

以下全部**未在本任务执行**。使用 PowerShell 7。禁止把正常 DB URL 或 Provider 凭据写入命令/回执；测试入口必须在导入 main 前建立新短私根和拒绝边界。

```powershell
# 解冻后：先做定向静态闭包检查。
rg -n 'body\.encode|raw_body\.decode|snapshot\.body|row\.body' apps/api/tire_api `
  -g 'vehicles.py' -g 'captures.py' -g 'quality.py' -g 'quarantine_review.py' `
  -g 'reparse.py' -g 'fitment_relations.py' -g 'interest_events.py' -g 'offline_evidence.py'
rg -n 'raw_included|verification_id|body_encoding|raw_capture_id' `
  packages/api-client/src/device-ai-projection.ts apps/desktop/src-tauri/src/offline/wire.rs `
  apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile/OfflinePackageValidator.java

# 示例只调用确实存在的受管runner和现有模块；每次使用不同的新短目录。
& 'apps/api/.venv/Scripts/python.exe' -X utf8 -B scripts/run_api_worker_regression.py `
  --phase collect --output-root '.artifacts/pdf-c-<NEW_GUID>' `
  --targets apps/api/tests/test_vehicles.py apps/api/tests/test_raw_captures.py
& 'apps/api/.venv/Scripts/python.exe' -X utf8 -B scripts/run_api_worker_regression.py `
  --phase run --output-root '.artifacts/pdf-t-<NEW_GUID>' `
  --targets apps/api/tests/test_vehicles.py apps/api/tests/test_raw_captures.py
```

`<NEW_GUID>` 是必须替换的占位符，不是可原样运行的路径。新增三个测试文件必须先加入 runner 显式清单；任何受其源码 pin 覆盖的生产变更，先重新审精确 child 分类/更新已审 SHA，不能因旧 pin 拒绝就关闭 guard。迁移专用入口、私 PG 命令和前端 workspace 命令待对应实现及现有 package scripts 核对后登记；不把不存在的 CLI 写成已可执行。

关闭首代功能 Gate 需要同时满足：用途依据、当次真实捕获、原件对象完整性、已审映射/Parser发布、私库迁移与回滚、质量/审批/历史兼容、全部消费门、真实私HTTP/SDK/UI、当前回归和无遗留资源。任一未验都必须在交付中标出；当前合同文档不关闭任何一项。完整 V1 发布 Gate 独立保留。

## 10. 置信度和明确待验证项

高置信度：nullable 需求、现有 UTF-8 硬门、捕获/对象 API、唯一 query 关联、审批等待新在线观察、冻结八键与 raw 排除均由上述当前源码/既有封存确认。

未验证：实际迁移 DDL、所有入向外键重建效果、PG、PDF网络/授权与实际生产capture、映射纯函数、binary release控制、消费者/UI/原生运行。尤其许可适用依据尚未闭合，不能由本文指定 SHA 自动得出可保存/可分发。本任务没有运行这些代码、测试或数据库。
