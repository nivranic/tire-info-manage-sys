# R117：真实 Uvicorn loopback TCP 受限验证通过

2026-10-21。Root 正式 v4 批次及独立终核通过，真实字符串入口 `tire_api.main:app` 在固定私库环境完成六条 loopback HTTP 请求、自然关闭及端口拒绝探针。产品 main 未再修改，仍为 27905B、SHA `57545ed00e1d9f90024adab1b4242143a4426360b9f54a068adffe9624f2365f`。[R115](round-115-lazy-app-factory.md) 的进程内 ASGI 与 [R116](round-116-main-lazy-regression.md) 的七项持久回归保留为独立证据，本轮未重跑普通 pytest 或全仓测试。

## v4 正式结果

[合同](../../../.artifacts/uvicorn-tcp-verification-20261021/CONTRACT-v4.md)限定 CPython 3.14.8、uvicorn 0.54.0/click 8.5.0/h11 0.16.0 overlay、十键清空子环境和私有 SQLite/objects/tmp。沿用旧 Guard、受控依赖预热与 selfpipe 能力；Uvicorn 用真实字符串入口解析默认 app，未替换工厂或 registry。

依赖准备单独记账：v1因未识别固定marker失败，只下载并校验Uvicorn wheel，无overlay/manifest；v2在TLS建连失败，downloads为空，无overlay/manifest。v3复用已校验的原Uvicorn wheel字节，下载其余两包，静态解包共三包、90文件、845833B，未执行Python、pip或安装钩子，详见[准备manifest](../../../.artifacts/uvicorn-tcp-verification-20261021/dependency-preparation-v3/package-manifest.json)。这是独立准备结果，不拼接任何运行回执。

[1509 项 pins](../../../.artifacts/uvicorn-tcp-verification-20261021/key-pins-v4.json) 为 493078B、SHA `99d0a09acdc1407a52b357b4cda36369f1fd3ae51cfaa57cf395bc538ef1fea6`；完整复核 v3 的1507项后，继承1502项、加入五个新源及v3 pins/回执两份证据，旧v1/v2证据继续保留。1509项声明、唯一集合及独立live逐文件长度/SHA核对均匹配、issue0；该集合不是完整传递 import closure。

[正式回执](../../../.artifacts/uvicorn-tcp-verification-20261021/run-f614022aae9b416eb02415c38556a991/receipt.json) 为 6254B、SHA `af7f99449cc95db4b5a667ac5f8c2bb48e727baf1be11533485dab3c9f4b7cc2`。launcher completed、五阶段 passed、输入首尾一致；自然 child0，stdout3345B/stderr0，无 timeout/forced，原始流未落盘。

| 实际覆盖 | v4 回执 |
| --- | --- |
| 真实默认 app | factory/Database/Telemetry 构造各1；251 routes、真实 registry、私库/objects、遥测禁用 |
| 六条 HTTP/TCP | requests=responses=6；observability/health/sources 为200，untrusted host为400，cross-site为403，external无Bearer为401；六个检查全真 |
| 自然关闭 | serve自然返回、lifespan启动/关闭成功；tasks/connections空，AI supervisor/telemetry关闭，pool替换 |
| 跟踪 DBAPI | opened=closed=confirmed_closed=1；固定关闭句柄探针通过，不代表系统全部句柄 |
| HTTP socket | listener1/client6/accepted6/negative1，共14对象，全部fd关闭；unique close为1/6/6/1；无违规、强制清理或首拒，包装恢复 |
| 协议与拒绝探针 | accepted metadata `default_0=6,tcp_6=0`；单次负连 `10061/refused`，2042ms，timeout配置5秒，异常字段null |
| Guard/清理 | 七探针各1，预期files拒绝4、其他拒绝0，SQLite连接1；tmp探针/残留/移除=true/0/true，db/objects移除，无清理issues |

accept_budget_stops=6、accepted_new_audit=0、accept_empty=0。旧selfpipe仍为受审单窗口 `stdlib_loopback_fallback`，内部临时listener bind/connect各1、pair关闭；不能将本轮描述为只有一个系统TCP listener。launcher确认落盘前私槽为空，现场回读只剩receipt。端口拒绝只证明观察时不可连接，不保证未来不被重用；budget stop也不观察OS待接受队列。

