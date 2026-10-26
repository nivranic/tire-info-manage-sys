# R96：Raw Evidence V2 共享界面与 Native 保存实施计划

**Goal:** 将冻结 PDF 合同 §5/§6、P6/P7 的 V2 原件读取接入全部现有车型/收件/隔离展示入口，并在浏览器交付和 Native 不可逆写入前建立可验证的上下文门。

**Architecture:** 复用现有六个 V2 SDK 方法、严格 decoder 和通用 Blob 保存桥，新增共享 reader/view；一次读取或下载的同一个同步 fence 贯穿 SDK 与保存，ownerSignal 立即撤销待保存操作。Native 另外持有独立下载 authority 和单用 opaque lease，在身份请求入站/结束及生命周期变化时失效，身份请求 pending 期间拒绝新保存；系统选择器返回后的 publication gate 把操作转 committing，作为不可撤销提交授权点。JS 检查不能代替宿主门。

**Tech Stack:** React 19 / Next 16 / TypeScript 5.9、共享 API/native-client、Tauri Rust、Capacitor Android Java；现有 Node test、私库 FastAPI HTTP、Chrome CDP、离线 Rust/JDK 21 harness。

日期：2026-10-20。本文是**静态实施计划，不是运行回执**。按 `writing-plans` 方法写文件级任务；执行由 Root 按已授权 `do` 流程协调实现、独审和验收，不另建 worktree、不提交推送、不再询问 Key/URL/批准。文件名带“新增候选”的脚本/模块目前尚不存在，创建、独审并绑定真实源码后才能成为可运行入口；下列现有命令也没有因写入本文而获准或已经运行。

## 基线与范围

- 依据 `docs/plans/2026-10-19-official-vehicle-pdf-contract.md`，不修改冻结合同。R95 基线为 `.artifacts/r95-close-b65e1fa8d043/verification-final.json`，31164 bytes、SHA-256 `fc7aae8b1435609278f9f925cd7c88654e8ed6326bdc8741b69f12707aa1b991`；Root 本轮重新核 96 bindings / 688 source，0 drift。实施前再次冻结本轮受影响文件及已有 dirty 完整字节。
- 保持 SDK decoder、旧 text API、8 MiB SDK 上限、Native 32 MiB 上限及现有 GET/header/MIME/path 策略。三类 V2 detail/content 的 canonical GET 已在 Native 策略覆盖，**不修改** `security.rs`、`NativePolicy.java` 来扩大权限。
- R95 的 `scripts/regression_children.py`、`scripts/regression_node_guard.cjs`、`scripts/run_api_worker_regression.py` 和全部旧 pins/source/回执保持原字节。R95 的三个 literal 子进程授权不能泛化成 npm、tsc、build 或本轮 harness；本轮采用独立、精确绑定的入口，先静审再运行。
- 只读展示/下载不触发在线采集、重解析、质量批准、正式事实、OE/SKU 关系、Provider 或导出授权。`capture.receipt_only`、`quarantine.accepted:false`、`local_snapshot` 保持。无 PDF iframe/object/embed、缩略图或 `content_path` 直链。
- 完整 V1、真实来源许可/新在线 capture、PG/正常库升级、Provider 与发布仍开放；不因本轮成功改变首代 ready/fetch 和许可门。`apps/mobile/ios` 当前不存在，本轮不声称 iOS 实现或设备验收。

## Task 1：共享 V2 reader、展示与下载身份

**Files**

- Create（新增候选）：`apps/web/components/raw-evidence-v2.tsx`、`apps/web/components/raw-evidence-v2-context.ts`、`apps/web/tests/raw-evidence-v2.test.ts`。
- Modify：`apps/web/components/auth.tsx`、`apps/web/components/workbench-platform.tsx`、`packages/api-client/src/index.ts`（仅同步 transport authority observer，由 UI worker 负责）；按实际布局最小修改 `apps/web/app/globals.css`。
- Read：`packages/api-client/src/raw-evidence-v2.ts`、`packages/api-client/src/index.ts`、`apps/web/AGENTS.md`，以及本地安装 Next 的相关 agent guide。

