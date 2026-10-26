# R132 KIT C2 捕获执行：原件未取得，原 UUID 保持未确认

2026-10-25。继续完整 V1。本轮完成受限入口准备、两次独立工装执行及终态核对；**未取得 KIT PDF、未完成原页许可/试验核验，不能将材料需求记为完成。** 无 EPREL Key，继续独立工作。

## 目标与实际范围

按[计划](../../plans/2026-10-23-kit-c2-material-capture.md)使用已有真实材料路由捕获 KITopen 论文。固定引用页为 `https://publikationen.bibliothek.kit.edu/1000123313`，PDF 入口为 `https://publikationen.bibliothek.kit.edu/1000123313/86536961`。CC BY 4.0 的保存依据来自[前期研究](../../../.artifacts/material-c2-research-20261021/C2-RESEARCH.md)，PDF 内版权与第三方例外尚未核对。

新工装复用 Python3.14.8、现有依赖、R115 受控导入和 ASGI 消费者、R114 Guard/selfpipe 原文件。显式创建新私槽 API 工厂，不启动默认 API、Uvicorn 或 Web。固定来源 transport、PublicResolver、TLS、robots、20秒/8MiB限制及 Provider/export=false 保留。仅增加本批网络观测和私槽 `FileObjectStore.put` 原子发布能力；本轮未走到原件写入。

工装和产品源是受信且冻结的；Python audit 不是 OS sandbox。网络计数是 CPython 审计操作，不能当作抓包或网站已收到 HTTP 的证据。空来源注册表仅用于隔离其他来源，不是真实轮胎来源验收。

## 首批失败及修正

[10/23目录首批](../../../.artifacts/material-c2-resume-20261023/run-356e579d80554b5c8624640427e62d10/result.json)于10/25实际运行。受控导入七探针通过，但工装错误引用不存在的 `tire_api.adapters.AdapterRegistry`，在 `explicit_private_factory` 阶段被 import guard 拒绝。该不存在符号是已确认的静态错误；原回执没有逐事件记录被拒绝的模块名。

子进程自然 exit3，捕获/查询调用均0、网络操作0、数据库句柄0，没有数据库或原件。外层执行工具返回1，不能混同子进程 exit3。Root 已确认 PID132232 缺席，见[首批观察](../../../.artifacts/material-c2-resume-20261023/first-failure-root-observation.json)。旧独审 ACCEPT 漏查实际导出符号，原接受记录、冻结输入和失败现场均保留。

新目录和 UUID 另建；唯一业务修正是使用 R115 实际已定义并验证的 `helper.SyntheticRegistry()`，其 `sources()` 返回空列表。Root 和[新批独审](../../../.artifacts/material-c2-resume-20261025/implementation-review.json)均逐字对比三份可执行文件，其他变化只有固定批次路径/UUID；策略字节不变。PS7 解析零错误，固定3.14仅 AST 解析通过。这些静态检查未证明真实捕获成功。

## 新批真实结果

UUID：`9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0`。冻结2622项输入：runtime1287、dependency1166、product159及其他10项；manifest SHA256 `36904426eb991d181e00b694e495b35f3b6fcd16144b13adb32af40b8509f3dd`。Launcher 前后文件集合/字节均稳定，child 也核已绑定文件稳定。

实际完成真实私库注册、会话检查、策略目录与预览；随后一次进程内 ASGI capture POST、同 UUID history GET。该调用计数不等于来源网站的 HTTP 请求数。

| 观察 | 结果 |
| --- | --- |
| 原 UUID 查询 | HTTP200，绑定到 request `fa5b142e-2375-4269-a0f0-2bf637453ce5`，状态 `processing_unconfirmed`，failure_code/document/receipt均空 |
| 来源网络观测 | DNS审计操作1；resolver返回列表观测1，逐项验证尚未通过，因此不能称完整结果已验证 |
| 后续连接 | 已登记公网地址0、TCP socket/connect0、TLS尝试/完成0；仅观察 robots 请求协程意图，没有证明网站收到 HTTP |
| 捕获响应 | 异常类型归类为 OtherException；原回执未保存嵌套固定 Stop 码，不能追认精确触发条件 |
| 最终记录 | `network_outcome=observed_outcome_unconfirmed`，子进程exit3，没有PDF或原件receipt |

[子结果](../../../.artifacts/material-c2-resume-20261025/run-9539e5d2d28e439ea6c0c2d4aea2bfc0/result.json)3410 B / SHA256 `ce781173dc3fc424195fba122a9d3ce5c4f9dd4a405ad81ccb1e0d99610c21ec`；[原 UUID 查询](../../../.artifacts/material-c2-resume-20261025/run-9539e5d2d28e439ea6c0c2d4aea2bfc0/lookup-response.json)2435 B / SHA256 `d4984f1233fd002586a36356b47934c7ffbaf08b7f07c86f9e1f321355328a10`。

静读发现一项确定的工装兼容性缺口：profile要求 resolver 返回的 `proto` 必须6，而产品 `PublicResolver` 透传系统 getaddrinfo 的协议字段，没有该限制。aiohttp 之后的 `_convert_hosts_to_addr_infos` 忽略此字段、固定生成 TCP6 socket 信息。最小修正建议是 resolver 侧接受0/6、socket侧保留真实转换后的6，并增加固定码的异常组诊断。**本批实际是否由 proto0 触发仍未证实；不能把候选原因写成已复现根因。** 本轮没有改动该已冻结文件或进行新一轮捕获。

## 终态与后续

[Launcher](../../../.artifacts/material-c2-resume-20261025/run-9539e5d2d28e439ea6c0c2d4aea2bfc0/launcher-result.json)记录2026-10-25 06:53:23–06:53:49 UTC、PID138184自然exit3、forced=false、前后输入稳定；外层执行工具也实际返回3。Root 另确认该 PID 缺席，见[终态观察](../../../.artifacts/material-c2-resume-20261025/root-terminal-observation.json)。

Guard 七探针保持、无额外拒绝；来源窗口关闭、私有临时目录移除，观察到的1个 DBAPI 句柄关闭后探针通过。异常路径的 `lifespan_closed` 标志仍false，不能宣称正常业务生命周期验收通过。Selfpipe 内部临时 loopback listener/pair均关闭；没有 HTTP 服务。新私库作为失败证据保留，Root 终态检查只读JSON和文件指纹，没有重开数据库。

原 UUID 仍未确认，**不改用新 UUID 重发这一捕获，不把它归为站点拒绝或网络失败终态。** 下一步先在独立切片修复上述工装兼容性及有界诊断，并明确未确认记录的处理合同；本批原件与原页核验继续留账。后续材料须保持独立真实采集身份，不能绕过未确认状态。

匿名 BB/SB/CR、245/45 R18仍只是候选研究，未创建 TestEvent、SKU link、成绩排名或真人 Golden。真实 Responses API/Provider、EPREL、正常库升级、PostgreSQL、原生宿主/设备、完整 WCAG及完整 V1 均未由本轮验收。未打开正常/保留 SQLite，未commit/push/reset/stash/clean，其他 dirty 保留。
