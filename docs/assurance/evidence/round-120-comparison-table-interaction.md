# R120 比较表键盘、列宽与固定表头

2026-10-22，Asia/Hong_Kong。已交付原规格878–880行要求的比较表键盘行导航、可调整列宽和固定表头，当前比较与已保存比较共用。**最终组件UI独立v3批次28项通过，当前Web生产构建与Root终核通过。** UI结论限于真实React布局配合合成数据，完整V1仍active。

## 功能结果与修改范围

[实施计划](../../plans/2026-10-22-comparison-table-interaction.md)绑定原规格；规格原件 SHA-256 为 `f8a2a4434d83824afe36d3e46730ee183e4506acc0c91041b8a122b36e6fc46d`。本轮产品范围只有三个文件：

| 文件 | 责任 |
| --- | --- |
| [comparison-table-layout.tsx](../../../apps/web/components/comparison-table-layout.tsx) | 新增纯 React 布局组件，接收列和行的 ReactNode，只管理焦点、当前实例列宽和滚动。 |
| [workbench.tsx](../../../apps/web/components/workbench.tsx) | 既有 `ComparisonTable` 保留身份、来源权威、事实值、人工核验状态及证据回调，将原值交给新布局；当前比较和已保存比较沿两处既有调用共享此路径。 |
| [globals.css](../../../apps/web/app/globals.css) | 比较表专用有界滚动、表头/字段列固定、焦点和列宽操作样式。 |

组件使用原生 table/thead/tbody/th/td，未改成 ARIA grid。支持 ArrowUp/Down 逐行移动、Home/End 到首尾，交互子项保留按键及 Tab/Enter；列宽支持指针和键盘、有界调整与重置，以稳定 column ID 管理本实例会话状态，并处理 Escape、pointercancel、捕获丢失与卸载。滚动容器最大高度为 `min(620px, 65dvh)`，横向滚动留在组件内；表头、字段列与左上交点分别使用独立层级。

没有 API、比较保存合同、SDK、后端、数据库、依赖、Provider 或持久化设置改动。不会用本轮布局交付替代完整 V1 验收；既有 Ctrl/Cmd+K 也不是本轮新增功能。

最终实现保留即时几何校正，并为当前焦点建立惰性的scrollend观察：若事件发生时目标仍可见，继续等待；第一次真正需要补偿时先拆监听再即时校正。新按键、wheel、pointerdown、touchmove、拖动意图、blur、新焦点与卸载会取消旧状态，避免回拉用户主动滚动。键盘调整列宽会在React提交DOM宽度后重建该事务，而非只在focus时修正；不使用持续轮询。

## 最终组件UI：独立v3同批28项通过

[最终v3回执](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/result.json)16119 B/SHA `bc46ba84e69a90afea2c004be8dbf3131eb9553ae8774eb75ab1af8601b637ae`；[prepare](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/prepare.json)20937 B/SHA `692068d27a7d14844e7a18a80e4a862c95b5dfe6b64b3dd42028e52e7ee705db`。当批28项全部通过，failure=null、source_stable=true、context_close_returned=true，requests/page_errors/console_errors均为空，Root观察执行器Node自然exit0。[组件类型检查](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/typecheck.json)diagnostics为空，[fixture编译](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/compile.json)errors/warnings为空。输入pin覆盖该批关键运行/编译输入，不称完整浏览器import closure或OS sandbox。

28项覆盖原生表格语义、行键盘导航与焦点、Tab/Enter回调和输入子项原生键、指针/键盘列宽上下限与重置、稳定列ID及实例隔离、动态行、拖动卸载、390px表内横滚/固定表头/证据可见、保存比较、暗色宿主、未完滚动中的焦点与列宽调整、wheel/blur/新焦点/卸载取消、CSS字号应力及无浏览器错误/请求。固定字段列宽控件的检查只证明按键横滚后即时可见；pointercancel仍是合成事件，capture-release仍是程序化触发。卸载事务检查通过程序click避免先由指针取消，450ms后重挂验证scroll0、width248、不夺焦及新导航，不把原拖动卸载当作替代证据。