1. 先为纯上下文/身份 helper 写失败用例，覆盖当前 owner、同步 `isCurrentOwner(epoch)`、选中记录/组件 generation、operation controller/signal、公开 `apiTransportAuthorityEpoch()`；同 ID 的 A→B→A、重复下载、关闭、卸载、auth revalidation 开始均使旧操作失效。依赖实时 ref/同步 owner 检查，不能只用旧 render 闭包中的 `ready` 或等 effect cleanup 才失效。
2. AuthProvider 新增当前 `ownerSignal`：`begin()` 和 unmount 同步 abort 旧 owner controller，再更新 epoch/ready；公共 reader 把该 signal 立即连接到 operation controller，已 aborted 的 signal 直接阻止启动，结束时拆监听。不能等 React effect 下一 tick 才撤销 Native picker。`packages/api-client/src/index.ts` 为现有 `apiTransportAuthorityEpoch()` 增加极小同步 observer：`setApiTransport` 安装和有效 restore 每次递增 epoch 时，在同一调用栈通知现有订阅者；reader 在启动操作前订阅并捕获 epoch，通知中同步 abort 自己的 operation，结束时解绑，不能只在保存 await 返回后才发现 transport 已变。observer 不修改 SDK decoder、请求或网络权限；Native picker pending 期间也必须经 AbortSignal 立即 release。共享 reader 以 `vehicle | capture | quarantine` 和固定 ID 选择对应 V2 方法，必须传 `RawEvidenceContextFence`；同一操作把同一 fence 原样传入 SDK 和 `saveDownload`。metadata/read/download 各自拥有 controller，选择变化与关闭同步递增 generation、abort 并清空；`details` 收起若未 unmount，须在 `onToggle` 主动 abort 活动 read/download，不等卸载；旧 finally/error/success 均不得恢复 state。`auth.ready=false` 当次 render 就隐藏旧内容、禁用下载。
3. 显示 text 时继续 `<pre>` 纯文本；binary 显示“PDF 原件”、真实 `byte_count/raw_hash`、source/source_url、观察/核验时间、parser version/identity、parse_method/mapping、已有 locator。字段为空表示未解析，不推造成功。车型定位从已有冻结结构取值；capture/rejected 无 locator 时明确未提供，不解析 PDF 补造。
4. metadata 展示成功时深复制并冻结 `{endpoint,metadata}` 的完整展示依据。比较采用递归稳定排序 object key、保留 array 顺序与 null 的闭合 JSON canonical 值，不能直接依赖响应 JSON 键序；下载只通过对应 `*EvidenceContent`，取得 `{blob,metadata}` 后与此完整依据比较。覆盖全部 raw V2 十键、endpoint/id、source_id/source_url/observed_at/parser_version、完整三键 parser_identity、snapshot_id/vehicle_id 等归属及 mapping/provenance；同 PDF/hash 但 capture/mapping/parser/source 变化也拒绝。为避免悄悄改变展示，本轮对 query_state 等非身份状态同样保守比较：任一字段不同即拒绝保存，清除旧下载资格并提示重新读取，绝不用新 metadata 覆盖旧展示后续存。仍保留宿主的事件/来源冻结约束。成功后以固定前缀＋经过 SDK 验证的 hash 生成 `.pdf` 文件名。
5. `SaveDownload` 增加可选同步 `assertCurrent?: () => void`，V2 必传；旧 caller 保持可调用。浏览器在 `createObjectURL` 前、`link.click()` 前检查 signal＋assertCurrent；URL 一旦创建立即进入覆盖 link 创建/append/最终 assert/click 的 `try/finally`，最终检查抛错也移除节点并 revoke 自建 URL，正常交付保留现有延迟 revoke。组件不持久化原件/Blob/base64 到 localStorage、sessionStorage 或离线包。

**Expected tests:** 纯 helper 对每个 fence 维度和 metadata 字段单独变更均拒绝（尤其同 hash 不同 mapping/capture/parser/source，及 query_state 单独变化）；仅 object 键序变化可接受，array 顺序变化不可接受。read/content await 前后、arrayBuffer/digest 后失效不能触发保存；transport 安装/有效 restore 同栈 abort，picker pending 时立即 dispatch release，不等待 save promise；解绑的旧订阅者不影响新操作，transport A→B→A 仍不能复活旧操作。assert 在 object URL 创建与 click 之间失效时 click=0、URL 被回收。保存失败/用户取消文案准确，不显示“已保存”。

## Task 2：迁移全部既有 UI 入口，保留业务绑定

**Modify**

