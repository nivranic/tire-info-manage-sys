# 第 97 轮：二进制审批 API 用途与账户边界

开始日期：2026-10-20；收口日期：2026-10-21（Asia/Hong_Kong）。**R97 仅 Task 0 后端切片按本文所列证据收口：boundary 25/25、compat 95/95，最终 120 个互异目标通过。** 原计划整体、Task 1 与完整 V1 没有完成；Task 1 尚未实施，V1 继续 active。四次失败/不完整诊断全部保留。Root 已核实际结果与 694 当前输入并明确接受此切片；本轮新 final seal 的最终逐 binding 独立复核仍待 Root 执行，不把它写成已经完成。

## 本轮范围与当前状态

本轮只处理 binary quarantine review API 的原 Q/正式 baseline 双用途门、`X-Tire-Expected-Account` 账户意图、写锁内重新判权，以及真实 `actor_user_id` 审计。设计依据为 `docs/plans/2026-10-20-binary-quarantine-review-ui.md`；Root 在 `.artifacts/r97-design-readback-20261020/review.json` 接受 Task 0 优先实施。

| 层级 | 当前证据与限制 |
| --- | --- |
| 生产与测试实现 | 后端 before、diff、最终静态证据位于 `.artifacts/r97-backend-eeb2212e7bc14afc8068460f41e16d07/`。源码已改，不等于动态验收。 |
| 独立源码审查 | `.artifacts/r97-review-d87122a5dea041d0bfea68bfc23b9f9e/review.md` 和 `independent-static-checks-v2.json`；未发现阻止受管验证的本轮 P1/P2，属于限定静审结论。 |
| 受管入口审查 | `.artifacts/r97-runner-root-review-20261020/review.json` 接受初版固定 `scripts/binary_quarantine_review_verify.py`；后续只针对新 runner 私路径预算作最小修正并重新静审、freeze，未改生产/测试/fixture/Guard/旧 scripts。静审本身不执行产品。 |
| source freeze | 初版、短路径版与透明诊断版均已生成，绑定各自 wrapper/suite；最新为 `.artifacts/r97v-903d7fe1866c478e/reviewed-sources.json`，134429 bytes，SHA-256 `30b56cc8f3de238d82e9bdb999a94a852e816b2bd31a696f8c5809de8b70d2ca`。历史 hash 与逐版差异见下。freeze 不运行产品或 pytest。 |
| boundary 首 run | `.artifacts/r97-verify-6b41b83ef3dc47fa8cf4a90a59323637/result.json`：runner 3 / pytest 1，25 项中 3 passed / 22 call failed；22 红停在 loss 链首 baseline live 断言，只读私库确认为 `parser_bundle_missing`。 |
| boundary 短路径 run | `.artifacts/r97v-75a129f633a74fd0/result.json`：仍 runner 3 / pytest 1，25 项中 3 passed / 22 call failed，child 0；代表私库现在为 `vehicle_source_fetch_failed`，只确认越过旧 bundle 注册断点，未通过审批边界。 |
| 单目标透明诊断 | `.artifacts/r97v-8025794d714c4ab7/result.json`：1 unique/protocol/call，setup 1P / call 1F / teardown 1P，runner 3 / pytest 1；41 条观察、observer error/overflow 0。固定私有 object link 处 PermissionError，详见下节；该次没有到达审批行为断言。 |
| 执行上下文对照 | `.artifacts/r97v-9a2aee127f2f4d15/result.json`：同 `72e3047d…` wrapper、同 freeze 与同 nodeid，pytest 0、三阶段各 1P、2 parser child exit 0/live 0；observer 保留 128 条、丢弃 335 条，所以 runner 3 / passed=false，诊断不完整。 |
| 最新完整 boundary | `.artifacts/r97v-ce6b0c7af1a549f8/result.json`：同源 require_escalated、关闭观察器，runner/pytest 0、25 unique、三阶段各 25P、0 fail/skip/incomplete；44 managed_parser 全 exit 0/live 0。Root 已独核，实账见下。 |
| compat | `.artifacts/r97v-5ddc4715c22c4cdf/result.json`：runner/pytest 0、95 unique、三阶段各 95P、0 fail/skip/incomplete；130 managed_parser 全 exit 0/live 0，无强停。Root 已独核终态，替代此前进度状态；进度观察账原件不改写。 |
| Task 1 增补 | `docs/plans/2026-10-20-binary-quarantine-review-ui-addendum.md` 记录五项源码前置差异；原计划 hash 保持。SDK/UI/Native 接线仍未实施。 |
| 独立反模式 | 原 `report.md`/`verification.json` 保留；新 `report-v2.md`/`verification-v2.json` 对最小路径 diff 复核仍为限定静态 P1/P2 各 0，原 15 输入仅新 wrapper 已知变化，其余 14 不变。不代替动态验收；v2 未预先认可短路径 run 通过。 |
| 最终资源与绑定核对 | 最终 boundary/compat 同最新 freeze，自身 694 输入首尾稳定；Root 与文档侧均实算当前 694 输入 0 drift。各旧 run 自身稳定但 wrapper 有已知版本变化。新 seal 绑定现有证据与 HANDOFF 保尾结果；Root 对新 seal 的最终复核 pending。 |

