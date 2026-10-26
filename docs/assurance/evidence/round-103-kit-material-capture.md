# R103 KIT C2：唯一尝试在导入阶段触发子进程禁止

2026-10-21（Asia/Hong_Kong）。**KIT C2 原件捕获未通过验收；V1 仍 active。** 唯一正式尝试记录阶段 `before_product_import`、`stop_code=child_process_forbidden`，captures POST 与原 UUID history GET 发起次数均为0，`network_outcome=not_observed`。没有原件成功回执证据，Root 对本次 run 按 `*.pdf` 递归枚举计数为0（仅文件名/后缀观察）。此结果不能归因于 KIT HTTP/robots，也不能记成一次来源抓取的业务 failed 回执。

本报告为 R103 KIT C2 单次捕获的正式证据记录。此前进展 draft、完整 HANDOFF before、候选和原始结果均保留，不覆盖。

## 来源、许可与身份边界

目标：Springer *Dynamic measurement of the fluid pressure in the tire contact area on wet roads*，DOI `10.1007/s41104-020-00056-z`，2020-02-03；KITopen 1000123313 记录同作者与 publisher edition。固定引用页为 `https://publikationen.bibliothek.kit.edu/1000123313`，唯一 initial URL 为 `https://publikationen.bibliothek.kit.edu/1000123313/86536961`，policy 为 `kitopen-1000123313-wet-contact-pressure-2020`。

Springer HTML 声明 CC BY 4.0；作者/来源署名、许可链接与修改说明须保留，PDF 版权行、版本及第三方 credit-line 排除仍未核验。KIT/Continental 作者关系和 Continental 资助已披露，不称独立商业横评。试验尺寸 `245/45 R18` 与 BB/SB/CR 等实验花纹不构成完整商品 SKU、载荷/速度指数、OE 或区域映射，不能建立商品排名或 Golden。`store_original/workspace_reopen/quote_identifiers=true`、`provider_use/export=false`；未做人工 PDF 审阅。

研究依据为 `.artifacts/material-c2-research-20261021/C2-RESEARCH.md`，SHA `47388d3723d9f1f29a26e5c0e6c757af86a20c9baa1d2452ad68d060a6bb40f9`。`redirect_urls=[]` 只表示没有批准的替代地址，未实测零跳转；任何跳转仍拒绝。

## 已审安装、正式冻结与唯一执行

候选保存在 `.artifacts/material-c2-candidate-20261021/`；R100 before 四文件完整保全，capture/launch 的函数/class AST 与通用逻辑保持，仅变固定来源、UUID 与路径。三正文以 CreateNew 原字节安装到 `.artifacts/material-c2-execution-20261021/` 并逐字节回读一致；安装回执 SHA `f03f8288a2ce4dd6000da4362137149c885394c2618d8e4ad00e64c2d1e3c8de`。未把 unfrozen proposal 当成正式冻结凭据。

Root 审定静态 helper 后执行一次 freeze，实际 exit0；新正式 manifest 为 `.artifacts/material-c2-execution-20261021/input-manifest.json`，2,840,619 B，SHA `26bc0af1d2e08891287a8e5f8337f0bffefd0b71eb26ba3c6816d3acbdb362c5`。原 proposal SHA `f15c2ffc3220e977a4faa923d8e1b57ee32da8837c09d86ce2a56bef511d72bb` 保留。Root 的七字段 delta 独核记录 SHA `fdd28399b89ec7773615e675a4f5343297bda3294f3601488303192536c0f62c`：bindings、roots/shapes、policy 与身份均与提案一致，仅已审冻结状态/时间字段变更。

freeze 与随后唯一 read-before 均实核217 primary +12,216 runtime +271 project =12,704 binding occurrences、12,495 个独立路径、全部 size/SHA、交叠一致性、完整 keysets、base/API-parent shapes、三正文、rights/argv；产品 Python 正确数量为142。read-before 确认 fresh run 不存在。helper 无产品/候选执行、网络或数据库连接；其结论只覆盖文件、声明权利及入口，不替代实际 PDF 或 OS/native 隔离验收。

唯一 UUID 为 `01981026-e6f1-4b67-b956-ee1318f75dd0`；run 为 `.artifacts/material-c2-execution-20261021/run-01981026e6f14b67b956ee1318f75dd0`。Root 使用已审安装位置与同一正式 manifest SHA 启动一次 launcher；正式 child 仍为 `D:/.PYENV/pyenv-win/versions/3.12.10/python.exe -I -S -B -X utf8`。20秒 transport、120秒 exact-child watchdog、最多一个 captures POST 加一个同 UUID history GET 的合同保持，但实际尚未到 API 发起阶段。

## 实际终态与关闭边界

Root 工具 session 为60694，初始 chunk `706f27`、终结 chunk `bc84c0`，观察到工具 exit3、launcher shell exit3；launcher 报 Python child exit3。outer shell PID66016 **不是** Python child PID，session60694也不是 PID。