| 文件与现有入口 | 接线要求 |
| --- | --- |
| `apps/web/components/workbench.tsx`：`showEvidence` 570/576、`EvidenceDetail` 854 | 车型支路改用共享 V2 reader/view；轮胎 `evidence` 及既有快照语义保持。关闭、切快照/查询、owner 变化清理，并保留焦点恢复。 |
| `apps/web/components/capture-journal.tsx`：41/47、89 | 详情接 `captureEvidenceV2`；receipt-only banner 和处理未确认文案保留，收到 bytes 不能被说成已采纳。 |
| `apps/web/components/source-quality.tsx`：101/106、188/197 | 详情接 `quarantineEvidenceV2`，binary/response_rejected 均保持未接受；详情和旧审批表单明确分支。 |
| `apps/web/components/interest-center.tsx`：257 | `vehicle_snapshot` 的 before/after 仍按事件冻结 ID/source/fingerprint 读取，车型改用共享 V2；禁止失败后改读 current。轮胎/目录/治理分支保持。 |
| `apps/web/components/golden-sets.tsx`：139 | capture 读取接共享 V2，保留 source/target kind/record.input.raw_hash 对照、人工真值/审核门；PDF 可核验下载不等于 Golden 已确认。 |
| `apps/web/components/parser-releases.tsx`：242 | capture 读取接共享 V2，保留来源/样本冻结 ID/评估绑定，不把 receipt 变正式真值，也不改变评估与发布批准门。 |

1. 逐入口先补可观察失败场景，再替换旧车型/capture/quarantine 调用；共享组件负责 bytes 展示和下载，各宿主保留自己的冻结范围检查与业务操作。
2. source-quality 的旧 binary 审批 UI 当前没有 V2 接线合同。本轮只完成读取/保存：binary 不请求或提交旧 `quarantineReview/reviewQuarantine` 表单，明确“此原件可核对，二进制审批界面尚未接入”；旧 UTF-8 审批仍走既有流程。该项在最终报告继续列未完成，不能声称审批/UI 全功能闭合。
3. 验证所有六处既有入口能进入共享 reader；不能只完成三个主面板便称所有 UI 闭合。对整轮实际修改后再做限定源码检索，列仍保留的旧调用及合理用途，不修改无关轮胎/召回页面。

**Expected tests:** 三主入口和三个旧调用者的 binary/text 均可读；binary 不出现 TEXT/null 正文、不内嵌 PDF，不产生旧审批 POST。source/冻结事件 hash 不匹配、403/404/409/503、关闭后迟到和账户切换都失败关闭；旧 UTF-8 审批、轮胎纯文本保持。

## Task 3：共享 Native 保存协议与 JS fence

**Files**

- Modify：`packages/native-client/src/index.ts`、`apps/mobile/src/native-platform.ts`。
- Test：`packages/native-client/tests/transport.test.mjs`、`apps/desktop/tests/native-platform.test.mjs`、`apps/mobile/tests/native-platform.test.mjs`。
- Read：`apps/desktop/src/native-platform.ts`（当前泛 `invoke` 已可透传，只有实际类型/接线需要才修改）。

1. 沿通用 `save_download` 封送新增宿主 lease 字段；新增候选内部命令名定为 `prepare_download`、`release_download`，Capacitor 对应 `prepareDownload`、`releaseDownload`。不是新增 raw 专用 bytes 协议；原 filename/mime/body_base64 校验和限制保持。
2. `NativeDownload` 同样增加 optional `assertCurrent`。所有旧 JS caller 通过统一 `createNativeSave` 自动 acquire lease；V2 caller 另必传自己的同步 fence。顺序固定为：检查 → await prepare → 检查 → arrayBuffer 前后检查 → base64/最终 IPC 前检查 → `save_download(lease,...)` → await 后再检查。任何 await 的 catch 也先按同 fence 判当前，不能把过时结果误显示成功。
3. 为 AbortSignal 安装立即 release 监听器：lease 到手后若 signal 已 aborted 立即释放，否则监听 abort；**save/picker pending 时也立即发 `release_download`**，不能只等 save resolve 后 finally。prepare 已发出但 reply 迟到时仍释放其 lease。完成后拆监听并在 finally best-effort 幂等 release；cleanup 失败不能覆盖原始取消/写入结果。ownerSignal、关闭/selection/repeat 都同步 abort 对应 operation；release 不能抹掉已提交写入的事实。宿主不支持 prepare 时失败关闭，不能降级为旧无 lease 保存。
4. 更新移动插件精确方法/参数映射和安全固定错误码；不把 native 异常中的本机路径、cookie、lease 内容带入 UI/日志。现有旧调用者测试适配 prepare→save→release 的新顺序。