独审执行前预计 **25 cases / 44 parser children**，早期两个失败 run 实际均为 25 collected / child 0，各 3 个通过项仅早期 admin 两例与 PG SQL 编译一例。最新完整 boundary 才实际达到 25/25 与 44 child，不能将它倒填给旧 run。旧两份 nodeids.json 字节相同；重复运行次数不能当作新增唯一目标。PG 项仍只编译 SQL，没有活 PG 连接或并发调度证据。

| 实际运行账 | 首 run | 短路径 run | 最新完整 boundary |
| --- | --- | --- | --- |
| result bytes / SHA-256 | 22870 / `fa182946090028df2e444c92a3a1980581c1391125d3214fb983db5824566bf6` | 22804 / `9249d80a7e1209311136d1c04cadc717df82d4939f2ead13f5e6685afe0357f7` | 34196 / `c9a8d34532ad34191a82311fec9b58dc4580db2bab9c3e74f1c3a4a282250241` |
| runner / pytest | 3 / 1 | 3 / 1 | 0 / 0 |
| collected / protocol / call | 各 25，unique 25 | 各 25，unique 25 | 各 25，unique 25 |
| setup / call / teardown | 25P / 3P+22F / 25P | 25P / 3P+22F / 25P | 各 25P |
| fail / skip / incomplete / reporting failures | 22 / 0 / 0 / 0 | 22 / 0 / 0 / 0 | 各 0 |
| 自身 source inputs 首尾 | 694 stable | 694 stable | 694 stable，同透明诊断 seal |
| parser children / live / owned cleanup | 0 / 0 / 无需回收 | 0 / 0 / 无需回收 | 44 全 exit 0 / 0 / 无 cleanup 动作 |
| SQLite | 24 已闭，forced close 0，errors 0 | 24 已闭，forced close 0，errors 0 | 29 在 final cleanup 前已闭，forced 0/errors 0 |
| resources_closed / 非 selfcheck 拒绝 / metrics | true / 0 / 0 | true / 0 / 0 | true / 0 / 0 |
| 正常库 / 真实外网或 Provider 调用 | false / 0 | false / 0 | false / 0 |

资源关闭与最新通过不抹去前两轮各 22 个 call 红；所有原结果与失败记录保留。前两轮没有启动真实 parser child，不以 ParserExecution 表存在一行冒称当时 child 已执行。最新 run 的 44 个 child 是本轮私库离线 S2 重放；不等同新官网 capture、正式来源许可、活 PG 或 Task 1 验收。R38 before/after pin 在最新回执中相同。

compat 实际 result 为 56895 bytes / SHA-256 `f938bd8d6255f67a13403cbeea0d87c35558b771ef5ad72c86e88762501cad7c`。95 collected/protocol/call/unique、setup/call/teardown 各 95P，0 fail/skip/incomplete/reporting failure；六模块为 approval 29、reparse 21、raw V2 18、旧 text 19、auth accounts 3、auth lifecycle 5。130 managed_parser producer exit 0/live 0，未强停；101 SQLite 在 final cleanup 前已闭、forced 0/errors 0；resources_closed=true、非 selfcheck 拒绝/metrics 0、正常库 false、真实外网/Provider 调用 0，R38 before/after pin 保持。

