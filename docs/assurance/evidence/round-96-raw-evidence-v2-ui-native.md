# R96：Raw Evidence V2 共享界面与 Native 保存证据

日期：2026-10-20。**R96 共享 V2 界面与 Native 保存切片已按本文所列层级收口，完整 V1 尚未完成。** 已核实类型检查、目标 Node 测试、三端前端构建、Rust/Java 生产纯模块测试、Rust lib/bridge 编译及两个精确 Bridge 测试、Android 全部当前生产 Java 的独立 javac 编译，以及 Root 实跑私 HTTP→SDK→React 的六入口 binary/text 和 1440/390/320 三个 viewport。最终 HTTP/Web 已受控停止；系统选择器、OS 落盘与真实设备没有验收。

完整 V1 Goal 继续 active。本轮不授予来源生产许可，不改变 Provider/export=false、首代 online fetch/ready、PG/正常库升级、binary 审批 UI、iOS、真实 Native 选择器/设备和发布的开放状态；EPREL 无 Key 不再索要。未提交或推送。

## 实现与独审范围

实施依据为 `docs/plans/2026-10-20-raw-evidence-v2-ui-native.md`，设计审查位于 `.artifacts/r96-design-review-c029ac6c58554ce5a3cad029c32a0f8c/review.md`，生产独立静审位于 `.artifacts/r96-code-review-eda440c8ebb04552b983159c4575c013/review.md`。静审最终刷新结论为未发现尚未处置的 P1/P2；这是源码结论，不能代替下表运行层级。

- 公共 reader/view 已接车型 workbench、capture-journal、source-quality、interest-center 车型 before/after、golden-sets、parser-releases 六个入口。读取、完整 metadata 展示身份和下载共用上下文 fence；ownerSignal、transport 变化、关闭、选择和重复操作同步撤销旧操作。binary 只展示 metadata 并下载经验证的 Blob，text 仍按纯文本显示。
- Native JS 在读取 Blob 前 prepare 单用 lease；迟到 prepare、picker pending 的 abort 与 finally 均接 release。Rust Bridge/NativeState 共用 authority；Android 使用应用级 authority 并绑定 plugin/document 身份。身份请求和异步 reset/recover/config 的 begin/end ticket 覆盖 pending 全程。
- picker 返回后，拥有 bytes 的 worker 在应用打开/写入前经 authority gate 转为 committing。这个转换是不可撤销提交授权点：撤销先胜才保证本应用 open/write=0；授权先胜后不承诺取消、零写入或回滚。Android 提供方可能在选择阶段创建空文档，本应用保证不能扩大为全系统零创建。
- 静审发现的来源页面 URL 被标为原文 locator、普通车型快照及既有质量复核来路弱化两项展示问题已修正；缺 locator 时如实显示未提供，不解析 PDF 补造。binary quarantine 不挂载旧审批表单，继续明确审批 UI 未接入。

## 已确认运行结果

各回执保留真实 argv/cwd、日志、源码首尾和私有输出。这里分别列运行层级，不把不同 run 的通过结果合成一次全绿。

