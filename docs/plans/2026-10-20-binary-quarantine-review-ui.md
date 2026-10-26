# 二进制隔离审批接续实施计划

**Goal:** 在不依赖 EPREL Key 的现有车辆 PDF 隔离链上，先补审批 API 的来源用途门与账户意图绑定，再接入最小共享 SDK/UI。

**Architecture:** 复用 R90 的 binding/revision/后续在线一次消费和 R93 的原件用途 helper；binary 写入增加明确的账户意图 header，保持六键 body 和现有响应形状。UI 复用 R96 owner/transport fence，把原件、对照、服务端 binding 和一次人工确认绑定，审批不直接采纳历史事实。

**Tech Stack:** FastAPI / SQLAlchemy、TypeScript / React 19 / Next 16、共享 API client、Tauri Rust / Android Java 精确 HTTP header 策略。

日期：2026-10-20。**状态：仅静态设计，等待 Root 独审；未实施、未运行本计划测试。** 按 `writing-plans` 方法组织；本轮只新增本文，生产、测试、fixture、wrapper、HANDOFF 和已有 dirty 保持。本计划不另建 worktree、不提交推送，不启动产品 import/API/UI/正常库/外网/Provider/设备；下列验证是后续另行静审精确入口后的任务。

## 已确认事实与风险边界

依据原规格的证据追加、质量隔离与分层验收要求，以及现行 `docs/plans/2026-10-19-official-vehicle-pdf-contract.md`、R90/R93/R96 计划和报告；它们不因本计划而升级验收状态。

| 当前源码证据 | 已确认事实；不等于动态漏洞实测 |
| --- | --- |
| `apps/api/tire_api/quarantine_review.py:388–442` | GET 无 admin dependency，作用域为 `local_workspace`；POST 有早期 admin dependency，写锁内执行 revision/binding CAS 并 append review/audit。 |
| `quarantine_review.py:242–277`、`vehicle_raw.py:269/428/474` | binary review 走原件/provenance 完整性链，未走 R93 来源用途门。可达响应含 structured comparison 和 raw metadata；本轮未调用 HTTP 验证。 |
| `vehicle_raw.py:574–614` | `checked_vehicle_original_bytes(db,row,structured=True)` 先核完整性，再同时核精确 row/capture/query/source/hash scope 的 `local_original_read` 与 `structured_fact_use`；不要求 accepted。默认两用途 pending，原件门拒绝码 `vehicle_original_read_not_allowed`，结构化门拒绝码 `vehicle_structured_fact_use_not_allowed`。 |
| `vehicle_raw.py:511–529` | `require_vehicle_consumer_use` 是面向 capsule 的 consumer 用途门，本身不验证 accepted、原件完整性或 original_read；不能替代原 Q 的独立 scope，也不能拿 baseline capsule 代替 Q 许可。 |
| `auth.py:65–84/140–145/187–192`、`db.py:217–229` | 当前用户由 session→user 动态取值；同 cookie 登录/退出可改变 user_id。review 仅持久化 actor_session_id，operator 是自报文字；无 expected-account 合同。 |
| `api_key_inventory.py:139–146` | 已有 `X-Tire-Expected-Account`：单值安全 ID、与当前账户比较，header 不是凭据。该只读模式不是已存在的审批事务 CAS。 |
| `apps/web/components/source-quality.tsx:191`、`packages/api-client/src/index.ts:583–584` | binary 目前只显示“审批界面尚未接入”；旧 SDK 两方法未协商 V2，旧表单不能直接复用提交 binary。 |

待验证假设：后端用途门缺失是否产生实际可观察的未授权响应、并发身份切换的具体调度结果、现有 Native 对拟增 header 的精确拒绝结果。本轮仅静态路径分析；不将这些描述成已复现漏洞。GET 无 admin 是现有设计事实，单凭这一点不构成缺陷；维持既有本地工作区只读角色设计，来源用途许可与用户 admin 权限分别核对，不因本计划扩大 GET 角色限制。

## 当前精确合同（尚未增加 actor header）

```text
GET  /v1/quarantines/{id}/review?mode=history&format=raw-evidence-v2  -> 200
POST /v1/quarantines/{id}/reviews?mode=history&format=raw-evidence-v2 -> 201
```

POST 恰六键，额外键拒绝：