最终 boundary 与 compat 模块集合不重叠，共 **120 个互异目标、正式 174 parser children**；单目标上下文对照的 2 个 child 另记诊断，不加成正式 176。全部六 run 历史合计 172 次 protocol/call，其中 call 127P/45F、四个 runner 失败回执；这是重复执行账，不是 172 个唯一目标，也不能称历史一次全绿。`observed-evidence-v6.json` 从现有逐项 test reports 实算三阶段账并保留各 run 对应结果、资源与模块计数；没有重跑测试。

## 两轮失败诊断与验证路径修正

首 run 结束后，verify 对其 24 个已关闭私库仅使用 stdlib、`mode=ro&immutable=1` 读取固定枚举状态，首尾 DB bytes/hash 不变并显式关闭；22 个 QueryRun 均为 source_unavailable / `parser_bundle_missing`，capture/parser 执行总数 0。`.artifacts/r97-verify-09f0ad48b5124ebf817ae9df25456927/private-db-diagnostic-codes.json` 为 14467 bytes / SHA-256 `2385942ebbf5504e8bc33cd2fbc53a9f9378f0d7573d98ca408212c72c6d172d`。最初 `private-db-diagnostic.json` 20396 bytes / `5ce9c9f8e2fd046d00dd79d10757e071eb156ec58ce9612101237b43efe56802` 因 allowlist 缺 BundleError 而隐藏具体 reason；原件保留，后来的固定码展开不覆盖它。

代表私库 registered bundles/deployments 为 0，但私有 sealed manifest/package 均存在。manifest 的 142 文件中，普通 Path 有 32 项 ENOENT（errno 2 / WinError 3），同一受限私路径的扩展长度前缀则 142/142 存在；最长绝对路径 277 字符，DB hash 保持。代表诊断为 `representative-bundle-diagnostic.json`，3738 bytes / SHA-256 `e63d176e876a3187f0d4351f4305de124f4a800660f64415f9aaf9c3af783b78`。这些是路径可见性观测，不把根因归为权限、sandbox 或 object store。backend 静查确认 fixture 的 bundle root 覆盖生效，新增 fixture 仅授本地用途 helper，未破坏注册 env。

Root 随后只授权缩短新 runner 的私有输出/seal 根 basename：`r97-verify-32hex` → `r97v-16hex`，仍为 `.artifacts` 直接新子目录；Windows 在 mkdir/bootstrap 前按固定受审 suffix 188 字符与上限 259 拒绝超预算。受审当前根长 68、静态预算上界 256。此改动不变 suite/fixture/64与256 child budget/8秒 parser 限制，不放宽 Guard/ACL，不采用 escalation；只是本轮固定矩阵的验证路径预算修正，未完成生产通用长路径适配。

短路径 run 的代表私库只读诊断为 `short-run-private-db-diagnostic.json`，902 bytes / SHA-256 `11735d45098776596d545431a0502e7a505cf31e2bb8a6c442eee496f190b529`；DB bytes/hash 首尾相同、连接显式关闭。QueryRun 现为 source_unavailable / `vehicle_source_fetch_failed`，capture 0、ParserExecution 1、registered bundle 1、deployment 1。另 `short-run-execution-diagnostic.json` 记录该 execution 为 not_started、error_code 同上、receipt 字段 0；它与 runner child 0 一致。这只证明代表链越过了旧注册断点，不能据此声称路径修复、parser 调用、完整 baseline 或审批 API 测试通过。其后新增下述受审透明单目标诊断，未扩大 8 秒限制或修改生产来源。

## 单目标透明诊断与上下文对照

为定位原 parent catch 前的失败，新 wrapper 只增加受限观察器与唯一固定 diagnostic nodeid：`test_vehicle_binary_review_boundary.py::test_postcommit_response_permission_failure_preserves_committed_review_and_real_actor`。诊断 child budget 为 4，仍只允许 managed_parser、并发 2、现有 8 秒限制；原 boundary/compat 目标和通过判据不变。观察器不包装或替换产品函数、返回值、参数或异常，仅对白名单源函数记录阶段、行号、异常类型、数值 errno/winerror、允许的 code 与路径长度/私有分类；不输出原路径、异常 args/message、body、cookie 或环境值。观察器错误或 overflow 均会阻止 passing receipt。

