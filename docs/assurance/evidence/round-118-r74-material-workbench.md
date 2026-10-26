# R118：R74 材料工作台重开、真实浏览器下载与资源关闭通过

2026-10-22。**本轮材料工作台验证通过：真实R74私库副本完成020→024→026迁移，当前Web构建通过；最终同一批次完成普通账户注册、原凭证可见、历史隔离、真实PDF下载及API/Web自然关闭。** API v3的27项检查与浏览器19项检查全部通过。完整V1仍active；本次材料为非SKU论文，不代表专业轮胎SKU、真人Golden、Provider或完整产品验收。前两次失败及诊断辅助文件事件分别保留，未拼接为最终通过证据。

## 当前证据层次

| 范围 | 当前已确认状态 | 证据边界 |
| --- | --- | --- |
| R74私库副本迁移 | Root正式运行及独立终核通过 | 原 R74 文件不回写，后续API另复制运行库 |
| 当前Web生产构建 | 三阶段通过，产物和恢复独立回读一致 | 不是HTTP、UI、PWA离线或设备验收 |
| 当前API与本机入站 | 最终同批27门通过，23次HTTP完整响应，5个SQLite连接确认关闭 | 仅固定本机入站、私库与两对象；未验证其他宿主的可达性 |
| Web服务与浏览器 | 最终同批Web自然关闭、浏览器19门通过，真实PDF落盘匹配 | 只覆盖本批私槽、headless上下文和两对象，不代表PWA或完整V1 |

本轮不修改产品源码，沿用现有数据库迁移器、真实 `create_app`、Uvicorn与Web组件；验证程序与运行证据位于本轮artifacts，正式结果记录于本报告及HANDOFF。未运行普通pytest、全仓测试、Provider或新来源捕获，未commit/push。

## 真实 R74 私库副本迁移

[迁移合同](../../../.artifacts/r118-material-workbench-20261021/CONTRACT-migration-v1.md)限定原字节加载旧Guard、受控依赖预热和仅私副本SQLite。Root使用v2 PowerShell与v1 runner/合同；[1395项清单](../../../.artifacts/r118-material-workbench-20261021/key-pins-migration-v1.json)455486 B，SHA-256 `64f7953034af8be281829db6cdcae8e212a57239514fdbffc3781c49e7f68188`。

[正式回执](../../../.artifacts/r118-material-workbench-20261021/run-da2799bef5254c959bea0ab1bd8eae36/receipt.json)3678 B，SHA-256 `e0109c84853894b3023b45ac8fc964283cc008ad3118a6118828f3169a76eb22`。launcher completed、五阶段通过、33检查全真；child自然exit0，stdout1881 B/stderr0，无timeout/forced。Root及独立终核确认输入首尾与live一致、R74九原件及无sidecar保持，tmp移除。

| 实际检查 | 结果 |
| --- | --- |
| 原库基线 | 123表、35行，版本001–020、legacy；普通启动preflight拒绝且不改库存 |
| 既有024迁移 | 141表，4个目标表；原列行多重集、非目标schema、FK与原材料绑定保持 |
| 当前初始化 | 版本001–026、144表；仅追加当前三张尾部表，重复initialize幂等 |
| 原材料对象 | PDF和robots两对象完整性、冻结请求/结果/文档/凭证绑定保持 |
| SQLite资源 | 实际观察6连接，固定关闭探针确认6个全部关闭 |

保留迁移库2437120 B、SHA-256 `85e4d356658914969d974ad796542d9cc141a5baf488b685654058dcfb893ee4`；SQLite backup2101248 B、SHA-256 `b686cbc03a377a85c184af0a6067f7c77b8181f69ef31926eca82f297d91dd55`。backup仅承诺与基线schema/行库存一致，不承诺与原数据库物理字节同hash。

迁移槽作为后续只读基准，API必须复制到新的运行槽；后续诊断曾产生SQLite辅助文件，已按下述事件留档并恢复，不能称该目录全程未变。原R74 DB的本轮hash是当前前像；旧最终manifest没有绑定DB，不能据此宣称历史零漂移。现有迁移器仍返回 `normal_upgrade_ready=false`、`object_bundle_entity_audit=not_performed`；本片另核这两对象，不代表全资产升级验收。