```ts
{
  action: "approve" | "keep_quarantined";
  expected_revision: number; // 严格整数 >= 0，不接受 boolean
  operator: string;         // trim 后 1–80
  reason: string;           // trim 后 5–2000
  confirmed_loss: true;     // 两个 action 都要求
  expected_binding_hash: string; // 小写 64hex，服务端原值
}
```

响应恰 16 键：`quarantine_id/scope/state/revision/can_approve/restriction/baseline_snapshot_id/current_snapshot_id/applied_query_id/comparison/history/history_truncated/evidence_format/binding_contract/binding_hash/raw_evidence`。固定 `scope=local_workspace`、`evidence_format=raw-evidence-v2`、`binding_contract=vehicle-binary@1`；`comparison={before,candidate}`；restriction/current_snapshot_id/applied_query_id 可 null。

`raw_evidence` 恰十键：`body_encoding=binary/body=null/raw_capture_id/raw_hash/byte_count/content_type=application/pdf/source_url/parser_version/parser_identity/parse_provenance`。parser_identity 完整三键 `bundle_id/parser_digest/deployment_revision`；parse_provenance 完整六键 `contract/method/mapping_id/source_raw_hash/bundle_id/mapping_file_sha256`，固定 `vehicle-pdf-parse@1`、`sha256_bound_reviewed_mapping`。没有 content_path、bytes、base64 或本机路径；不得推导下载地址。

history 最多 100 项，每项恰 `id/quarantine_id/revision/action/operator/reason/created_at/expires_at`，无 actor；同 binding 的不同 Q 可共享历史和最新 revision，不强行要求每项 quarantine_id 等于当前 Q。

15 键后端 binding 包含 `binding_contract/target/source/query_key/baseline/raw_hash/url/parser/content_type/payload/quality/parser_identity/body_encoding/byte_count/mapping_id`；不含 capture ID、run ID、时间和 source generation。浏览器不能仅凭十键 raw_evidence 自行重建它。

## Task 0：先补真实 API 的用途门与账户意图契约

**目标文件**

- Modify：`apps/api/tire_api/quarantine_review.py`。
- Read/reuse：`apps/api/tire_api/vehicle_raw.py`、`auth.py`、`service.py`、`db.py`；仅在确需共享 helper 时最小修改 auth，不泛改登录流程。
- Test：`apps/api/tests/test_vehicle_binary_approval.py`；新增候选 `apps/api/tests/test_vehicle_binary_review_boundary.py`。
- Native 后续精确接线：`apps/desktop/src-tauri/src/security.rs`、`security_tests.rs`、`apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile/NativePolicy.java` 及对应 policy 测试。

1. 先用私有 fixture 写 API 负例：原 Q 与 baseline 分别 original pending、structured pending、scope 错配、坏件；GET 与两个 POST action 均 fail closed，review/audit/fact/use 数量不增。复用 `checked_vehicle_original_bytes(...,structured=True)` 分别核原 Q 与正式 baseline 后，才构造/使用完整 review state；保留原完整性/provenance/quality/baseline 再核。权限异常映射为上述 403 code，不混成 503；完整性失败继续 503。生产 pending 不改为 allowed，测试许可仅由受审私有 policy fixture 提供。
2. **拟新增合同，当前尚不支持：** 仅 binary POST 必须携带恰一个 `X-Tire-Expected-Account: <auth/me.user.id>`，ID 匹配 `[A-Za-z0-9_-]{1,64}`。缺失/重复/畸形用新码 `review_expected_account_invalid`（422），与当前认证账户不同用 `review_actor_changed`（409）。匿名/非 admin 继续早期 `admin_required`（403），不泄漏记录。body 六键、响应 16 键和旧 UTF-8 请求保持；旧 binary 直调缺 header 将被明确拒绝，是有意的安全收紧，更新 binary fixture/test caller，不静默降级。
3. `lock_ingestion()` 会先 commit 再加 SQLite `BEGIN IMMEDIATE` / PG advisory xact lock（service.py:451–465）。必须在该锁之后刷新并锁定当前 UserSession 及判权依赖的 User 行，到本次提交结束，再核会话有效期、current user/admin 并比较 header；不能复用 dependency 已读 ORM 缓存或只在锁外检查。PG 使用行锁，SQLite 依赖现有写事务；核对登录/退出/重置，以及仓库实际存在的禁用、过期清理等身份更新路径与该锁/事务顺序一致，设计并发 barrier 负例，不凭库存只读模式宣称已经具备事务 CAS。
4. 成功事件仍 append-only；将服务端冻结的 `actor_user_id` 加到同事务既有 `AuditEvent.detail`（service.audit 支持任意 detail），继续保存 actor_session_id。operator 继续作为自报说明，不冒充认证身份。无需为本轮添加表字段/迁移，也不修改旧 history 八键；不能靠之后 session.user_id 反查历史操作者。
5. 这是**账户 ID 意图 CAS**，不是服务端认证代次令牌。UI 自身 A→B→A 的旧确认由 R96 epoch/signal 撤销；只靠此 header 不能证明同账户从未登出重登。若独审要求跨页面/跨客户端同账户认证代次也使所有旧意图失效，应先单独冻结带服务端 generation/intent 的版本合同，不能偷偷增第七个 body 键或声称库存 header 已做到。
6. Native 当前只在密钥 inventory GET 允许该 header。若接入 Native，仅为规范化的上述 binary review POST 精确放行单值安全 ID，维持其它 path/method/query/header 拒绝；不泛开 `/v1` 写入权限。先完成 exact policy 正反例再让 SDK/UI 使用。