**Expected tests:** prepare await 后、arrayBuffer 中、最终 IPC 前 fence 变化，save IPC=0；prepare 后中止会 release；picker pending 时 abort/ownerSignal 开始立即 dispatch release，且不等待 save promise；同 fence 成功保留每字节。取消 picker 返回 saved:false；IPC 迟到不能恢复旧 UI。Node mock 仅证明 JS/adapter，不能证明宿主零写入。

## Task 4：Rust / Android 下载 authority 与宿主提交门

**Files**

- Create（新增候选）：`apps/desktop/src-tauri/src/download_authority.rs`、其纯测试 `apps/desktop/src-tauri/src/download_authority/tests.rs`。
- Modify：`apps/desktop/src-tauri/src/lib.rs`、`apps/desktop/src-tauri/src/bridge.rs`；复用 `bridge.rs` 的 ABA/publication 思路，不把 `SessionFence` 当账户 fence。
- Create（新增候选）：`apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile/DownloadAuthority.java`、`apps/mobile/native-tests/DownloadAuthorityTest.java`。
- Modify：同 Java 目录的 `TireNativePlugin.java`、`NativeHttpBridge.java`、`DownloadJob.java`；Test：`apps/mobile/native-tests/DownloadJobTest.java`。

1. 先实现可独立测试、生产实际调用的 authority：独立 revision＋document/lifecycle 身份、随机 opaque lease、有界 pending 表/单调时钟 TTL/过期清理，`prepare → reserve → commit → finished/released` 单用阶段；错误/取消/重复 reserve/过期/旧 revision 均拒绝。unknown/repeated release 幂等且不延长 TTL、不遗留 busy，所有出口释放资源。Rust `Bridge`/`NativeState` 共享同一 `Arc` authority；Android authority 由 application-owned `OfflineRuntime/NativeHttpBridge` 唯一持有，plugin/document 使用宿主 document token 绑定 lease，不能各自建纯测试孤岛或让重建插件拥有另一账户 authority。document 结束只撤该 document 的 leases，auth/config/reset 撤全局。计数回绕必须 fail closed/换 authority 身份，不能让 A→B→A 复活旧 lease。
2. 精确身份请求 classifier 使用**已验证并规范化的 method/path**：现有 Rust `validate_request` / Java `NativePolicy.request` 验 decoded path 却保留 raw encoded path，classifier 必须先去 query、严格单层 UTF-8 percent decode route 后再比较，不能只比 raw 字面串。匹配 GET `/v1/auth/me`；POST `/v1/auth/register`、`/login`、`/logout`、`/profile`；POST `/v1/auth/users/{id}/role`、`/password`；DELETE `/v1/auth/users/{id}`。入站、排队/网络之前以独立 ticket 登记 identity pending 并递增 revision，结束/失败/取消/排队拒绝必须由 finally/drop 再删除自己的 ticket、再次递增 revision；任一 identity ticket pending 时 prepare/reserve/commit 一律拒绝。并发旧请求 finally/drop 只能清自身 ticket，不能清新 epoch 的 pending/busy；失败也不恢复旧 lease。对其他用户管理操作可同样保守撤销，不读取 cookie 猜当前用户。无效/嵌套编码/encoded slash 路径仍按既有策略拒绝，不能因此获准网络访问。
3. Rust 在 `bridge.rs` 入站共享同一 authority；`lib.rs` 注册 prepare/release，复用 `lib.rs:991` 的 `on_page_load Started` document hook。Android 在 `apiRequest` 入队前处理全局身份失效，复用 `TireNativePlugin.java:85 documentStarted`，并在 `handleOnDestroy` 结束本 document。reset（包括异步 owner DB、控制队列、registry/session 工作）必须在首个 await/排队前取得同一 authority 的 transition ticket：begin 时全局撤销并增加 pending，整个过渡期间 prepare/reserve/commit 在 authority gate 内拒绝；成功/失败/取消/排队拒绝的 finally/drop 仅清自己的 ticket，并再次撤销。实际含异步身份替换的 recover/config 也使用该 begin/end ticket；不能只在过渡开始撤销一次，也不能以 gate 外预查 `offlineResetting` 代替原子 pending 检查。纯同步 document 代次切换只需撤本 document；teardown 关闭对应 document/authority。prepare 与 save 必须来自同一插件/主文档，旧 document token 不能复用。测试须把 reset/recover/config 停在中间 barrier，确认新 prepare 和旧 reserve/commit 均拒绝，结束/失败后旧 lease 不恢复。
4. `save_download` 必须带旧步骤 issue 的 lease，不能在 save 到达时才捕获“当前 revision”。入站 reserve 单用 lease 后显示既有系统选择器；选择器取消/错误即 release。选择器返回并验证名称后，在**独立 publication gate** 内最后核 lease/revision/无 identity pending、转 committing，再释放 gate，由拥有 bytes 的 worker 开始目标 open/create/truncate/write。转 committing 就是不可撤销提交授权点；gate 仅保护撤销/领取/阶段转换，session/registry/插件主线程锁不能跨文件系统或 SAF 流 I/O。
5. 线性化语义：失效/release 先于 commit 授权，则本应用 Destination.open=0、写入原件 bytes=0；commit 授权先胜，则后续即使尚未发生实际 OS open 也不承诺能取消，可能产生部分/完整文件，不能声称回滚或零字节。宿主完成仍不授权旧 JS 显示结果。Android 保留 `DownloadJob` 已有 chunk 取消、单次 settlement 和“运行中的 bytes 仅 worker 归零”所有权；不能在 provider 忽略 interrupt 时提前擦 bytes。`ACTION_CREATE_DOCUMENT` 提供方可能在用户选择时创建空 document；本应用的零 open/write 保证不能扩大成全系统零创建。