独立静审 `.artifacts/r97-diag-review-e3d7d2c8ed9f48c3aa98433e78d2b32b/static-review.md` 的最终 SHA-256 为 `48ad2ef40315f6ac3700d636901d17e356196dbdb217cec1179f602f10ec26bb`，接受新 freeze 与该唯一目标诊断，未把其当作运行通过。新增 wrapper 为 25613 bytes / `72e3047d3517afd795d13fd82228172300b3d88719d2ed6845011fb2cba4238b`；短路径旧全文 `10a09921…` 完整保存在诊断目录 `binary_quarantine_review_verify.before-observation.py`。

实际单目标回执为 `.artifacts/r97v-8025794d714c4ab7/result.json`，28542 bytes / SHA-256 `07dfe251e080de2d2fc02131c191e9ea3e58176a1978fb73b72d71fce2df54ab`：1 collected/unique/protocol/call，setup 1P、call 1F、teardown 1P，skip/incomplete/reporting failures 0，runner 3 / pytest 1。694 输入自身首尾稳定；parser child/live 均 0，1 SQLite 已由 producer 关闭、最终强制关闭 0、errors 0；resources_closed=true、非 selfcheck 拒绝与 metrics 0，正常库 false、真实外网/Provider 调用 0。该 nodeid 属于既有 25 项中的一项，诊断执行没有新增唯一验收覆盖，也没有执行到所期望的 commit 后行为断言。

观察原件 `stage-observations.json` 为 6668 bytes / SHA-256 `88d57663cccaa282ff54f27c875b51c1ef070af535de0c6d7eea7cdec0cb635d`：41 条、observer_error_count=0、discarded_events=0、observed_thread_count=1。S2 pre-use 的 UnicodeDecodeError 是 fixture 对二进制 UTF-8 解码的预期检查，随后成功返回，不能把它作为本次失败。确定的阻断观测在 `object_store.py:71` 的 `os.link`：PermissionError、errno=13、WinError=5；target 202 字符、temporary 157 字符，均为私有路径且低于 260，随后沿 ObjectStoreError → CaptureWriteError 返回失败。该证据没有识别具体 ACL、sandbox 或其他底层原因，不因 WinError 5 就归因某个权限层。

`fixed_error_code=null` 也不证明没有固定原因：ObjectStoreError/CaptureWriteError 本身无 `.code`，固定原因以 Exception args 表达；观察器按隐私边界不输出 args/message。`trace_uninstalled_before_receipt=true` 仅表示观察器已功能停用并恢复主线程 trace 与未来线程默认；不能作为所有既有线程全局 trace 引用已移除的证明。本轮没有线程生命周期验收。

同精确 wrapper、freeze 和 nodeid 的 require_escalated 执行上下文对照已终态，Root 已独核；文档侧实算两上下文 `source-before.json` 和 `nodeids.json` 均逐字节相同。对照 result 为 `.artifacts/r97v-9a2aee127f2f4d15/result.json`，37463 bytes / SHA-256 `6ddd2e383d7679eabd189efcda94756f6641880ca0bc7b47c13b9235eeb709ed`；`stage-observations.json` 为 14088 bytes / SHA-256 `b1b9abbaa88977c42d54197f3a25c3725faa5c08a0046aba530cd392279efe71`。

该对照唯一目标 pytest exit 0、setup/call/teardown 各 1P、无 fail/skip/incomplete/reporting failure；2 个真实 managed_parser child 均 producer exit 0/live 0、无 cleanup 动作。694 输入自身首尾稳定，1 SQLite producer 已关闭、forced 0/errors 0；resources_closed=true、非 selfcheck 拒绝/metrics 各 0、正常库 false、真实外网/Provider 调用 0。**整体仍 runner 3 / passed=false**：观察器达 128 上限，丢弃 335 条，observer_error=0、observed threads=2；这是诊断不完整，不能称单目标诊断全绿。后续完整 boundary 的验收必须引用其另立通过回执。