## 先前失败批次不拼接

三批均自然child1、stderr0、无timeout/forced，回执记录输入首尾一致及私有目录清理完成，仍各自整批失败。

| 批次 | pins / 回执字节 | 保留的失败事实 |
| --- | --- | --- |
| v1 | 1503项 / 1441B | tcp/observability，首拒tcp_accept_peer_invalid，serving、违规2；不能识别具体子项 |
| v2 | 1505项 / 1977B | 同首拒；仅accepted_proto_tcp=false，其余十个布尔真，operation=none、errno=null |
| v3 | 1507项 / 1502B | shutdown/negative_connect，TcpCapabilityDenied/capability_invalid；首拒tcp_negative_refusal_invalid，违规1、accept_failure=null |

v1 [回执](../../../.artifacts/uvicorn-tcp-verification-20261021/run-35d60862e8214150b8e49167195a447a/receipt.json) SHA `396fccb3cd017ce2d4e6aa47286aec9145878722f969344b44a725b36360a2c4`；v2 [回执](../../../.artifacts/uvicorn-tcp-verification-20261021/run-b2b9c97701744fc8b725b383fdd2c874/receipt.json) SHA `4ae0814a8ea1b079c9e6f391a39322163f6dc09d4530eae47661db87eee0d374`；v3 [回执](../../../.artifacts/uvicorn-tcp-verification-20261021/run-4b2aee1e954a4437a1bbdd78ebeff1fe/receipt.json) SHA `451ab4109a5e91668a9d6b19c927f5f2ff11909cd4caa9d2365e9322eec07c25`。各自pins SHA依次为 `7362b77da647ac8588e8873ad13b42f9f018682b3427b3fad0b538c968740db8`、`d0057907070f21d58199c5704a2ef64f735e2db20ee964810c5e0a2b60d2a3ad`、`30723228dcdcd77248ced21bf8d6393494c539e1a87547da4bf1770ddb64bbbf`。旧源、pins、回执原字节保留。

## 两次有限调整与证据边界

v2只增失败诊断，不改成功谓词；它未记录实际协议整数。CPython `Lib/socket.py:291–305` 显示accept包装原fd，同版socket文档1555–1559、1908–1914区分默认协议0与fileno的Python表示、实际OS资源；文档SHA `1374d2ed505eb58d34987307507ca26c1719db246312d290d3dd20180ba2a757`。据此v3仅对已登记TCP6 listener的原始accept结果，在类型/族/fd及local/peer绑定完整时容许metadata为整数0或6；其他创建、listener/client/负探针、bind/connect及审计门仍严格协议6。TCP来源依据是原始accept和对象/fd/端点绑定，不能单靠metadata宣称内核协议证明。

v4仅把同端点单次负向探针的socket timeout由1改5秒，增加七键有限诊断，无重试；cap/runner仍严格要求原Python拒绝码，Windows launcher额外要求10061。5秒是操作配置，不是墙钟硬上限。v4首次实际记录accepted为0及负连2042ms/10061；这不能回填v2实际协议，也不能证明v3因1秒超时失败。v3失败投影没有六条响应、协议分类、DBAPI计数或负连返回码，本轮不倒推这些值。

成功仅覆盖固定环境、受控依赖预热、真实默认app、私库lifespan与六条loopback路径；未证明自然冷导入/WMI、正常库及迁移、实际PG、真实材料/许可、Provider、全部路由、浏览器、设备或完整V1。Python hook非OS sandbox；native/cached盲点、非完整pins及流捕获无硬内存上限仍在。V1 active，provider/export=false，未commit/push。

下一步先核R74/R97/R98已覆盖范围，仅补尚缺的真实材料工作台闭环；新捕获另用新UUID并逐项复核robots/许可，不重写R72，不把unknown SKU升级为Golden。真实SKU/真人Golden、Responses、PG/平台分别记账，不需要EPREL Key。HANDOFF保留原133282B、SHA `928451fcc3133827fd11dfbd7f388a0ddc44b1356e419883be0f3abbaee34524` 为完整原字节尾文，正式文档由Root唯一应用。