| 层级 | 本轮实际结果 | 回执 |
| --- | --- | --- |
| 四份 TypeScript | web、desktop、mobile、native-client 各 exit0；不代表 SDK `.mts` 独立 tsc | `.artifacts/r96-frontend-122c11fafbc247ecbc000c8fb3fc4fc5/verification.json` |
| Node | 公共 helper 10/10，native-client/两 adapter 35/35，transport observer 2/2；四份 tsc 同 run 全过，source_stable=true | 同上，三个目标 stdout 均保留 |
| 三端前端构建 | desktop/mobile Vite、web icons/Next/PWA 五阶段均 exit0；source_stable=true；生成文件完整原字节恢复，mismatches=[] | `.artifacts/r96-frontend-916d98b340734a1f9fc0af73534733d9/verification.json` |
| Rust 生产 authority | 实际生产纯模块 4 tests 通过 | `.artifacts/r96-native-d6230c5343a44c9d8de35d81dc7ecf9e/verification.json` |
| Java 生产纯模块 | javac exit0；NativeCore 84、DownloadAuthority 69、DownloadJob 31 **checks** 均通过，不能称 184 个 JUnit tests | `.artifacts/r96-native-01e48b04ab0648b1ad61456b79f21250/verification.json` |
| Rust 整体集成编译 | 当前生产 lib/bridge 的 `cargo check --lib --locked --offline` exit0 | `.artifacts/r96-native-28fd90e57f1b45ab8a389d59aefc5626/verification.json` |
| Rust Bridge 精确测试 | 完整 cfg(test) 代码编译；两个新 Bridge 测试各实际执行 1 pass、171 filtered out。只执行这两个目标，不能称 172 项全跑 | `.artifacts/r96-native-202c8ce28a034889a46e456a73effca2/verification.json` |
| Android 全生产 Java 编译 | 33 个当前 `app/src/main/java` 生产文件及 1 个旧生成 BuildConfig，使用真实缓存 Android/Capacitor/AndroidX 字节完成 javac，exit0、103 class、82 输入首尾稳定 | `.artifacts/r96-android-c913c97358124ed7bfb57944639c58d0/verification.json` |

所有上述 Native 回执均记录 sources_stable=true。Android 的 BuildConfig 是原字节复制的旧 debug 产物，其 OFFLINE_HOST_BUILD 不能标识本轮源码；30 个缓存传递 classpath 输入只用于 javac 支持，不是当前 Gradle resolved graph。本轮没有执行资源生成、Gradle、D8/desugaring、APK 打包、SAF 或设备。Rust 编译及精确 Bridge 测试也不等于 Tauri/WebView2/系统 picker 运行验收。

报告准备阶段另以只读 SHA 对比成功 run 的输入与 live，结果见收口草稿目录 `compiled-input-live-check.draft.json`：checks4 208、build 208、最终 Bridge 67、Android 82 输入均 0 drift。早期 Rust 纯模块 10/Java 纯模块 15 输入各有后续已知 lib 生命周期修正及 wrapper 变更两项；host check 63 输入只有后续 wrapper 变更一项。相关实际 authority/Java 目标字节没有漂移；不能因此把所有早期 manifest 描述为与最终 live 全同，也不为这些历史 run 补填新 hash。

公共 helper 测试内 read/content/arrayBuffer/digest/save 标签共用一个受控 await，不能说实际五阶段 SDK/React 集成都由该测试验证。Node observer 的 release 计数是 signal listener，Native TS 测试覆盖生产 createNativeSave 调用，仍不是真实 OS picker。

## 失败与复跑账

原始失败不改写，未执行阶段保持未执行；详细账起点为 `.artifacts/r96-validation-draft-a521f79b598b4c019bca2953e5a56d96/draft-2.json`。该 draft 的 UI/Android 顶层状态比后续证据旧，不能覆盖本报告逐层更新。

