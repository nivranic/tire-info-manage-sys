# 车型原件 V2 HTTP 与 SDK 接线计划

日期：2026-10-19。依据冻结 `2026-10-19-official-vehicle-pdf-contract.md` §5/§7、R93 map 与独立 addendum；不改变原合同。实施前 Root 已复核 R92 seal、683 个 live source 与 R93 baseline。范围为 HTTP、SDK、领域类型和窄验证；UI/Native 保存、正式许可、在线采集及 PG/正常库升级另验。

## 路由与兼容

三个既有 detail 新增 `format=raw-evidence-v2&mode=history`：`GET /v1/vehicle-evidence/{id}`、`/v1/captures/{id}`、`/v1/quarantines/{id}`。旧 text 不增字段；旧 vehicle text 无 mode 继续可读。未协商 binary 保留 409 `binary_evidence_format_required`。未知 format、未知/缺失必需 history 为 422；vehicle V2 缺 mode 用 `raw_evidence_history_required`。内容路径固定为三 detail 路径加 `/content?mode=history`；不接受外部 URL。

未知 ID 为 404，原件损坏/缺失统一 503 `vehicle_raw_integrity_failed`，原件用途不允许为 403 `vehicle_original_read_not_allowed`，结构化用途拒绝为 403 `vehicle_structured_fact_use_not_allowed`。文本内容路径固定 409 `raw_evidence_content_unavailable`。固定码用 FastAPI `detail:{code}`；原有 404 文案保留。

内容先完整验证再返回全部 PDF bytes，200，不实现 range/206。固定 headers：`Content-Type: application/pdf`、`Content-Disposition: attachment; filename="vehicle-evidence.pdf"`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`Content-Security-Policy: sandbox; default-src 'none'`，附已核 `X-Evidence-SHA256`。成功 metadata 保留旧审计；内容分别记 `vehicle_evidence_downloaded/raw_capture_downloaded/quarantine_evidence_downloaded`，复用当前 workspace local-session 历史范围，不虚构逐账户 ACL。

## 精确顶层 metadata 键

共享 V2 十键集合 R：`evidence_format/body_encoding/body/raw_capture_id/raw_hash/byte_count/content_type/content_path/parse_method/mapping_id`。每分支以下键与 R 的并集是完整集合，拒绝未知顶层键：

| 分支 | R 之外的精确键 |
| --- | --- |
| vehicle evidence | `id/vehicle_id/snapshot_id/source_id/source_url/source_page/parser_version/parser_identity/observed_at/evidence_path/quality_review/verified_at/data_state/documents` |
| capture | `id/query_id/source_id/target_kind/source_url/parser_version/observed_at/parser_identity/query_state/query_reason/query/processing_unconfirmed/evidence_path/data_state/receipt_only/storage_kind` |
| quarantine 共同 Q | `id/query_id/source_id/source_url/parser_version/observed_at/previous_snapshot_id/status/kind/target_kind/reason_codes/metrics/evidence_path/data_state/accepted/candidates/quality` |
| field_loss tire | Q，无额外键 |
| field_loss vehicle | Q 加 `vehicle_id/vehicle_payload` |
| response_rejected | Q 加 `stage`；`previous_snapshot_id/metrics/quality=null`、`candidates=[]` |

`data_state=local_snapshot`；capture `receipt_only=true`，storage_kind 为 object_store/database_legacy；quarantine `accepted=false/status=quarantined`。quarantine 没有 parser_identity 顶层键。嵌套 documents、quality_review、candidates、quality、vehicle_payload 沿原领域 wire；不为新格式改写历史 payload。