## 当前 Web 生产构建

[构建v2合同](../../../.artifacts/r118-material-workbench-20261021/CONTRACT-web-v2.md)只执行 `web-icons`、`web-next build --webpack`、`web-pwa`。新槽 `web-build-7c49e8b6a2d105f3` 的freeze2132572 B，SHA-256 `e27afcfb2eb353a4ab083b5a3f8745347d0d60b272feb4665c4690ce9d3e4355`。

[正式构建回执](../../../.artifacts/r118-material-workbench-20261021/web-build-7c49e8b6a2d105f3/verification.json)为passed，126999 B，SHA-256 `e291c5d75f0b2782f7c83afb492375b245c23285c4f3d8da4c163dbf1468157b`；Root原handle自然exit0。

三个Windows Job的observed=total分别为2/25/2，共17个product与12个console，无强停。17份Guard日志无拒绝；8个终态为own-exit-0，8个是框架父进程观察SIGINT，1个为父请求SIGINT后Native Job自然关闭，不能写成17个均own-exit-0。

[Root产物回读](../../../.artifacts/r118-material-workbench-20261021/root-build-readback-v1.json)1307 B，SHA-256 `e89786a7325b5c2a2316929ecdd8dceb97214ef363a20e38caffa8b1db819eb8`：160 sources、8983 dependencies、3 executables、8 generated pins逐项零漂移；110个Web产物和保留public五文件的keyset/hash一致；7个工作区生成文件恢复；29个精确PID均缺席。

专用dist为 `apps/web/.next-r118-7c49e8b6a2d105f3`。匹配的favicon、sw.js与三个图标保留在该构建槽 `web-public/`。工作区public已恢复，不能将它冒称为新构建产物。

## 最终同一批次：API、Web与真实浏览器全部通过

最终使用[API v3合同](../../../.artifacts/r118-material-workbench-20261021/CONTRACT-api-v3.md)与[集成v2合同](../../../.artifacts/r118-material-workbench-20261021/CONTRACT-integration-v2.md)，从原迁移基准新建运行副本，未复用任一失败库。API v3清单1488项、486584 B/SHA `7d466d2ae494f34126c6c83e7a097ab7f13d34dd63f1478125e7840a32dab18f`；集成v2清单11个直接输入、3048 B/SHA `2408122ef5b985039eefed41e24b0c6a8081a15418a8cbdae11a22d52db8dba7`，另首尾核1488 API与9687 Web/UI项。Web和浏览器源保持原已审字节。

[集成终态回执](../../../.artifacts/r118-material-workbench-20261021/integration-run-948263b3f4944eb6be04469fa16928cc/receipt.json)1763 B，SHA `64d0fb8179c32368d42d757fcd6557b60e8192fc4ee87784964a3be55612f92e`。Root原执行句柄自然exit0、status/stage均completed、failure=null；同宿主health第一次即200。API launcher、Web supervisor、浏览器Node三个原始进程句柄均自然exit0/stderr0、无forced；API18986与Web18987停止后均拒绝连接，source_inputs_stable=true。下表全部属于该集成回执关联的新批次。