保留下来的前 128 条显示第一次 object_put 正常返回、私有 fetch 已返回 actual parser 结果，未再出现原有 object link 的 WinError 5；后续观察已溢出，不能补造缺失阶段。两上下文差异是当前已观测事实，仍不证明具体 ACL、sandbox 或系统根因，也不意味着 I/O 已修复。S2 UnicodeDecodeError 在两者均是预期检查，不能归为失败原因；trace 功能停用和既有线程引用限制同上。

Root 随后批准同源 require_escalated 的完整 boundary，关闭观察器；该组与随后获准的 compat 均已按上文终态通过。原 Guard/ChildPolicy、fixture、8 秒与源绑定保持既定约束。两轮完整 boundary 红、普通上下文单目标红及对照 observer 溢出均保留，不相互覆盖或改写；最新通过也不是底层 ACL/系统原因的诊断证明。

## 具体合同与证据含义

GET 与 binary POST 的 review facade 固定先检查原有完整性/provenance/quality/formal-baseline/15 键 binding，再分别对 fresh Q 与 fresh baseline 调用 `checked_vehicle_original_bytes(..., structured=True)`。每条记录均检查精确 row/capture/query/source/hash 的 `local_original_read` 和 `structured_fact_use`；两用途独立，Q 不借 baseline 的许可。用途拒绝保留固定 403，完整性异常保留 503。生产 pending 与 Provider/export=false 未因本轮开放。

binary POST 继续早期 admin dependency；匿名/非 admin 先以 `admin_required` 拒绝。只有 binary POST 要求恰一个 `X-Tire-Expected-Account`，匹配 `[A-Za-z0-9_-]{1,64}`；缺失、重复或畸形为 422 `review_expected_account_invalid`，与当前认证账户不同为 409 `review_actor_changed`。旧 UTF-8 请求保持既有合同；binary 旧直调缺 header 被拒绝是有意的安全收紧。

`lock_ingestion()` 自带先 commit 后加锁，因此真正身份检查必须放在其后。实现以 Session → User 顺序执行 FOR UPDATE + populate_existing，重新核会话有效期、绑定、User 存在、admin 与账户 header，并持锁到同一审批事务 commit/rollback。API/CLI reset 的 User → Session 局部次序依赖共用 ingestion 锁互斥；这是明确的源码维护约束，不能据此声称真实 PG 并发已通过。

审计仍为 append-only，同事务 review 与既有 AuditEvent.detail 增加冻结的真实 `actor_user_id`，保留 `actor_session_id`。`operator` 仍是自报说明；不能从之后可变的 Session.user_id 推回历史真实操作者。POST body 六键、响应十六键及 history 八键保持，不增加 actor 公共 history 字段、下载内容、本机路径或第七个 body 键；POST 不 fetch、parse 或直接采纳。

GET 无 admin 是既有 `local_workspace` 读取设计，单凭这一点不构成缺陷。账户 header 是账户 ID 意图 CAS，属于与已认证会话比较的意图约束，不能作为凭据，也不是服务端认证 generation。只靠此 header 不保证同账户 A → B → A、跨页面或跨客户端的旧意图全部失效。

## 提交前拒绝与提交后响应失败

commit **之前** 的权限拒绝、CAS 冲突或插入后异常，应不新增 review/audit/fact/use；结论限定于实际私库故障注入及计数覆盖。最新 boundary 支持其用途/header/锁内身份负例的零新增断言；compat 通过既有 CAS、一次消费与插入异常等所列兼容目标。当前代码私库回归不等于 before/after 生产运行对照，也不将覆盖场景泛化为任意拒绝均无写入。

`decide` 在成功 `db.commit()` 后重新读取 binary review response。此时如果用途变为 pending 返回 403，或完整性重读失败返回 503，审批及 actor audit **可能已经提交**。不能把任意 POST 403/503 写成回滚、服务器已取消或零新增；后续 UI 必须先只读核对 state/history，不能自动 POST 重试，也不能仅以相同 action/operator/reason 冒认本次成功。

最终新增 boundary 测试在 original commit 成功后才撤回私有 structured 用途，并断言 POST 403 时 review/audit 各 +1、actor 保留、事实/use/capture 与 adapter 调用不变，恢复 fixture 后 GET revision=1。前两轮完整 boundary 与普通上下文单目标均在其前置 loss baseline 失败；同源对照虽该目标 pytest 通过，observer 溢出仍失败。最新无观察器的完整 boundary 25/25 通过才提供该断言的完整受管回执；其余用途/header/锁内身份/actor/barrier 等也由同组目标覆盖。加上 compat 95/95，Root 仅接受 Task 0 后端切片，不关闭 Task 1 或完整 V1。