Root实际查看本批[桌面表格](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/desktop-table.png)、[390px当前比较](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/mobile-table.png)、[暗色保存比较](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/mobile-history-dark.png)、[字号应力](../../../.artifacts/r120-comparison-table-20261022/ui-8fa2eb46/mobile-font-stress.png)4张截图。暗色computed门记录宿主/表头背景rgb(25,29,28)，表头/正文文字rgb(224,228,218)。200% CSS字号应力记录12px→24px；表头高度增至265px，证据按钮仍实际聚焦并完整露出，Enter只触发一次。该项不是原生浏览器zoom或完整WCAG验收。

Root保留旧[QA](../../../.artifacts/r120-comparison-table-20261022/browser-qa.mjs)、[QA-v2](../../../.artifacts/r120-comparison-table-20261022/browser-qa-v2.mjs)和[fixture](../../../.artifacts/r120-comparison-table-20261022/component-fixture.tsx)，最终使用[QA-v3](../../../.artifacts/r120-comparison-table-20261022/browser-qa-v3.mjs)与[fixture-v2](../../../.artifacts/r120-comparison-table-20261022/component-fixture-v2.tsx)。等待门为至少400ms观察且连续3帧稳定，保留2秒失败门，避免动画尚未启动时误判稳定。新的当前/保存证据按钮断言核实真实焦点、左右及正文上下几何；单独保留未等行稳定就Tab的正文场景和rapid8横滚→Tab A→立即ArrowRight至264px的列宽场景，避免等待洗掉旧触发条件。

## 当前Web生产构建与Root终核通过

独立新批次[web-build-c1208fa2eb463719](../../../.artifacts/r118-material-workbench-20261021/web-build-c1208fa2eb463719/verification.json)为passed，125006 B/SHA `aa276ce6ba817f9f45d3f66a5bcd460162d53da40c7cd1fea54a8f21cc2ec3a1`；freeze SHA `0b3fc9ff1ab9337a10c19b22cd972443c9189fb81bc9a79279925888506b1bee`，Root观察顶层Node自然exit0。web-icons/web-next/web-pwa三个阶段的supervisor与child均exit0、natural_resources_closed=true、active_pids_after_natural_grace为空，无forced job close。三个私Job分别完整观察/分类2、25、2个进程；这只证明所拥有进程树清理，不是系统所有句柄关闭或OS权限隔离。

当前Web的Webpack编译、TypeScript、静态页5/5及PWA shell生成完成，source_stable/dependencies_stable为true，generated_restore.passed=true且mismatches为空，unexpected_denied/optional_probe_blocks为空。17个guard终态分别为自身exit0的8个、父进程观察SIGINT退出的5个、父进程已请求SIGINT并以Native Job关闭确认的4个，不能合称17个自身正常exit0。本新批 `failed_framework_fallback` 为0，新增回退例外没有真实触发。日志仍有无缓存提示及受控home下package.json/outputFileTracingRoot警告；构建通过不等于无警告，也不是PWA离线或原生宿主验收。

新的 `build-web-v3-r120.mjs` SHA `d6dc7e14994adb01e0cf32e343b2203f57bc746dd94f9272c3bb5a890896fb6b`仅增加精确worker停止回退分类，旧helper与失败回执不改。[分类器15项](../../../.artifacts/r120-comparison-table-20261022/build-classifier-tests.json)已通过，SHA `ececa958be85309ff3357636b692136fa22233e0c2099628dfebb88b99c67a65`：真实旧记录只读重放、普通SIGINT及accepted SIGTERM、顺序/重复/缺终态/错误身份/阶段/抛出/SIGKILL/非零退出/强制清理/缺Native清单等负例。其范围是classifier-only，不是新构建执行，也不升级旧failed。