| 入口 | 保留的失败 | 修正及实际后续结果 |
| --- | --- | --- |
| frontend checks 1 | `.artifacts/r96-frontend-08c02e36eb1b45d1bd565d7b57a033d1/verification.json`：web tsc TS2345，后续未跑 | SDK UTF-8 encode 前显式 requireContract(body 是 string)，无空串/断言退路 |
| frontend checks 2 | `.artifacts/r96-frontend-54c47953f02a498490007706beec821e/verification.json`：四 tsc/helper 过，recursive data-URL loader 遇合法 ESM 循环，内部 exit13、目标测试入口失败 | 仅测试 loader 改复用原 URL/hooks |
| frontend checks 3 | `.artifacts/r96-frontend-67a65e9178974a87a6b278232d61ac2c/verification.json`：四 tsc/helper10/adapters35 过，observer Windows `E:` import 入口失败，生产测试未执行 | wrapper 使用 `./packages/...`；checks 4 完整通过 |
| Rust host 首编译 | `.artifacts/r96-native-5827ef6d325f4ead9a3d1bd899a93f2d/verification.json`：E0599，exit101 | 生产 lib 改为先 build 得到 window 实例，再注册同 authority 的生命周期回调；新 host check 通过 |
| Rust Bridge 首测试 | `.artifacts/r96-native-5eadcbcd93a346fb84260f890fc8f5dc/verification.json`：snapshot 缺 tests/support 两文件，cfg(test) 编译失败、目标未跑 | wrapper 精确补入实际支持文件；新 run 两个 exact 各 1 pass |
| Android 首运行 | `.artifacts/r96-android-0d5619fdd321436c9a0671e70d547d53/verification.json`：Python audit 拒绝 spawn，javac exit=null | 是 wrapper 自有精确 child 校验失败，不是 javac 编译失败；没有补填退出码 |
| Android 次运行 | `.artifacts/r96-android-2619eced94434f668032d3461829afba/verification.json`：真实 javac exit1，缺 drawerlayout | 从真实 POM 声明补精确缓存坐标后，新 run 全生产 Java 编译通过；非产品 Java 修复 |

实施前及后续修正前完整字节分别保存在现有 `r96-ui-before-*`、`r96-native-before-*`、`r96-ui-display-before-*`、`r96-native-teardown-fix-before-*` 等目录，索引以各原 manifest 为准。旧生产字节、失败、seal/pins 不覆盖，不据目录名猜 SHA。

## 私 HTTP 与浏览器

HTTP fixture 使用新私库/object/tmp，返回合成 policy/receipt，离线重放已封存历史 S2 bytes。本轮实际走 FastAPI→SDK→React 本地调用链；这不等于新官网采集、parser child、正式来源许可或生产 release。四个 HTTP 结束回执都记录 normal_database_used=false、real_provider_calls=0、actual_parser_child=false，外网/子进程/正常库尝试均 0；最初启动失败的回执仍保留 shutdown_complete=false。

1. 同源脚本 `113034...` 普通上下文输出 `.artifacts/r96-http-71c99c933d8f43088a3e17c1afba11f6`：object_write_failed，startup_completed=false、ObjectStoreError、shutdown_complete=false，原 launcher exit1。提升上下文对照 `.artifacts/r96-http-c0f794bf342b46789046920527554419`：startup/stop 完成、source stable，Root 实观 launcher exit0。底层 I/O 原因仍 unknown，不能称 I/O 已修复或 sandbox 根因已证明。
2. 补 text fixture 的 `.artifacts/r96-http-0e25b93cc70e4eb6a4a49278e2af01c7`：Root 桌面 attempt1 已执行 capture 25 断言；quarantine HTTP200 被严格 SDK 拒绝，诊断显示合成 quality 缺必要字段，不能称生产缺陷或整套 UI 成功。`ui-desktop-full-attempt1-mcp.json`、`quarantine-diagnostic-mcp.json` 以及根目录 `r96-http-0e25b93cc70e4eb6a4a49278e2af01c7-fixture.py` 保留。stop/source stable 完成，Root 实观 launcher exit0。
3. 普通 Web launcher `.artifacts/r96-web-server-d56415f56a384c5bb643ea17cbdeee97` 自检200，但 Chrome/独立进程请求超时。Root 发受控 stop 后 Python launcher 实观 exit0；**server.json 的自有 Next child exit_code=1**、own_child_terminate_called=true、source_stable=true，不能改写成 child0。同 launcher/同成功 build 的提升上下文输出 `.artifacts/r96-web-server-7dbac7081ecd4675b1e37bb28539eff6` 可由 Chrome 访问，完成最终 UI 后同样受控停止，launcher0/child1；底层差异原因未知。
4. Chrome MCP 以 sourcePath/filePath 读取输出被其 workspace roots 边界拒绝；这不是 automatic approval review 拒绝。Root 改为读取已审源并 inline 执行，把实际 MCP 返回保存为本轮证据。

