# 2026-10-26 全项目从头到尾复核报告（V1 目标对账）

本报告是一次"全项目体检"级复核：按原始需求规格与交接卡对整个工程做端到端对账，复核本身不修改任何产品代码。结论先行的判定：**工程仍为 R136 限定验收，不是完整 V1**；今日复核未改变任何发布 Gate 判定；全部可复验项通过；新发现一个与本机环境相关的受管 runner 命名陷阱（非产品缺陷，见第 6 节）。

## 1. 范围与方法

- 锚定文件：[原需求规格](../requirements/2026-09-26-tire-intelligence-original.md)（12 模块、10 发布 Gate、13 SLO、15 决策）、[AGENT-HANDOFF-2026-10-26](../AGENT-HANDOFF-2026-10-26.md)、[R136 正式报告](round-136-source-material-stop-adoption.md)、[提交前检查](publish-2026-10-26.md)。
- 方法：证据驱动复核——先核对仓库/远端/字节钉，再重放可重放的验证（静态四项、受管 runner 两批），最后对 12 模块与 10 Gate 逐项对账；不可复验项如实列为未复验。
- 边界：全程未打开正常/保留 SQLite，未启动默认 API，未登录任何来源，未调用任何 Provider；封存 KIT C2 UUID 未触碰。

## 2. 基线与仓库状态

| 项 | 核对结果 |
| --- | --- |
| 工作区 | `git status` 干净；复核全程零未预期改动 |
| HEAD 与远端 | 本地 `0cd9694` == `origin/main`（`git ls-remote` 实测，github 当日可达） |
| "commit 所有改动" | 复核启动时无任何待提交/待推送改动；本会话全部产出在 gitignore 的 `.artifacts/`（既有约定，交接卡§1）。本报告自身为唯一新增跟踪提交 |
| 产品字节钉 | `source_materials.py`(7c52cb47)、`migrations.py`(54e99974)、`source-materials.tsx`(a7ccf32b) 与 root-closeout `current_product_pins` 完全一致 → **当前 HEAD 产品代码 == R136 验收时代码** |

## 3. 本机证据可用性（交接卡点名回执全部在盘）

- 目录：`publish-handoff-20261026`、`r136-source-material-stop-20261025`、`r136-core-a`、`r136p2`、`r136-final-a`、`r136-parser-a`、`r136browser-d1364e5f60718293`、`gnt-capture-execution-20261026`、`te-import-wright-20261026`、`material-r137b-research-20261026`、`utqg-capture-execution-20261021` 全部存在。
- 哈希钉：浏览器批 `result.json`（2,227,667B）SHA `9d010150…` 与 root-closeout inputs 钉值一致。
- 回执内容与文档一致：核心批 251/251 exit0；Parser/Golden 批 27/27 + 47 受管子进程全 exit0；扩展批 468 pytest 全过但 runner 因已知 urllib3 IPv6 导入探针 exit3（`known_blocked_ipv6_import_probes=1`）；Root closeout 124 项检查 passed，且显式包含"旧 Parser 两红保留、历史 UI 失败保留、不得重写"的检查。

## 4. 本会话（R137 之后）新增交付复核

| 交付 | 回执核验 |
| --- | --- |
| 第二次真实原件捕获（Green NCAP 轮胎磨损测试规程 v3.0.0） | `run-ae4c9a26…/result.json`：exit0、440,798B、raw_hash `7646fd9f…`、document `e381371f…`、provider_use/export=false、正常库未授权访问 |
| TestEvent 导入链路首次闭合（Wright & Els 2017，CC BY 4.0） | `run-568648f1…/result.json`：exit0、event `42deb710…`、fingerprint `17f12898…`、`sku_golden_created=false`、单次 POST、离线导入 |
| 会话+精确SKU材料前沿封锁证明 | `material-r137b-research-20261026/RESEARCH-CARD.md` §1–§8 在盘（含 R137 候选纠错、网络白名单矩阵、四重条件无交集与解锁条件） |

## 5. 今日复验执行与结果

| 项目 | 命令口径 | 结果 |
| --- | --- | --- |
| Web 标准测试入口 | `npm run test --workspace @tire/web`（Node 22.22.1） | exit 0，日志零失败行 |
| TypeScript ×3 | `tsc --noEmit --incremental false`（web/desktop/mobile） | 三项分别 exit 0 |
| Python AST | venv 3.12.10 遍历 apps/api+apps/worker+scripts（排除 venv/pycache） | 2,005 文件全部解析通过，零语法错误 |
| 核心批复跑 | 受管 runner `--phase run`，新私槽 `fullreview-20261026-core-a`，同 R136 三模块目标 | **251/251，runner exit 0**，764 源稳定，正常库未启动，零意外拒绝 |
| Parser/Golden 批复跑 | 同 runner，先长槽名后短槽名 | 长槽名 21/27 早段失败（见§6根因，非回归）；**短槽 `fvr-p1`：27/27、runner exit 0、47 受管子进程全 exit 0**，与 r136p2 完全一致 |
| 扩展 11 模块批 | 未重跑 | 维持已记录形态：468 pytest 绿 + runner exit3（已知 IPv6 探针），交接卡§4 结论不变 |