[Root独立终核](../../../.artifacts/r120-comparison-table-20261022/terminal-verification.json)为passed，4014 B/SHA `e1134b7fba08daf0e72a52a63d09f2b716d30573bd69a187412fb8dcc5877097`：三项产品pins与UI/build/live匹配，UI96项输入live匹配，四截图已实际查看；同时绑定分类器15项、新helper、旧failed回执及与旧freeze一致的原helper。最终UI、生产构建和分类器是各自独立证据，不能相互替代或合并计数。

[只读终态独审](../../../.artifacts/r120-comparison-table-20261022/independent-terminal-review.md)进一步核对上述回执、关键输入与终态分类，未发现阻塞；没有重跑测试、构建或浏览器，也未重新哈希全部依赖。

## 历史失败批次与独立诊断

各批次只按自身冻结源码及回执解读，不累加成同批全绿。以下都是已结束的证据；未读取运行中的槽位。

| 批次 | 终态 | 实际结论 |
| --- | --- | --- |
| [ui-3a27bc91 prepare](../../../.artifacts/r120-comparison-table-20261022/ui-3a27bc91/prepare.json) | 只准备，未执行浏览器 | 有编译和类型检查文件；不能计作一次失败 UI，也不是最终 UI 通过。 |
| [ui-4b68ad02](../../../.artifacts/r120-comparison-table-20261022/ui-4b68ad02/result.json) | failed，失败前通过 12 项 | 在 `mobile_and_saved_table` 阶段因键盘证据目标被固定字段列遮挡失败。390px 文档与视口均为 390px，内部宽 358px、表格 scrollWidth 676px；目标 left=144、固定列 right=196，遮挡 52px。 |
| [ui-5c79be13](../../../.artifacts/r120-comparison-table-20261022/ui-5c79be13/result.json) | failed，失败前通过 13 项；Root 观察 Node exit3 | 首次修正让横滚后的表头列宽控件可见（left=202、固定列 right=196），但正文证据目标仍被遮挡（left=19、固定列 right=196），在同一断言失败。 |
| [ui-6d80cf24](../../../.artifacts/r120-comparison-table-20261022/ui-6d80cf24/result.json) | failed，失败前通过 12 项 | 即时滚动/实际 sticky 几何等窄修后，失败提前出现在表头列宽控件：left=109、right=125，固定字段列表头 right=196，整控件被遮挡；未到该批正文证据按钮验收。 |
| [diag-focus-6d82cf24](../../../.artifacts/r120-comparison-table-20261022/diag-focus-6d82cf24/result.json) | completed_diagnostic | 同一旧冻结 bundle 的独立采样：真实 Tab 后目标已聚焦，立即 left=202、scrollLeft=7；两帧后仍聚焦但 left=147、scrollLeft=62，固定列 right 始终为 196。仅证明先露出后遮挡，不证明哪种原生滚动或动画机制导致。 |
| [diag-trace-7e91d035](../../../.artifacts/r120-comparison-table-20261022/diag-trace-7e91d035/result.json) | completed_diagnostic | 第三红批 bundle 上，正文证据目标立即 left=209/scrollLeft=0，两帧后为147/62，再18帧后为-102/311；全程仍聚焦。跟踪记录了两次 `behavior: instant` 调用，不能据此认定后续原生滚动被取消。 |
| [diag-matrix-8fa2e146](../../../.artifacts/r120-comparison-table-20261022/diag-matrix-8fa2e146/result.json) | completed_diagnostic，四个对照场景 | 无横向按键、横向按键后先等24帧再Tab都保持表头控件可见；按键后立即Tab，以及立即Tab后再挂一次scrollend修正，24帧后均被遮挡。后者回调已执行1次，仍未解决。 |
| [diag-transaction-00964dda](../../../.artifacts/r120-comparison-table-20261022/diag-transaction-00964dda/result.json) | completed_diagnostic，八个场景 | 冻结失败bundle加诊断监听验证惰性scrollend方案：表头与正文各补偿一次后稳定；wheel/按键/指针/blur取消，补偿后的主动wheel仍可滚走。不是最终产品验收，触摸和卸载未在此诊断实测。 |
| [ui-7e91da35](../../../.artifacts/r120-comparison-table-20261022/ui-7e91da35/result.json) | passed，v2同批27项；Root观察Node0 | 交互检查通过；Root实际查看截图发现旧fixture仅设置主题变量而未将ink/paper应用到宿主，暗色截图黑字黑底，不能证明有效暗色。不是已确认的生产app-shell缺陷。 |