完整 quality fixture 的最终 HTTP 根为 `.artifacts/r96-http-ecc71693395449479388597a965d7e44/`，使用同一成功 web build 和实际生产 SDK/React。最终 MCP 结果已分别解析回读 done=true、passed=true、失败记录0：

| 实际 viewport / scope | 原始 MCP 回执 | 结果与 Blob 交付 | 真实 MCP 截图 |
| --- | --- | --- | --- |
| 1440×1000 / all | `ui-desktop-attempt3-mcp.json` | 78/78 断言、4 次交付 | `ui-desktop-final.png`，1510597 bytes、全页 |
| 390×844 / layout | `ui-390-final-mcp.json` | 60/60 断言、3 次交付 | `ui-390-final.png`，68613 bytes |
| 320×740 / layout | `ui-320-final-mcp.json` | 60/60 断言、3 次交付 | `ui-320-final.png`，57615 bytes；Root 已查看 |

三个 run 都实走六入口 binary/text、hash/大小、无 PDF embed/原件直链、可访问下载按钮、receipt-only/accepted:false、冻结兴趣快照身份与未发 binary 旧审批 POST。每个 run 只在 IIFE 末尾的 capture 页面断言 document 和 PDF 原件 card 无横向溢出，六入口没有逐页检查 overflow。capture、quarantine、workbench 各实际调用下载；Golden、parser-release、interest 验证读取与按钮，**没有实际下载调用断言**。文本是精确 inert 正文且不显示 PDF 动作，未执行旧 UTF-8 审批提交、Golden 确认或正式 parser 发布。

只有桌面 all 另外实跑 metadata 403/404/409/503、同 PDF 的 source/query_state 展示身份变化拒绝、只换 JSON key 顺序通过、content hold 期间关闭、selection A→B→A、私 fixture 换账户并 revalidate 及重复保存禁用，释放 hold 后旧操作均未交付。窄屏没有重复这一组故障场景。transport epoch 变化由独立 Node 生产 observer/adapter 测试覆盖，本页没有执行该场景；其他 metadata 字段变化也不能由这两个 UI mismatch 用例泛化。

