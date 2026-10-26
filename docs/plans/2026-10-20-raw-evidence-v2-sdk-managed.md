# R95：Raw Evidence V2 SDK 精确受管测试入口

日期：2026-10-20。当前状态：已按 Root 实施 Gate 编写静态候选，等待完整候选独审及单独运行 Gate。本文不构成 pytest、Node、类型检查或运行通过证据，不追改 R94 历史。

## 基线与授权

设计来源为 `.artifacts/sdk-raw-evidence-managed-entry-83b5d6f392c042ca/proposal.md`，独立设计审查为 `.artifacts/r95-sdk-entry-review-8065222857c740c0aba8fbe08ce69098/review.md`。以审查中的实时修正为准：既有 `.mts` 是 23381B／`db7bf5e993a89f226feae671a72cbb8c2385563441eb612e0cd8a644377d527c`，不是提案中的旧 pin；runner 是 161 项，不是 160 项。

Root 已核验 R94 最终 seal `.artifacts/r94-close-d7c49021e6a8/verification-final.json`（33878B／`367890328b67544f43c74234f7050c519d0066d7119d47d72f455a84c1a917ba`）及全部 120 文件绑定、687 source inputs 与 live 零漂移，随后明确开放本轮静态实施 Gate。R94 seal、回执和失败历史均保持原字节。

动笔前已确认新 wrapper、本文均不存在，并在唯一目录 `.artifacts/r95-impl-1de95e43ed6b404ab9c476bc3e40771d/` 保存三旧脚本完整字节、原 pin 清单、18 个旧 REVIEWED、161 项 manifest 和 R94 的 687 项 source manifest。新 wrapper 编写后，独审代理实读其最终字节并核准 1058B／`f62e6f5dd1db7b62bbbde7777c69c90b242d96ed9dfab2f899d7258622c64268`，此后才登记这一精确 pin。该批准仅指 wrapper 静态字节，不等于整体审查或运行通过。

## 文件级实现与依赖

| 文件 | 本轮唯一职责 |
| --- | --- |
| `apps/api/tests/test_raw_evidence_v2_sdk.py`，新增 | 只有 `test_raw_evidence_v2_sdk_behavior` 一个测试；只导入标准库和 pytest，不导入 app/DB。将 Node 解析为绝对 realpath；找不到 Node 直接 fail。局部固定 literal 为 `await import('regression:raw-evidence-v2-sdk');`。只调用一个 Node child，不传 stdin；repo cwd、30 秒、shell=false、capture_output/text/UTF-8。必须 exit0，且 `stdout.splitlines()` 恰为下面唯一成功行。 |
| `scripts/regression_children.py` | 18 个旧 REVIEWED 键/value及其顺序不变，只追加 wrapper 的审后 pin 和原样 `.mts` pin，18→20；两个旧 `node_scripts` 后只追加新 wrapper。index=2 沿用现有 no-artifacts→json 双 hook、精确 argv 比较、private cwd/env、native ticket 和 `node_wire_3` 分类。 |
| `scripts/regression_node_guard.cjs` | 增加唯一固定 alias。固定 repo 相对路径先严格等于其 realpath，拒绝入口本身的 symlink；其后生成唯一 canonical file URL。所有 resolve 分支先经 `nextResolve`，再从最终 URL 经 `fileURLToPath` 识别 `.mts`，要求无 query/fragment、href 精确相等、再次 realpath 仍是固定文件。保留 `@tire/api-client` 映射及既有网络、数据库模块、普通 FS 写入和后代进程拒绝。 |
| `scripts/run_api_worker_regression.py` | 原 TEST_MODULES 顺序完整保留，只在对应位置登记新 API wrapper，159 API＋2 Worker→160 API＋2 Worker，即 161→162；同步帮助文字。现有 bindings 已覆盖 `.mts`，只因新 wrapper 预计 687→688。 |

唯一成功行沿用已审 `.mts` 的原字节，不为变更轮次标语修改测试：

```text
R93 synthetic SDK assertions completed; this is not real HTTP, UI or Native acceptance.
```

新 wrapper 的用户态 argv 固定为：

```text
[exact node,
 --experimental-transform-types,
 --import, ./packages/api-client/tests/device-ai/no-artifacts-hook.mjs,
 --import, ./packages/api-client/tests/device-ai/json-esm-hook.mjs,
 --input-type=module, -e, exact literal]
```

ChildPolicy 按既有机制改写为 private cwd、绝对 `--require regression_node_guard.cjs` 和两个固定 hook 的 file URL。不得增加动态 `-e`、脚本路径参数、环境驱动入口、任意 Node 文件、npm 或 tsc。全局预算、timeout、并发、启动票据、stdin/stdout规则、自检和通过条件均不调整。两个旧 wrapper、两 hook、package scripts、`.mts`、SDK、`regression_guard.py`、`regression_child.py`、产品、模型、迁移及 Native 均不改。