**Required pure/integration assertions:** 同 cookie login/logout、GET me revalidation 开始/结束/失败、role/password/delete、reset/document/config/teardown；`/v1/%61uth/%6cogin`、`/v1/auth/%6de` 和合法 query 都不能漏失效，嵌套编码/encoded slash 继续拒绝；auth 先入站而旧 save 后到；pending 期间 prepare/reserve/commit 拒绝；并发身份 ticket 旧 finally 不清新 pending、请求结束再次失效；同 cookie ABA；旧/伪造/重复/过期/已 release lease；picker 返回前失效；reserve 后 commit 授权前失效；这些提交前撤销场景都应用 open/write=0。commit 授权后、实际 open 前再取消也单列非 rollback，不要求零写；保留现有阻塞 provider/部分 chunk 场景。

## Task 5：独立精确验证入口与证据

**新增候选脚本**：`scripts/raw_evidence_v2_frontend_verify.mjs`、`scripts/raw_evidence_v2_web_fixture.py`、`scripts/raw_evidence_v2_web_ui_qa.mjs`、`scripts/raw_evidence_v2_native_verify.py`。先编写完整限制与子进程 literal、独审、Root 绑定新鲜输出与源码 SHA，再运行；不复用/改写旧轮输出或 R95 Guard。

| 分组 | 实际入口/最小内容 | 成功标准与边界 |
| --- | --- | --- |
| 四份 TypeScript | 现有 `node node_modules/typescript/bin/tsc --noEmit --incremental false -p apps/web/tsconfig.json`；同形依次换 `apps/desktop/tsconfig.json`、`apps/mobile/tsconfig.json`、`packages/native-client/tsconfig.json` | 各 exit0、保存 argv/cwd/source before/after；这不是 SDK `.mts` 独立类型检查，也不启动 API。 |
| Node 目标测试 | 现有 `node --test packages/native-client/tests/transport.test.mjs apps/desktop/tests/native-platform.test.mjs apps/mobile/tests/native-platform.test.mjs`；新增共享 helper 测试沿 web 现有 `--experimental-strip-types` 入口，文件存在后绑定 exact literal | 运行实际生产 helper/bridge，不重写一份模拟 authority 当预期；用例、exit、失败都留存。 |
| 三端前端构建 | 独立 wrapper 参照 `scripts/frontend_round49_build_evidence.mjs`；desktop/mobile 用现有 Vite CLI、分别 cwd、`--outDir` 指新 GUID artifacts；web 用 `TI_NEXT_DIST_DIR=.next-r96-<guid>` 与私 loopback `TI_API_BASE_URL`，走现有真实 build 流程 | web/desktop/mobile 产物清单/hash 和 host fingerprint；先完整保存 `apps/web/public/icons`、`apps/web/public/favicon.ico`、`apps/web/public/sw.js`、`apps/web/next-env.d.ts` 的存在性/字节，finally 逐项精准恢复并核 hash。旧 `.next`/dist/文件不覆盖；构建不等于宿主或设备验收。 |
| 私 HTTP→SDK→React | 新 fixture 只借鉴 `scripts/api_key_inventory_web_fixture.py`、`api_key_inventory_web_ui_qa.mjs` 的护栏；新 GUID DB/object/bundle/tmp，import main 前清理 TI/TIRE/Provider/proxy 环境并禁 AI/embedding/observability；只允许两个精确、非正常端口的 loopback listeners；audit 拒外网/子进程/正常库 | 真实当前 FastAPI→SDK→React，桌面/390/320 像素，六入口、PDF bytes/hash、文本、拒绝码、错展示身份、账户/selection/重复/关闭/迟到、无横向溢出和可访问按钮；每个断言与截图绑定同 source/build。fixture HTTP/许可/响应是合成数据，单列真实 S2 历史 bytes 的离线 replay，不称官网/生产许可。 |
| Rust / Java 宿主 | 新 wrapper 使用离线 Rust 1.95.0 / JDK21、已有 JUnit4；实际编译生产 `download_authority.rs` / `DownloadAuthority.java`，生产 `DownloadJob` 继续执行既有场景；路径/编译列表/cwd/输出在脚本创建后精确绑定 | 并发 barriers 控制 revoke/commit 顺序，真实生产 authority 的 open/write spy 计数、单用/ABA/生命周期全过。不能在 `.artifacts/r80-native-2b63376f017c4a5ba149544250b2337d/verify_native.py` 原地重跑。纯模块不能证明 Rust lib/bridge、Java Plugin/HttpBridge 整集成代码已编译；完整宿主编译与 Tauri picker/WebView2、Android SAF 真设备分别记录。 |