三次失败执行批都使用实际 React 布局组件与合成 current/history props；`production_workbench_or_api_used=false`，不是完整生产工作台或 API 验收。三批均记录 `page_errors=[]`、`console_errors=[]`、`requests=[]`、`source_stable=true` 及 `context_close_returned=true`；执行器为 Playwright 1.63.0/Chromium revision1243/headless。每批保留 `desktop-table.png` 和 `failure.png`，后续成功不得覆盖失败回执或截图。

失败批部分通过、旧批类型/编译为空诊断均只约束当时冻结输入，不能补齐后续未执行检查或代替最终新批。

trace 与矩阵绑定第三红批 bundle SHA `8306e4f2d2342fb4f28c1c0aa5c72e6eb8bab1e735e9f4e18c53a5abd7489f03`，两份回执均 requests=[]、closed=true。矩阵同时记录 CSS SHA `4cb90b2319ad9374e5d75ac41c3506a77e849535962af6c0b65306542e725ebe`；[诊断脚本](../../../.artifacts/r120-comparison-table-20261022/focus-matrix.mjs)读取冻结失败 bundle 和执行时 CSS，并在各独立页面比较四条路径。其观察支持“尚未完成的横向按键滚动与焦点迁移重叠”这一触发条件关联；没有隔离证明 CSS smooth 是唯一原因，也没有证明挂一次 scrollend 就能修复。诊断没有修改产品，不属于正式通过批次。

中间源码3750497仅静审发现resize未重建事务并返修，没有prepare/run，不计为第四次UI红批。

v2旧回执15848 B/SHA `16e0c2086d3f3cb52f42fad42e4f5ec432e8931ad21fa823392b923001e744ae`及其27项通过保留。其暗色问题在fixture宿主，不更改已冻结回执或把产品源回退；v3是完整独立重跑，不将v2/v3检查拼成55项。

### 历史构建：c1207e91da352608整批failed

[web-build-c1207e91da352608](../../../.artifacts/r118-material-workbench-20261021/web-build-c1207e91da352608/verification.json)为failed，73333 B/SHA `81c63423106b2a0f8482ed887cb9c0019d9b65dacbf9ca1824e8691f0ed71421`，error=`Error: Contradictory worker terminal evidence`；Root观察顶层Node exit1。web-icons/web-next/web-pwa三个阶段supervisor均exit0；[Next日志](../../../.artifacts/r118-material-workbench-20261021/web-build-c1207e91da352608/web-next.stdout.log)记录编译成功、TypeScript完成、静态页5/5，但这些阶段结果不能将整批改成passed。

回执source_stable=true、dependencies_stable=true、generated_restore.passed=true且mismatches为空，unexpected_denied/optional_probe_blocks为空。guard记录精确父57544对worker65944先SIGINT accepted=true，802ms后SIGTERM accepted=false，最终child_exit的signal=SIGINT。[独立失败分析](../../../.artifacts/r120-comparison-table-20261022/build-failure-analysis.md)确认旧helper逐stop要求SIGINT，且Next cleanup→Jest end/forceExit的回退控制流与记录相符；preload原样调用kill，没有改写信号。accepted=false的SIGTERM不能描述为已杀死worker，旧失败回执也不得翻绿。Next stderr318 B包含受控home下package.json/outputFileTracingRoot警告，stdout另有无缓存提示；不得称日志无警告。

## 并行 Safety Gate 来源调查

该调查与比较表产品及 UI 验证分别记账；详见[独立报告](../../../.artifacts/r120-safety-gate-discovery-20261022/REPORT.md)、[结构化观察](../../../.artifacts/r120-safety-gate-discovery-20261022/observations.json)和[manifest](../../../.artifacts/r120-safety-gate-discovery-20261022/manifest.json)。结果为 **`discovered_contract_pending`，未注册 ready，未实现接入**。