JSON hook 后注册，其 `.ts/.mts` load 会 shortCircuit，因此 `.mts` 白名单必须位于最终 resolve 结果边界。检查只放行上述固定真实文件；不能只检查 alias、原 specifier 或较早的 load。URL 解析失败被拒绝，其他 protocol 沿既有 `nextResolve` 结果处理，不增加协议或读取放行。

## 静态交付与运行 Gate

实施阶段仅允许指定 API venv Python 的标准库 AST、hash、JSON 和文本 diff，PowerShell 使用指定 PowerShell 7。候选冻结应交付四源的完整字节、SHA256、diff，以及下列静态核验结果，随后停止修改并交完整独审：

1. wrapper AST 为一个顶层测试、一个 subprocess.run、零 skip；固定 literal、argv、cwd、timeout 和 exit/stdout 判据正确。
2. 18 个旧 REVIEWED 键/value 完整保留，恰增加两项；20 项均与 live 源匹配。两个旧 Node literal、顺序、hooks、预算和 ChildPolicy 其余 AST不变。
3. 161 项旧 manifest 完整保留，恰增加 wrapper，实际 162 项；与目录中的显式测试模块集合一致。源闭包预计 688 项，只允许四源差异。
4. `.mts` 仍为 23381B／`db7bf5e993a89f226feae671a72cbb8c2385563441eb612e0cd8a644377d527c`；其他 SDK、旧 wrapper/hook/package 和 guard/child 未变。
5. Node guard 的固定入口、canonical URL、解码后 `.mts` 路径、query/fragment 和 realpath 检查由独审读完整控制流；静态检查不冒充 Node 语法或兼容性运行。

完整独审后，只有 Root 的独立执行 Gate 可以授权原 runner 的一次受管 run。精确选择以下三个唯一 nodeid，不选择旧 21-test 路由模块整体，不另造 runner 或放宽阈值：

```text
apps/api/tests/test_device_ai_public_contract.py::test_public_sdk_exports_match_closed_server_dto_fields
apps/api/tests/test_device_ai_routes_prepare.py::test_preparation_response_views_are_consumable_through_public_sdk
apps/api/tests/test_raw_evidence_v2_sdk.py::test_raw_evidence_v2_sdk_behavior
```

运行验收必须逐项核对：3 个唯一 pytest 项，setup/call/teardown 完整，3 pass、0 skip、0 incomplete；`node_wire_1/2/3` 各 authorized=1、started=1，3 个 child 全 exit0、live0；原 selfcheck 保留；raw 非 selfcheck 拒绝0；首尾/live source bindings 一致；资源关闭、自然退出、R38 前后 metadata 不变；正常库未启动、真实 Provider/receiver 调用0。原 runner 的绿色本身不足以证明零 skip 和恰好三个 Node child，仍需审回执。

若失败，保留原失败目录及原字节，先定位精确原因；不修改旧红、放宽拒绝阈值或静默改 pin。涉及测试字节变化时重新独审新 pin，运行必须重新获 Gate。

## 证据口径与验收限制

新 wrapper 的行为账是 **1 个 pytest wrapper、1 个 Node child**；连同两个旧兼容目标是 3 个 pytest 项和 3 个 Node child。`.mts` 内部断言或循环不得展开为大量 pytest case。

`.mts` 使用合成 transport、原生 Response/Blob、真实 Node WebCrypto SHA256及独立 fixture hash，断言三闭合 schema、Blob SHA/size/MIME/signature、fence/abort/transport epoch 和错误页行为。只有实际执行回执成立后，才能描述这些断言已通过。旧路由 wrapper 保留其 private API/DB fixture；只有新增 wrapper 无 app/DB import。

当前 `.mts` 没有断言 `ApiError.code`，只能按实际断言描述 ApiError 类型与 status。四异步边界循环由 vehicle content 进入共同 helper，不能声称六个方法各在四个阶段独立跑过；也不能补称每个拒绝 Promise 分支或每次拒绝后的请求停发均已独立覆盖。

Node transform 会擦除 TypeScript 类型；`@ts-expect-error`、Equal/Assert 和 compileOnly 不构成 tsc 证据。本切片不证明真实 HTTP→SDK、账户切换 UI、Native 保存、真实 Provider、来源许可或完整 V1 Gate。

现有 Python/JS API fence 是 reviewed-source 边界，不是 OS 沙箱。普通只读 FS 仍允许；no-artifacts hook 只覆盖同步 readFileSync 的 `.artifacts` 路径，不能声明所有正常库或凭据文件原始字节已受 OS 隔离。本轮不增加普通读取沙箱。

## 回退边界

未启动任何产品或修改数据库，无迁移回退。需要撤销本切片时，先核四源 live pin，按 `.artifacts/r95-impl-1de95e43ed6b404ab9c476bc3e40771d/` 的完整旧字节和精确 diff 撤销本轮新增/修改；若出现后续并行改动，逐块处理，不覆盖他人变更。保留所有 R94/R95 回执、失败历史和本轮备份，不自动 reset、clean、stash、commit 或 push。