| 同批证据 | 实际结果与文件绑定 |
| --- | --- |
| [API launcher](../../../.artifacts/r118-material-workbench-20261021/api-run-a3c6f468d09b473dbe3b6f1f971c893a/receipt.json) | completed，6109 B/SHA `d951303b942e7794946627a0698b543179ccc30a38ce9b10ad34993ed6287667` |
| [API child](../../../.artifacts/r118-material-workbench-20261021/api-run-a3c6f468d09b473dbe3b6f1f971c893a/child-result.json) | passed，27 checks全真，2935 B/SHA `d7dfad34b77283f63be49f0a6f07bdbe33834b1fb7f0e4c0b9fffff28b93277b` |
| [Web服务](../../../.artifacts/r118-material-workbench-20261021/web-service-dcba05a69ea9480c/service.json) | stopped，3595 B/SHA `846d9196803b1777ab8d210b8d5b4e74693da0cdf1d43fd8492094dd38287562` |
| [浏览器](../../../.artifacts/r118-material-workbench-20261021/browser-r74-e0628a76704a4ac7/browser.json) | passed，19 checks全真，3830 B/SHA `6b144eca7f68cf77c562ed4b64a541e90fc3e6bbb96b6abaaf1552a9535409ca` |
| [实际保存PDF](../../../.artifacts/r118-material-workbench-20261021/browser-r74-e0628a76704a4ac7/r74-frontiers-original.pdf) | 真实download事件后saveAs，实际3302848 B/SHA `33471a0b0d0a8c2f172b61b034a8300c65e3ff2372c79782562048133606f635`，独立文件hash与R74原件一致 |
| [本批凭证截图](../../../.artifacts/r118-material-workbench-20261021/browser-r74-e0628a76704a4ac7/source-receipt.png) | 实际查看来源、完整SHA、DOI、CC BY4.0及不授权模型/导出的范围，未含账户/密码；258964 B/SHA `a96d356c5c22b2cb5da7cd230604e2972eb3b31f6e0ebc5fce767a65d69da1a7` |

API实际23 requests=23 responses、注册POST1，HTTP denied/failed均0，请求body82 B/响应3359594 B。新普通账户能读取既有文档与凭证、下载实际原件；其材料请求历史total0/items空，旧请求幂等key返回404，当前策略catalog为空。数据库基线user1，本批新增非管理员user1、session4、audit2；两条新增审计分别严格匹配一次成功隔离列表读取及一次固定文档下载，detail完整相等、query_id/consent_id均null，原schema与其他表/旧行保全门通过。

上述可见范围沿用当前 `local_workspace` 设计：新普通账户可读取工作区既有文档/凭证，材料请求历史仍按owner隔离。本轮没有重置旧账户、扩大许可或重新捕获材料。

API实际观察5个SQLite连接，固定关闭探针确认5个均已关闭；Uvicorn lifespan、自管AI supervisor、telemetry、pool置换、selfpipe和socket门全部通过。单listener的created/bound/listened各1；accepted8，new audit0/without audit8，closed9、peak5、violations0，socket包装恢复。Guard七个预期探针各1，files四次均为既定平台探针拒绝，其他六类0。child自然exit0、stdout2936 B/stderr0，无timeout/forced，tmp移除。

最终API槽按纯文件清单独核为7文件/4目录：运行DB、两对象、ready、stop、child及launcher回执，无tmp/WAL/SHM。运行DB2437120 B/SHA `c0948367965fe5c6ae8c78c07fd7a1e74166f65177f502ccdc675e270c987afe`与launcher一致；终核没有再次打开SQLite。新运行库包含本次注册产生的账户/会话数据，不能当成无敏感信息的公开发布包。

Web实际Node exit143、Python supervisor0；Job observed=total2、active为空，guard包含listener_closed，无拒绝、无forced，构建输入稳定。浏览器为Playwright1.63.0/Chromium headless1243，原字节私复制117/292文件；GET28、HEAD0、唯一注册POST1，forbidden0、页面错误0。只对这个context的public五文件提供匹配原字节，service worker禁用；API响应未stub，真实下载落盘校验与截图观察均独立完成。这不代表一般客户端、PWA离线、原生宿主或设备验收。

[Root终核回执](../../../.artifacts/r118-material-workbench-20261021/root-completed-readback-v1.json)3597 B/SHA `e010de643ffa188232d082b63b3f3649fe8aff5585de7296bce918db22c5963d`，独核10个关键文件绑定、27/19门、实际下载与新截图、6个精确PID均缺席；其中明确 `full_live_pins_rehashed_by_root=false`，不冒称Root本人做了完整重算。另一独立终核逐项确认1488/1488唯一API pins、11/11直接输入、R74九原件9/9、迁移槽5文件/4目录与5/5文件hash保持，迁移/原R74无sidecar；新API槽7文件/4目录及DB/两对象绑定匹配。完整输入回读只用文件/清单和hash，未打开SQLite；行级语义依据本次正式runner内部保全门。