| 实际项 | 结果 |
|---|---|
| result stage / stop | `before_product_import` / `child_process_forbidden` |
| denied | `child_process=1`、`nonprivate_sqlite=0` |
| captures POST / 原 UUID history GET | `0 / 0` |
| network / human PDF review | `not_observed / not_performed` |
| TestClient context exited | `false` |
| result input bindings stable after | `true` |
| launcher exact child exited / forced stop | `true / false` |
| stdout / stderr suppressed characters | `0 / 276` |
| 原件 / 验收 | Root 对本次 run 按 `*.pdf` 递归枚举计数0；`accepted=false`、`goal_complete=false` |

`denied.child_process=1` 证明审计钩子拒绝了受禁的子进程请求，不证明该进程实际创建。触发的具体 audit event、exe/argv 与导入链仍 unknown。`stage` 是粗阶段标签，不能据此补出更细的调用链，也不能证明此前没有执行项目代码或私库初始化；`nonprivate_sqlite=0` 不是全数据库/系统边界证明。`network_outcome=not_observed` 不证明全局网络活动为零；上述按文件名/后缀的递归计数不是实际对象完整审计或数据库句柄审计。

有限 CIM 观察失败；独立 Python PID 身份、独立进程缺席与全部 SQLite/OS 句柄关闭均未证明。launcher 的 exact-child exit 与未强停是已报告事实，`testclient_context_exited=false` 不能改写成 TestClient/所有资源已关闭，也不能凭此断言泄漏。原始 stdout/stderr 由 launcher 在内存读取，未向人或日志展开、未持久化；落盘仅有抑制字符数。Root terminal-readback 是有界安全观察摘要，不是 raw tool log 或完整 OS 隔离证明。

## 执行后独核与保护对象

Root 唯一 read-after 工具 `3ab215` exit0；12,704 条 binding /12,495 个独立路径全部 hash、交叠记录、keysets/shapes、三正文与声明合同保持。正式 manifest 是 freeze 时快照；after-readback 不代替执行终态判断。R38/S2 的另行前后纯文件 hash 核验保持，未打开数据库连接：

| 保护对象 | 字节 | 前后相同 SHA-256 |
|---|---:|---|
| `.artifacts/runtime/round38-before.sqlite` | 25374720 | `a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4` |
| S2 `xiaomi-first-generation-2.pdf`（r81-source-and-regression 原件） | 3240150 | `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f` |

本轮关键证据均在 `.artifacts/material-c2-root-audit-20261021/`（result/launcher 位于上述 run）：

| 实际文件 | 字节 | SHA-256 |
|---|---:|---|
| run/result.json | 797 | `deb524c0f522ff836b0f927c24cd5cc5422202be6b0455b11166829a3fbe13b4` |
| run/launcher-result.json | 395 | `fa4ee30402aea67497b552897f29ea8e687c59b1e9611ac0447f8d9451aa5e0f` |
| capture-invocation-terminal.json | 650 | `1cfc9f18f446550da20364a39f2b8a8fa3cb876f1ea212a8f7726784f0d116e8` |
| before-readback.json | 1516 | `4b7817093c250971a90007a07d0eea09717e153180413a8658d6b3085d5da8ce` |
| after-readback.json | 1484 | `650ff6bd86fcc2d87316cb3e14adfa2479ed894be2b31308e8214a4bf6793028` |
| protected-after.json | 858 | `d0cfc346ffcfdb59604e1951198e418b3148f7ec545e438d9f7d3795e1b2d2b2` |
| terminal-readback.json | 3637 | `c25048b1773388448980550686cc0620beb5c37a2a426694ab6ae424de4c96be` |

终态独审已完成：`.artifacts/material-c2-review-20261021/terminal-review.json` 为5,605 B，SHA `b6f91cf939014e394f46ebdb5a920de0e926876d2f448f6353c1dd0e80e16fac`；`terminal-review.md` 为2,371 B，SHA `54ad30cb15c95cd6c0202a0dc036b8a10478fddb5b8eeb2a1e89e59f9dfc8eb2`。独审确认终态证据一致、材料验收未通过；其仅核七件有界 JSON 及凭证，未重复全量输入 rehash、重开 R38/S2、递归审计 PDF/对象、查看 raw tool log 或新增进程查询。Root 工具 exit/session/PID 和递归 PDF 文件名计数保持 Root 报告的来源层级，不冒称审查者独立现场观察。没有真实站点/PDF、人工页面权利、商品 SKU/Golden、全资源关闭或 V1 完成验收。

下一步由新的 bug-analyzer 只读分析导入链；静态候选不能直接改写根因结论。如需有限导入诊断，须另审范围，继续拒绝 child，不记录 argv/env/locals/raw 异常，当前不运行诊断。不重跑该 UUID、不放宽 Guard、不清理现场、不重试 aging/UTQG/MDPI C1 或回填旧失败。Provider/export 保持 false，不因未配置 Key 再次索取；V1 继续 active。