binary：`body=null`、MIME application/pdf、真实 capture ID、固定 content_path；成功首代 Snapshot/VehicleQuarantine 的 parse_method/mapping_id 取原冻结 provenance，quarantine 仍未采纳。capture/rejected 即使其 capture 已成功解析也两字段 null。text：严格 UTF-8 string，content_path/parse_method/mapping_id 均 null；真实关联 capture 才填写 ID，旧无 capture 不补造。hash/byte_count 来自已核真实 bytes，1..8388608。vehicle text 仅 application/json；非 vehicle text 沿既有 text/html、application/json、text/javascript、application/javascript、text/plain 白名单。

## 用途检查与实现文件

API 仅改 `vehicle_raw.py/vehicles.py/captures.py/quality.py`。保留原 R91/R92 helper 定义字节；新增 `checked_vehicle_original_bytes(db,row,*,structured=False)`、`checked_vehicle_v2_metadata(db,row,*,structured=False)` 和私有 `_vehicle_original_policy(binding)`。前两者先核同一真实 row/capture/query/source/raw 身份，再检查固定可信来源政策。路由用 `vehicle_raw_requires_v2(db,row)` 同时识别 binary 或固定来源/首代 row、query/capture 身份；将首代改成合法 UTF-8/JSON/body/hash 不能降级成旧 text：未协商仍409，新 V2/content 由原 helper 完整性拒绝503。政策描述含版本、依据、精确对象 scope、期限和五种用途；生产 capture_storage/local_original_read/structured_fact_use=pending_review，provider/export=false。不得从 env、enable、用户勾选或 consent 授权。

受限 binary metadata/content 均检查 local_original_read；Snapshot/VehicleQuarantine metadata 仍带业务结构字段，另独立检查 structured_fact_use；content 不要求结构化用途。RawCapture/Rejected 原件读取不要求 accepted capsule、成功解析或正式核验。两用途互不授权。非 vehicle text 使用独立 text adapter；SourceQuarantine 严格 encode/hash，存在真实 capture 则核对象权威 bytes 与行身份，不能回退绕过坏对象。

SDK/domain 仅改 `packages/domain-types/src/index.ts`、`packages/api-client/src/index.ts`，新增 `raw-evidence-v2.ts`。新增独立类型 VehicleEvidenceV2/RawCaptureEvidenceV2/QuarantineEvidenceV2，不放宽旧 body:string。方法为 `tireApi.vehicleEvidenceV2/captureEvidenceV2/quarantineEvidenceV2`；内容方法为 `vehicleEvidenceContent/captureEvidenceContent/quarantineEvidenceContent`。**六个新方法统一签名 `(id,fence:{assertCurrent():void},signal?)`，包括单读 metadata 的方法，fence 均必需**；内容方法返回 `{blob,metadata}`。内部先 metadata 再固定 content，核 schema/ID/path/MIME/size/实际 SHA256/%PDF-；每次 await 前后、返回前复核 abort/fence/transport epoch。fence 不等同 transport epoch；真正保存前 UI/Native 仍须复核。

## 验证、交付与回滚

API 新 `test_vehicle_raw_v2.py` 复用私有 SQLite、历史 S2、真实 child 与既有 fixture，覆盖三 endpoint、捕获/拒绝/质量分支、独立用途、旧 text、非 vehicle text、严格协商、坏件、headers/全量/audit。runner 只加新模块登记及计数。SDK 新 `tests/raw-evidence-v2.mts` 编写但当前不运行；当前 ChildPolicy 只允许两个固定 Device Node literal script，没有 tsc/npm/任意 .mts 模板，不更改 Guard/ChildPolicy/launch/REVIEWED SHA。

开发期间仅源码/AST/diff/hash；独立审查通过并由 Root gate 后，才用既有 run_api_worker_regression.py 受管运行 API。SDK 静态、未执行测试与真实 HTTP→SDK 分别记录，旧 Device Node import 不算新 decoder 行为验收。新 V2 字段不进入 offline/Device 八键 source。回滚仅撤销本切片精确文件差异并恢复 baseline 副本，保留已有 dirty tree、私有运行证据与失败历史；不 reset/clean/stash，不 commit/push。