## 历史失败与修正：API v2独立工具调用

历史[API v2合同](../../../.artifacts/r118-material-workbench-20261021/CONTRACT-api-v2.md)仅授权从上述已迁移基准再复制运行库及两对象，真实普通账户注册、旧文档/凭证读取和下载。材料策略环境键缺省时，现有产品直接返回空catalog而不读工作区策略文件；数据库URL显式传入。入口只有固定18986入站，所有出站connect/DNS保持拒绝；私槽stop.request请求自然关闭。旧API清单1488项、486583 B，SHA-256 `287abb2bb73b5e47b7b2b20e05b8cf6a1845d3dee4169e6ceadecccd8ad8efee`。

[Web/UI合同](../../../.artifacts/r118-material-workbench-20261021/CONTRACT-web-ui-v1.md)限定Next18987、干净headless上下文直接 `/#/sources`、唯一注册POST、真实响应和实际下载落盘校验。Playwright117文件及browser292文件原字节复制到新私槽，外部树只读，不装依赖。Web/UI清单9687项、2436308 B，SHA-256 `7ece1357b6ed953e1d8f6b40ad0010796e4e5103fec4cfa5a7724a15441388f0`。

首次运行槽为 `api-run-7d27c8adb3ed47d6bac65f80bc9d1f81`。[child回执](../../../.artifacts/r118-material-workbench-20261021/api-run-7d27c8adb3ed47d6bac65f80bc9d1f81/child-result.json)1629 B，SHA-256 `00429dc3f94a2ae7b7aa2370e0c137bd6107955ada6e65276df3e87e33015ab4`；[launcher回执](../../../.artifacts/r118-material-workbench-20261021/api-run-7d27c8adb3ed47d6bac65f80bc9d1f81/receipt.json)857 B，SHA-256 `19343023857bb694db694c6eb590a97aac7231adf85d87ac6c6f7899be838264`。child为failed、自然exit1，launcher为child_failed，无timeout/forced，stdout1630 B/stderr0，1488项输入稳定。

该次ready之后，Root观察到Web前置探针 `exact_api_ready_and_web_port_free_required` 失败，Web槽未创建，外部端口/health检查未连通。Root写入固定5 B停止请求后，child的stop_requested、natural_shutdown、lifespan_closed、selfpipe_closed与guard_clean均真；created/bound/listened/closed各1，accepted、HTTP请求、socket violations、HTTP denied/failed均0。最终failure为 `shutdown/database`：HTTP交互没有发生，完整数据保全要求未满足；不能据尚未赋值的默认计数推断具体用户/会话检查已经执行。此结果不能记为API交互通过，也不能据外部探针失败断言进程内listener曾提前关闭；首次外部不可达的机制仍未确认。失败槽原样保留，不与后续尝试拼接成通过证据。

该失败回执的sqlite_opened/sqlite_closed均为0，是因为程序在保全检查失败后没有走到这两个结果字段的赋值点；Guard实际记录3个SQLite连接。本次没有完成逐连接关闭探针，不能把结果字段0解释为未打开连接或已证实泄漏。

### 历史同宿主集成首轮：Web/浏览器通过，整批失败

Root随后冻结并运行一次性[同宿主编排合同](../../../.artifacts/r118-material-workbench-20261021/CONTRACT-integration-v1.md)：保持API v2、Web与浏览器源不变，在一个PowerShell宿主中创建三个独立新槽，先健康GET、再Web、浏览器，最后依次停止Web和API。集成清单3048 B，SHA-256 `7855906f7a5198376085ac3463851c5b6e4ff29f6a2924ec90cca5524b943558`，绑定11个直接输入并首尾复核1488 API/9687 Web UI项；未将其称为完整import closure。