私 fixture 若还需 parser 实际 child 才能构造真实 S2，须另立明确受审入口；不能在默认“child forbidden”护栏里临时放开。优先只读使用已核历史 bytes/receipt，明确 replay 的范围。若缺本轮生产 UI 构造所需字段，则停止该用例并报告缺口，不能退为页面全 Mock 后称真实 HTTP 完成。

运行记录使用全新 `.artifacts/r96-<scope>-<guid>/`，保留 stdout/stderr、真实退出码、source before/after、bindings、资源首尾/监听/子进程与清理结果。失败保留原回执，不补填未发生的 after、cleanup 或“0”。任一非预期源码漂移/正常资源访问/外网尝试停止该入口，先独审修正，不扩大预算或权限掩盖。

## Task 6：闭合、交付与回退

1. 独审核查本计划全部六入口、同 fence 与展示 metadata identity、宿主 lease issue 时点和 picker 后 commit，特别审查“auth 先到、旧 save 后到”和 JS abort 被误当写入回滚。按必要性运行目标现有 API 合同回归；若需要进入受管 API/Worker，只能调用已有审定 exact target，不修改其策略来承载前端工具。
2. 只在真实结果齐备后新增本轮 evidence/report/seal，并在 `docs/HANDOFF.md` 顶部追加本轮当前入口；旧全文/旧 seal/pins 原字节保持。报告分别列静态、Node、四份类型、三前端构建、真实私 HTTP/React、真实 S2 离线 replay、Rust/Java harness、完整宿主集成编译、真实宿主/设备实际做到的层级。“整宿主集成代码编译未验证”与“设备未验证”分别写，不能以纯模块绿代替前者；binary 审批 UI、iOS 与上述完整 Goal 的开放项继续列出。
3. 回退不涉及迁移/正常库：按实施前保存的完整字节与本轮精确 diff 撤销自己修改；新文件仅在确认无后续引用/并行改动后处理，逐块保留他人 dirty。前端公共 reader 可切回旧 text caller，但 binary 必须继续明确不支持，不能显示空正文成功；Native JS/宿主 lease 变更成对部署/回退，版本不匹配失败关闭，禁止无 lease fallback。所有验证/失败历史和保全副本保留，不 reset/clean/stash/commit/push。