每次实际交付都从 URL/click spy 捕获生产 Blob，重新 arrayBuffer/SHA-256，并断言大小、hash、文件名匹配冻结 metadata。桌面有 3 份历史 S2（3240150 bytes，SHA-256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`）及 1 份合成 key-order PDF（43 bytes，SHA-256 `3254a9780fdac5e0f9bf927a34095053408696fc42b8e8fbad515c5f9153f7db`）；两个窄屏各交付 S2 三份。回执记录 actual_os_file_save_checked=false，不能声称 OS 文件已落盘。

最终桌面 `console-page-2-final-mcp.json` 只有故障用例预期的 403/404/409/503 四条资源错误；390/320 的 `console-page-3-final-mcp.json`、`console-page-4-final-mcp.json` 无 console 消息。此前 `ui-desktop-attempt2-mcp.json` 为62项已过后 timeout: frozen version action，不能算全套通过；验证 IIFE 漏展开已有 interest details，Root 静审两 hunk 后仅修工具，生产不改。该版旧全文保全在 `.artifacts/r96-ui-interest-expand-before-c47a90d994f74ad9ab54239af7756d49/`，SHA-256 `32d72d658573f3d3bbde7919439b2f68ee8f40f8f43174a64cb3314b023d9479`；更早 quality 修正前的 fixture/IIFE 在 `.artifacts/r96-http-quality-before-6b584ee1b46a47aebc2cc5a2f502c614/`。最终脚本 SHA-256 `f948c67b5505cd4f74d41df80da374e9fcd944e940a64bf694b4e657066f70f1`；attempt1 的25项通过及 quarantine timeout 继续保留。Root 已查看390/320真实截图，窄屏文本换行可见。

## 最终资源与保全

- HTTP shutdown POST 实返 stopping:true，Root 所见 launcher session14564 exit0；`server-return.json` 同记 process_exit_code=0。最终 `stopped.json` 的 startup/lifespan exit/client close/shutdown_complete 均 true，280 输入首尾稳定；外网、子进程、正常库尝试各0，正常库false、真实Provider0、parser child=false。
- Web 的 Root launcher session31769 收 stop 后 exit0；最终 `server.json` state=stopped、child PID52992 exit1、stop_requested=true、own_child_terminate_called=true、source_stable=true。这是受控 terminate 子进程的退出，不补写正常 child0。
- Root 的 socket connect_ex 两口均10035，不能判断监听是否消失；Get-NetTCPConnection 因 CIM 不可访问 exit1，不能作为零监听证据。安全替代的 exact `127.0.0.1:18966|18967` TCP LISTENING netstat 实查0条、exit0，PID52992不存在；报告准备者再次独立执行同范围只读 netstat/Get-Process，结果相同，见 `resource-final.json`。Root 实观记录独立保存在 `.artifacts/r96-root-audit-20261020/resource-observations.json`，它是观察记录，不伪装原始 tool transcript。
- 浏览器 page4/page3 已关闭，最后 page2 导航 about:blank 后保留，不能写成全部页面已关闭。私库/产物保留为证据。
- 三份保护对象本轮只读实核：历史 S2 3240150 bytes / `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，R38 保全库 25374720 bytes / `a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4`，R95 final seal 31164 bytes / `fc7aae8b1435609278f9f925cd7c88654e8ed6326bdc8741b69f12707aa1b991`，均与既有 pin 相同，不执行 SQL。

## 证据绑定与开放边界

机器收口文件为 `.artifacts/r96-close-41569a232f344c18a42148958f15125e/verification-final.json`，绑定本报告、最终 source/UI/resource 回读、全部采用回执、失败/部分运行、截图和保护对象。`source-final.json` 对503个唯一当前输入（含源码及工具链/缓存）实算 hash；最终 checks/build/Bridge/Android/HTTP 分别208/208/67/82/280输入与各 run 0 drift，早期五条已知历史差异按上文原样列出。它不是503项测试，也不替代运行证据。HANDOFF 仅 prepend R96 入口，原全文字节另存 `HANDOFF.before.bin` 并核原尾保持。草稿文件继续保留为过程记录，最终 seal 待 Root 独立复核。

security.rs 与 NativePolicy.java 没有本轮独立 before pin；只能确认实施改动清单未含二者、独立静审没有发现权限扩大，不能声称两文件字节不变。本轮独立限定反模式检查未发现违规；Root 已实核 R95 三个受管 scripts 与正式 bindings 保持。这些范围不能泛化为全仓行为证明。

Root 独立回读的实际成功结果在 `.artifacts/r96-root-audit-20261020/independent-readback.json`。首版读回器把 Android 的 list 误当 dict.items，exit1；原脚本与失败保存在同目录 `audit-attempt1.py`、`attempt1.json`。按实际 schema 兼容后再读 exit0，重核最终输入/HTTP guard 与三 UI 结果；这是独立读回工具修正，没有重跑产品测试，也不能称整轮一次全绿。

本轮未新增正常库/PG迁移、生产网络或 Provider 验证。binary 审批 UI、iOS、Tauri/WebView2 系统选择器、Android SAF 真设备、OS 真实保存、生产来源许可与发布均未验证。回退仅按完整字节保全和本轮精确 diff 撤销自有变更，保留他人 dirty；Native JS/宿主 lease 必须成对部署/回退，版本不配时失败关闭，禁止无 lease fallback。保留所有历史证据，不 reset/clean/stash/commit/push。