[集成回执](../../../.artifacts/r118-material-workbench-20261021/integration-run-58bb9ad74ce54aeda60a3c8835f0805c/receipt.json)1773 B，SHA-256 `6da750999b3dfc8bc71fbe7ef7502f94b9bef52fbbca3ba93db7ac2762e3b755`。同宿主health一次200，源输入稳定，三子进程均未强停；最终status failed、stage api_stop、failure_code api_natural_stop_failed。此轮只证实同宿主链路可达，不能反推首次独立工具调用不可达的机制。

| 本轮实际证据 | 已读回结果 |
| --- | --- |
| [浏览器回执](../../../.artifacts/r118-material-workbench-20261021/browser-r74-951b5dceebe84aed/browser.json) | 3830 B，SHA `e7e1b3fba0f255c643e761f3a4af23a1b0101d1c3bd7ef29a3795f9d8c150d75`；19检查全真，Node自然exit0，GET28/注册POST1/forbidden0，页面错误0；私复制Playwright117/browser292文件 |
| [真实保存PDF](../../../.artifacts/r118-material-workbench-20261021/browser-r74-951b5dceebe84aed/r74-frontiers-original.pdf) | 实际浏览器download事件后saveAs；独立重算3302848 B、SHA `33471a0b0d0a8c2f172b61b034a8300c65e3ff2372c79782562048133606f635`，与R74原件匹配 |
| [凭证截图](../../../.artifacts/r118-material-workbench-20261021/browser-r74-951b5dceebe84aed/source-receipt.png) | 258964 B，SHA `a96d356c5c22b2cb5da7cd230604e2972eb3b31f6e0ebc5fce767a65d69da1a7`；Root及独审实际查看，来源、完整SHA、DOI、CC BY4.0与不授权模型/导出的限制可读，未含注册账户/密码 |
| [Web回执](../../../.artifacts/r118-material-workbench-20261021/web-service-06eaa6af1b954c30/service.json) | 3417 B，SHA `c0810b35c862eaa90f1cc7fb5220a08522d2c7da6d0059757ae4242be228fc4c`；Python自然exit0、Node143，Job observed=total2、active为空，无forced，listener_closed、端口拒绝连接、构建输入保持 |

[API child](../../../.artifacts/r118-material-workbench-20261021/api-run-e6f385be9a324e27893d4b8a209d6278/child-result.json)2974 B，SHA `6be5e5bc58bd10161c30490ce0e4c388a55d719c4788baa5a41269d0d5b34875`；[launcher](../../../.artifacts/r118-material-workbench-20261021/api-run-e6f385be9a324e27893d4b8a209d6278/receipt.json)857 B，SHA `9064a04d7d64393c52d1b87542b252ece1c4e712e57b790b1c7b2b4d6a8d293c`。23 requests=23 responses、注册POST1，body请求82 B/响应3359594 B，HTTP denied/failed均0；文档/凭证/实际原件响应、普通账户、历史0/旧key404/空策略目录的对应门均真。7 accepted均走无socket.__new__ audit分支，closed8、peak4、violations0、包装恢复。