结构一致性锚点：迁移版本以 `apps/api/tests/version_registry.py` 为权威全集 001–031（`024_vehicle_binary_raw` 定义于 `vehicle_binary_migration.py:19`，无空号）；Parser 来源清单 `parser_bundles._SOURCES` 恰为 10（michelin-us/uk/fr/de/cn、toyo-us、hankook-us、pirelli-us 共 8 个轮胎参数源 + nhtsa-us-recalls + xiaomi-cn-vehicles），与交接卡口径精确吻合；12 个规格模块在 `apps/api/tire_api/` 均有对应实现模块在位。

## 6. 新发现：受管 runner 输出槽名长度 × MAX_PATH 陷阱（非产品缺陷）

- 现象：今日以长槽名（29 字符 `fullreview-20261026-parser-a`）复跑 Parser/Golden 批，21/27 测试在 2–4 秒内早段失败（产品 `parser_releases.py:192` seal 包错→503→bootstrap 类测试连锁断言失败），run 阶段零受管子进程；文件级隔离（`…-parser-iso1`）复现 10/12 失败。昨日同管线的 `r136p2`（5 字符）为 27/27。
- 差分实验（全部今日执行）：
  1. 官方 runner + 短槽 `fvr-p1`：**27/27 + 47 子进程全过**；
  2. 复用 runner 自身 `bootstrap()+RegressionGuard` 后直接调用 `seal_deployed_bundle()`：长、短槽名均成功（162 文件，bundle `b56c697c…`，零拒绝）；
  3. 裸 pytest 单测（默认 bundle 根已有预封存同 ID 包，走"已存在→仅校验"快路径）：55.36s 通过；
  4. 全部过程中 764 源字节稳定、selfcheck 12/12、run 阶段零守卫拒绝。
- 根因：`test_parser_releases.py` 夹具 `trusted_copy(tmp_path, …)` 把受信包树复制进 `--basetemp`（`<槽名>\private\pytest-tmp\test_<长测试名>0\`）再做完整 seal staging（`bundles\sha256\<64hex>\package\tire_api\adapters\…`）。长槽名把最深绝对路径推过 Windows MAX_PATH 260（本机 `LongPathsEnabled=0`）→ OSError 被产品包装为 503。直接 seal 不经过 pytest-tmp 段，故长短槽均成功。
- 影响范围：仅影响"新批次的槽名命名选择"；不影响产品代码、不影响昨日及更早全部回执（均为短槽名）。
- 建议（工程变更需另立命名批次，本报告不擅改）：
  1. 约定：新 runner 批次 `--output-root` 槽名保持 ≤10 字符量级（如 `fvr-p1`）；
  2. 可选加固：`trusted_copy`/seal staging 使用短化临时名，或系统启用 LongPaths（需独立评估影响面）；
  3. 已写入项目备忘（跨会话记忆），防再次误判为回归。

## 7. 12 模块对账结论

模块实现与边界维持交接卡§2 判定；本轮复核补充锚点：规格 12 模块全部有代码在位（查询/身份/适配/比较/TestEvent/监控/CRUD/证据/个性化/AI/对外/后台对应模块清单见§5）；今日无产品代码变更，故各模块"已实现/未闭合"状态与 R136 验收时逐字相同，不在此复制全表。重点未闭合项不变：P0 来源覆盖、真实精确 SKU 正例与真人 Golden、首代 SU7 官方 OE、真实 Responses 语义验收、任意网页/PDF 监控、生产部署/平台/无障碍验收。

## 8. 10 项发布 Gate 现状

沿用交接卡§6 判定，本轮复核未产生任何足以改变判定的新证据：P0 来源 provenance、未授权回退全平台证明、Golden 错合并真实样本、AI 引用真实端到端、AuthZ/SSRF 生产零证明、P0/P1 故障闭环、WCAG 2.2 AA、六平台核心 E2E、Adapter 长期健康、整库升级回退——**全部仍未达成**；工程性防护与阶段证据存在（详见各轮报告）。

## 9. 未复验项（诚实边界，按五层口径）

- 源码层：已复验（tsc×3、AST、web 测试、字节钉；见§5）。
- 合成/隔离层：核心批与 Parser/Golden 批已当日复验通过；扩展 11 模块批、全量套件、浏览器 E2E、生产构建、Native/Android 编译与设备批**未重跑**，维持历史回执。
- 真实 HTTP 层：未发起新捕获；既有 GNT 捕获回执复核一致；来源网络白名单维持研究卡结论（前沿封锁中）。
- 模型层：本轮零 Provider 调用；真实 Responses 语义验收仍缺本机凭据，维持开放（不索要密钥）。
- 设备层：未重跑任何设备/模拟器验收。

## 10. 遗留与建议顺序

1. 维持交接卡§5 接手顺序：P1 真实材料前沿（网络解锁条件见研究卡§8）＞P1 真实 Responses（凭据可用时）＞P2 旧 Parser 两红与扩展 runner IPv6 探针排查（新命名批次，短槽名）。
2. `docs/assurance/risk-register.yaml` 仍为 r82 旧版（交接卡§6 已声明）；若做台账同步，须逐项对后续轮报告核验，不得整表判关闭。
3. 今日全部复核产物：`.artifacts/fullreview-20261026/`（静态检查日志、双批判执行日志、诊断驱动脚本）、`.artifacts/fullreview-20261026-core-a/`、`.artifacts/fullreview-20261026-parser-a/`、`.artifacts/fullreview-20261026-parser-iso1/`、`.artifacts/fvr-p1/`、`.artifacts/fvr-dg2/`、`.artifacts/fvr-dg3/`、`.artifacts/fullreview-20261026-diaglong/`（后三者为只读诊断私槽，均未触碰正常库）。