## 冻结源码与 before 保全

| 文件 | 权威 before SHA-256 | 最终静审 SHA-256 |
| --- | --- | --- |
| `apps/api/tire_api/quarantine_review.py` | `126f40037f4bf627a0b59c68dbe88a3c1a8cbf141b82d39b6c28f9a526bd83b7` | `f8249dd9d76d492e05ea607a698a1a77eb2af374fcca50b5bff282859672e605` |
| `apps/api/tests/test_vehicle_binary_approval.py` | `bfe1e1acae0a2013ed51e2b503e68243ec1c6476d3b17be73c917df118372e84` | `32e375e34ca400f08899ea63e237c5290be4ce51bcfe5fb2b0ac07cf2975431b` |
| `apps/api/tests/test_vehicle_binary_review_boundary.py` | 本轮原不存在 | `c1d15159ce93803bf82a5faf76be11c1dd0895c3e79293d76bfbd1899dc40609` |

权威 before-manifest 与两个原文件完整字节在 backend 目录；初版 boundary `30bed13a88dfe8e84e1f9d0a32ac7793763240f7a6038cc540b64a16e2e60a2f` 原文及新增 commit 后失败用例的精确 diff 同样保留。独审分别重算 before/after hash 与 diff，没有为新增 boundary 伪造 before。

初版 freeze SHA-256 为 `945609da6fb3be2ec3f9d0abe4fe9c53f19ad2d98bb652cd0f60ac44d474a59f`；短路径 freeze 为 `40c4f2e029b8689f80a9a13ae6efb9c3241efd3612798f499cec034e6cd46bd4`。文档侧独立对比两份各 694 输入：只有 `scripts/binary_quarantine_review_verify.py` 从 18908 bytes / `343efeecaba05cf974a9a9fa1ab658905815f280f7023c861c99d91df0a1f9ec` 变为 19235 bytes / `10a09921e7020ca911ce707b6c7ba95b24adeacae7640f8a6d79485dd53eacf4`，其余 693 不变。透明诊断 freeze 对短路径版仍仅该 wrapper 变为 `72e3047d…`、其余 693 不变；透明诊断版 694 输入对本次 live 观察无 drift。此前观察账记录短路径版当时无 live drift，并不适用于新 wrapper 后的当前状态。各 run 自身 source 首尾 stable 与跨版已知 wrapper 变化分别保留。

独立文本比较确认 `_binary_integrity_context` 与原 core 除私有函数名外逐文本一致；`consume_binary_approval` 除固定私有 core 调用名外逐文本一致。**逐文本保持不等于 before/after 运行对照。** review API 固定调用用途 facade，唯一原在线 consume 固定调用私有完整性 core，不读取 query/body/header 旁路开关。原在线 response 未额外调用 `require_vehicle_consumer_use(local_structured)` 的用途闭包仍开放；这不能升级为本轮已实测漏洞或已完成在线闭包。

## 保全、失败记录与切片收口

本轮收口目录为 `.artifacts/r97-close-8de9f8b8091148d8949f3aaa49e68706/`。`HANDOFF.before.bin` 保存 R96 入口起的 86568 原字节；`preservation-before.json` 记录开始观察的文档、相关源码与保护对象。本轮 HANDOFF 只 prepend R97 Task 0 入口，原全文作为 suffix 逐字节保留；精确 prefix/before/after 与保尾结果见 `handoff-final.json`。收口时间按 2026-10-21 实际写入，不倒填开始日。

开始只读实核七个保护 pin 均匹配：历史 S2 3240150 bytes / `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`；R38 保全库 25374720 bytes / `a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4`；R95 seal 31164 bytes / `fc7aae8b1435609278f9f925cd7c88654e8ed6326bdc8741b69f12707aa1b991`；R96 seal 23489 bytes / `4781953e4dbdb516f3f2bdb00b48c156406df86d399b64feac6d52d86572dbfe`；R95 三个受管脚本的 bytes/hash 见 preservation。以上为文件字节读取，没有打开 SQLite 或修改旧 seal/Guard/ACL/pins。