**保持不变：** POST 不 fetch/parse/采纳；只允许 row_loss/field_loss；24h、最新 revision、keep 撤销、一份批准仅在未来新在线 run+新 capture+同完整 binding 下消费，use 与正式事实/通知同事务。当前未定义 Idempotency-Key；缺少幂等协议本身不是 bug。旧 revision 重试应 409，不能自动改 revision 后重发。

## Task 1：最小 SDK 与隔离页接线

**目标文件**

- Modify：`packages/domain-types/src/index.ts`、`packages/api-client/src/index.ts`、`apps/web/components/source-quality.tsx`。
- Create：`packages/api-client/src/quarantine-review-v2.ts`、`packages/api-client/tests/quarantine-review-v2.mts`、`apps/web/components/binary-quarantine-review.tsx`、`apps/web/components/binary-quarantine-review-context.ts`、`apps/web/tests/binary-quarantine-review.test.ts`。
- Read/reuse：R96 `raw-evidence-v2.tsx`、`raw-evidence-v2-context.ts`、`auth.tsx`、transport authority observer；旧 `quarantine-review.tsx` 保留 text 合同。实施前遵守 apps/web/AGENTS.md，读安装 Next 的相关 guide。

1. 添加独立 binary DTO、严格 closed decoder 和新 V2 SDK 方法：精确路径/查询、六键请求、账户 header，完整校验 16/10/3/6 键及有限枚举、整数/64hex/固定 MIME/null。错误处理兼容 detail 对象、字符串和 FastAPI 数组；旧两 SDK 方法不改成隐式 V2。方法名为新增设计，不能在实施前当成现有能力。
2. source-quality 为可审 binary vehicle 的 **row_loss 与 field_loss 两类原因**接新表单；当前 `quality.py:183–190` 把两者都放在 `kind="field_loss"`，应按 `reason_codes` 区分 `row_loss_threshold/field_loss_threshold`，不能寻找不存在的 `kind="row_loss"`。`vehicle_quality.py:18–29` 对 vehicle/trims/fitments 分组计算丢行和丢字段，`quarantine_review.py:128–141` 两原因都允许；两者及其组合均覆盖，不无意收窄。RejectedObservation/结构解析失败继续不可人工跳过。服务端 can_approve 不含当前用户权限，写入须 `ready && authenticated && admin && currentBasis && freshlyConfirmed && !busy`，不照搬旧表单 ready=false 仍宽松的逻辑。
3. 将已展示的完整 metadata 深复制冻结，复用 R96 canonical 比较（对象键排序、数组有序、null 保留）。核 review.quarantine_id/detail.id、baseline/detail.previous_snapshot_id、comparison.candidate/detail.vehicle_payload，以及 detail/raw_evidence 全部共享归属和完整 parser/provenance；binding_hash 直接提交服务端原值。row_loss 对照以稳定 ID 找出缺失的 trim/fitment，候选侧显示“记录缺失”，不得当成字段对象解引用；field_loss 保留真实 null/字段缺失并显示“字段缺失”，不以 baseline 值补齐。当前完整 comparison.candidate 是 row.payload 字典（quarantine_review.py:242–273），且结构门要求 fitments 长度 1–100（:191–200），所以根 candidate=null 或 fitments=[] 是合同/结构失败，不能渲染成可批准的“全部丢行”；不放宽 decoder 接受它们。任一字段变化就清确认并重新读取，不能以相同 PDF hash 代替完整绑定。
4. detail/read/review/action 共用 ownerSignal、同步 ownerEpoch/current-owner、transport epoch 和当前选中记录 generation fence。关闭/切记录或来源/刷新/unmount/auth 开始/transport 变化立即 abort 并清提交资格；迟到 GET/POST/finally 不复活旧 UI。表单展示当前认证账户与自报 operator 的区别。
5. 409 binding/revision/actor 变化：重新 GET、重新核对原件和对照、人工重新确认；不自动 POST。网络断开/abort/丢响应显示“提交结果待核对”，只读 GET 查真实 state/history；不声称已取消服务器写入，不凭相同 action/operator/reason 认定是本次成功。history 没 actor，不能伪造本人归属或幂等 receipt。
6. 清晰呈现 pending/restricted/stale_baseline/kept_quarantined/expired/approved_waiting_online/applied_on_online_fetch；批准文案说明“24h 内后续新在线请求可尝试一次采纳”。原件可读取、capture receipt、质量批准均不等于来源许可、正式事实、Golden 人工真值或 Parser 发布批准；不新增在线采集按钮绕门。