匿名直连 Safety Gate 门户 HTTP200 得到 2269 B HTML 外壳（SHA `e420da2c114f4ee456b8d517ae684b63af898b947afc7b9e44f13d57714e3452`）；官方数据目录 HTTP200 得到 1599 B 外壳（SHA `6c25d8e78e6c165067d88d1fe7b81899a3e2274ce9562521110a84d7254d82e4`）。两者无重定向，但都没有告警数据、可用分发 URL 或 schema。官方索引提供周报 XML/Excel 分发线索；RDF/XML/Turtle/JSON-LD 是目录元数据格式，不是已验证的告警合同。

EC 与 Data Europa 的 robots 工具结果未见所选路径匹配禁止规则，但工具未提供源 HTTP 状态；Commission robots 不可访问且源状态未知；Webgate robots 的一次直接诊断为 HTTP404，不是403。Safety Gate 专属免责声明索引指向保留公告原意、指定署名及 Decision2011/833/EU，但实际打开到 `sorry.ec.europa.eu` 临时不可用页，未取得当前 PDF 原字节或完整许可。不得把索引、robots 或 HTML200 当作告警接入或当前再利用许可已经核验。

调查预算为 7 个显式官方 URL 加 1 个工具报告的重定向最终 URL，共 8 个不同 URL；另有对既有 URL 的 3 次直接诊断和 9 条索引查询，不能写成只有 8 次网络请求。未观察到403，未使用已见 robots 禁止路径；未用账户/Key/私有 API，未抓取或执行 JavaScript、猜 wire、下载全量告警或媒体。调查已停止联网，未改产品、正式文档、数据库或运行服务/测试。

下一步仅在取得官方真实提供的一次有界 XML 导出、当前完整再利用/署名条款及实际样本后，评估按“来源＋原公告号”严格本地解析、原件保存、详情与历史消费者。还需验证字段/标识/措施语义、完整性及更正/撤回合同；操作员提供文件须明确标记 supplied material，不能当成在线核验。各类措施不能一律称为召回。Safety Gate 继续待合同，既有 NHTSA 路径保持。

## 源码保存与验收边界

Root已在修改前保留两个既有文件原字节，[before manifest](../../../.artifacts/r120-comparison-table-20261022/before/manifest.json)记录：workbench为102078 B/SHA `993358f9012e3bc0df331fd96e0ae212b4a73728852e9234a81c60f82e200d35`；CSS为129203 B/SHA `377108c58cb8b35493447c77254d8ad9c9e0810331626348d92a5d9bc9ebc5fd`。当时新组件不存在。

最终产品三文件已由终核绑定：布局组件14710 B/SHA `ef79b8f326979d99c67b78b7ab04e3e65a19d74e8f01e0bd91a597864909cb0b`，workbench102594 B/SHA `ca8dbe68f7055542ead4bd861929062b083d15ce11c1ef596e0960342c95d493`，CSS130907 B/SHA `4cb90b2319ad9374e5d75ac41c3506a77e849535962af6c0b65306542e725ebe`。

纯组件浏览器只证明实际布局组件配合合成数据交互；构建只证明各自范围，均不等于完整生产工作台/API、真实专业SKU/真人Golden、真实Provider/Responses、真实PostgreSQL、正常库升级、原生宿主/设备或完整WCAG。本轮未重跑无关后端/API/Worker全套，未打开正常或保留SQLite，未commit/push/stash/reset/clean；dirty及历史失败证据保留。

## 后续交接

本报告由Root应用到 `docs/assurance/evidence/round-120-comparison-table-interaction.md`，并前置HANDOFF摘要；原HANDOFF的142344 B/SHA `54754581e7663e686b424ed9314a74b8c9fba2b598ffa32aafb82a26783bf073`保留为完整原字节尾文。R119及更早原文按历史时点解释。完整V1仍active，不按轮数或检查数推算完成率；EPREL、真实专业材料/真人Golden、真实模型、PG、来源覆盖和设备验收继续独立留账。