API收到stop后natural_shutdown、lifespan_closed、selfpipe_closed、guard_clean均真，launcher自然exit1，无timeout/forced、stderr0、1488输入稳定；但preservation在database阶段抛错，整体为failed。已确认是验证器遗漏了正常来源页读取产生的审计：v2仅允许新增 `evidence_document_downloaded`，而现有产品 [quality.py:320](../../../apps/api/tire_api/quality.py#L320) 的GET `/v1/quarantines`会写 `quarantines_list_read`，下载在 [documents.py:131](../../../apps/api/tire_api/documents.py#L131) 写对应下载审计。

经Root协调的Node内置SQLite `readOnly:true` 比较既有/新增audit_events.id，迁移基准4行变为本次运行库6行；新增恰为 `quarantines_list_read`（source_id=null、limit=50）和固定R74文档/原件SHA的 `evidence_document_downloaded`，两者query_id/consent_id均null；不是注册审计。该只读诊断未另写结果文件，本报告绑定实际保留数据库：迁移基准2437120 B/SHA `85e4d356658914969d974ad796542d9cc141a5baf488b685654058dcfb893ee4`，失败运行库2437120 B/SHA `027e353b528185ad117491c8cc736dea26da7c4dca0ae32d7be24a3ecec8b48e`。两文件长度与hash已独立回读。修复应严格核对这两种动作与成功路由响应，不放开任意新增审计，也不修改产品现有读取审计。

后续database_preserved/objects_preserved/database_handles_closed/http_complete/sockets_closed门未完成；其中sqlite结果计数仍未赋值，Guard实际观察5连接，不能据字段0断言泄漏或全部关闭。

### 只读SQL诊断的辅助文件副作用与恢复

上述Node `readOnly:true` 查询在2026-10-21 17:23:44 UTC为迁移基准及失败运行库各生成一对WAL/SHM；因此“只读SQL”没有保证目录无写入。两个WAL均0 B，两个SHM均32768 B/SHA `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`。Root先确认四文件与两主库可独占只读打开并关闭，再使用原生Move-Item将四辅助文件原字节移入独立incident槽，不覆盖历史回执，也未通过SQLite执行恢复。

[事件回执](../../../.artifacts/r118-material-workbench-20261021/sidecar-incident-6d2aca0ce83e469288a57410a8fdfc2c/receipt.json)3156 B，SHA `592d61a0e676ca0c1e5d9502ef9ef4bcd38a1f84c123cf634211527f077b9f18`，附before.json及四原辅助文件。独立复核留档文件hash、迁移主库SHA `85e4d356658914969d974ad796542d9cc141a5baf488b685654058dcfb893ee4`、失败运行主库SHA `027e353b528185ad117491c8cc736dea26da7c4dca0ae32d7be24a3ecec8b48e`保持，两个原槽当前WAL/SHM均不存在。仅能说主库字节保持、辅助文件留档后目录恢复，不能说基准目录全程未变。后续独立终核仅文件hash/清单回读，不直接打开这些保留SQLite库。

修正仅进入新API v3验证器：严格限定上述两种审计动作、detail及对应路由各一次200响应；用户、旧行、其他表和资源门不放宽。随后全新集成v2批次独立通过全部门，未追认这两个旧失败槽为通过。

上述历史批次和最终批次都只覆盖各自headless上下文，不能扩大为一般客户端或PWA离线验收。

## 未执行候选与后续边界

| 候选 | 静审发现及处理 |
| --- | --- |
| 迁移PowerShell v1 | 不兼容Windows stdout的CRLF；v2只修一行JSON终止符及自身绑定，旧v1未执行 |
| Web构建v1 | Node argv正反斜线严格比较阻断；v2统一路径并保留匹配public五文件，v1未freeze/run |
| API v1 | 错误要求accepted必有socket.__new__ audit；v2依据R117真实无audit分支，仍核原accept/真实SocketType/固定两端地址，并分账计数；v1未执行 |

原R74材料的PDF为3302848 B、SHA-256 `33471a0b0d0a8c2f172b61b034a8300c65e3ff2372c79782562048133606f635`；document为 `55bc1948-fa4f-4312-9635-de46a6eaa130`。旧请求lookup使用idempotency key `be866119-a633-4764-8866-1f82262be53b`，不是request_id。凭证内容真实性仍为unverified、引用关系为operator_configured、accepted_as_facts=false，provider_use/export=false。

R74是非SKU材料；本片不满足专业轮胎SKU、真人Golden、Responses/Provider、正常库升级、实际PostgreSQL、原生宿主或设备验收，也不扩大许可、不认证内容、不将本地重开说成重新捕获。Python/Node Hook不是OS沙箱，pins不是完整import closure，native/cached盲点及父进程流捕获无硬内存上限仍在。用户已确认没有EPREL Key，继续独立任务，不再索要该凭据或材料URL。

后续继续完整V1其余独立工作，优先按既有验收清单补齐实际来源覆盖、专业SKU/真人Golden及尚缺的运行环境证据；不要以本次非SKU材料代替它们。R117和更早“未验材料工作台/浏览器”等语句属于各自历史时点，本轮仅更新当前已取得的R74本机工作台证据，不改写旧失败事实。