## 最小验收、受管入口与回滚

后续执行先给新受管入口做源码/argv 独审，绑定届时 source 和新私库/新 artifacts；**不改旧 wrapper/pins，不直接裸 pytest/Node/tsc 绕现有受管机制。** 新候选入口尚未创建，不能把本文当作已可执行脚本。

入口挂接：先核现有 `scripts/run_api_worker_regression.py` 的允许目标范围，能合法选择的既有模块使用其精确 module/nodeid 选择；新增 boundary 模块及 SDK/UI/Native 目标若不在范围，另建精确候选 wrapper、列 literal argv/私有输出/子进程清单并先独审，不修改旧授权来“顺便放行”。R95 的 `scripts/regression_children.py`、`scripts/regression_node_guard.cjs`、`scripts/run_api_worker_regression.py`、Guard/ACL/pins 保持；其三个 literal 子进程授权不能泛化为本轮 API/Node/tsc/build。候选命令和计划中的 PASS 均不算已执行。

- API：新 boundary 测试 + `test_vehicle_binary_approval.py`、`test_vehicle_raw_v2.py`、现有 auth 同 cookie rebind 目标；核上面两个用途门、缺/重/坏 header、A 表单在同 cookie 变 B 后拒绝、锁内账号变化 barrier、并发同 revision 至多一写、旧 binary/no header 拒绝、旧 text 兼容。审查 PG 行锁生成与顺序；没有活 PG 运行不得宣称 PG 并发已验收。
- SDK/helper：严格合同单字段漂移、额外键/畸形/错目标、相同 hash 不同 capture/mapping/parser/source、对象仅键序不同、数组顺序不同、row_loss 的候选缺行与 field_loss 的候选字段 null/缺失分别渲染且不补旧值、根 candidate=null/空 fitments fail closed、owner/transport A→B→A、POST 丢响应与冲突不自动重发；旧 text tests 回归。
- UI：私库受审 HTTP fixture + 浏览器实际点击，桌面及 390/320px；row_loss/field_loss/两者组合各一例，admin/非 admin、用途 403、质量 restricted、成功后待在线而非已采纳、keep 撤销、过期、迟到/关闭/切账户/切记录。Mock/helper/build 不代替实际 UI/API，编译不代替 Native 真设备。
- 构建：最小涉及 web/desktop/mobile 的 TypeScript 与三端生产构建；若改 Native header policy，补 Rust/Java 精确 policy 目标。成功计数以实际新回执为准，不继承 R90/R96 历史通过数。
- 回滚：先保存本轮精确 before 字节与 hash；仅按本轮 diff 恢复新增 SDK/UI/Native 接线，恢复 binary“审批界面尚未接入”。用途门与 actor 安全收紧不应因 UI 回退一并移除；若 Task0 自身错误，停 binary 写入并单独修复，保留已经 append 的 review/audit/use，不删除历史、不改正常库、不 reset/stash/clean 他人 dirty。

完成标准：Root 独审通过 Task0 合同后才实施；新运行证据分别支持 API、SDK、UI、Native policy 层级。本文冻结本身只完成下一步设计，不关闭完整 V1、来源许可、真实在线/Provider、正常库迁移或设备验收。