独立反模式报告实算三 scripts 与 R95 正式 live binding、auth/vehicle_raw 与 R96 source-final 均匹配；旧 report.md SHA-256 `b367bc8f7059c24f17722d22dc64474af5652bd52961438ed10559c5a4df597e`，verification.json 为 `7fe8c385f65fad9bd5567df806364687ba2593a602378835f75474886e9f9f0f`。路径修正后的 report-v2.md SHA-256 `6aca60deb8fe48d3354b5a0ad5f427d477cb78e0a395dea21296ed7bf99a0e62`，verification-v2.json 为 `74c7114993f560ca81d3579dea72f8b900a474156ab7e1e1a637a2b114492de2`；原 15 输入仅新 wrapper 已知 1 变，其余 14 保持。没有旧 Guard 独立历史 before pin，也没有 ACL 前后状态证明；只能确认本轮新增代码不写旧 Guard/ACL，不能声称其历史字节或全系统权限状态始终未变。runner 边界为受审 Python 与精确 child，不能据此声称 OS/native syscall sandbox 或全系统零泄漏。

文档只读采集失败记录均保留：首次 exit 1 无返回诊断，原记录的语法原因仅为推测，另以 `report-read-attempt1-qualification.json` 明确修正；第二次 `R` 被 Invoke-History alias 解析，改用任务专用函数名后重试成功；第三、四次为 rg 同时给入不存在的备选文件路径，现已核对正确路径，分别见 `report-read-attempt3.json`/`report-read-attempt4.json`。这些失败没有产品/测试运行或文件修改，不能混入产品回归结果。

`observed-evidence-v1.json` 至 `observed-evidence-v6.json` 保留逐阶段实际回执、诊断、反模式与 hash 观察账；更新前报告全文另有各 `report.before-*.md`，旧进度与草稿不覆写。最终 `source-final.json` 实算当前 694 输入，与最新 freeze 无 drift；Root 也已独立实核这 694 文件。`protected-final.json` 再核七个历史 pin。该核验不补造旧 Guard 历史 before 或 ACL 前后证明，也不把后端切片通过当作具体 ACL/系统根因证明。

本轮唯一 final seal 为 `verification-final.json`，绑定本报告、原计划/Task 1 增补、backend before/当前三源、独立静审/反模式、三 freeze、六真实 run、观察诊断、当前 694 输入 snapshot 与保护 pins；`bindings` 和 `evidence-inventory.json` 列出实际 bytes/hash，不含循环 self-hash。报告不嵌入 seal 自身 hash，HANDOFF 仅链接其路径。Root 对新 seal 的最终逐 binding 复核仍 pending；文档侧的 `final-seal-local-readback.json` 只证明本地写后绑定回读，不能冒充 Root 已复核。

## 仍开放的工作

Task 1 SDK、共享审批 UI、精确 Native header policy 尚未实施/验收。新增静态增补计划记录 Native JS 同判词、以 capture 补足 identity、单 active manager、显式 fence SDK/POST latest state、真实 DescriptionText 五项前置差异；没有改原计划或生产合同。没有本轮浏览器实际点击、真实 Native policy/设备、picker/SAF 或 OS 保存证据；R96 的既有 UI/Native 保存证据不能替代本轮 binary 审批接线。

活 PG 并发、正常库升级、真实来源许可、首代 online fetch/ready、直接在线 response 用途闭包、真实 Provider/receiver、EPREL、发布与完整 PDF/V1 Gate 继续开放。EPREL 无 Key 不再索要；本轮不因无需 Key 而伪称其完成。生产 Provider/export=false、来源许可 pending 与完整 V1 active 保持。

回滚只能依据本轮 before/diff 窄恢复；不得 reset/stash/clean 他人 dirty，不删除已 append 的历史。若 Task 0 自身有误，先停止 binary 写入并单独修复；Task 1 的将来 UI 回退不应顺便移除用途与 actor 安全边界。本报告作者仅做只读 hash/文档写入，未 import 产品、运行 pytest/API、启动正常库、联网或操控设备；未提交推送。
