# R134 来源原文变化监控

2026-10-25。已补上“原文变了、结构化参数没变时没有提醒”的主链缺口。最终新私库生产 Web 通过4个场景、49条检查，Root实际看完三图，收尾71项通过。此处49是检查记录数，不是49个独立测试。完整V1目标仍active。

## 已交付

新增来源级 `page_changed` 事件及共享历史提醒；它们独立于SKU的 `ChangeEvent` / `LocalNotification`，不制造SKU身份。只比较同一已登记轮胎来源、canonical query及同URL成功采纳的UTF-8文本原文。首次采纳建立基线，304、失败、隔离和不同查询/URL不产生本类事件；哈希不同只表达原文变化待人工核对，不证明页面语义或参数变化。

`029_source_page_monitoring` 迁移登记两张表。事件按本次Verification唯一去重；A→B→A→B可分别记录。采纳、事件和提醒共事务及既有ingestion锁，保留任务lease与来源generation。仅首次插入新事件时评估规则，既有事件重入不重评或补投；评估使用同锁下当前latest修订，并限制rule/revision.created_at不晚于本次Verification.verified_at。暂停、归档或之后新建规则不补发历史。

页面规则独占 `page_changed`，variant=null、fields=[]、conditions={}；不能在页面/参数模式间互换既有规则。通知冻结当时规则修订与前后snapshot、verification、raw_hash、观察/核验时间及解析器；只允许修改已读时间。SQLite防REPLACE及PostgreSQL历史保护已实现，真实PostgreSQL未执行。

历史列表仅投影元数据，不读取Snapshot正文/parsed_variants。独立的list/detail/read路由使用 `scope=local_workspace`、`data_state=local_snapshot`；详情复核两侧正文SHA，再允许打开原证据。损坏引用/元数据/哈希统一固定503，缺失通知404；只窄捕获解码异常，不吞DBAPI或审计守护异常。

前端手工表单新增来源原文变化类型，默认暂停，隐藏SKU、字段和技术条件；历史提醒与原SKU提醒分开，明确本机共享范围，支持分页和未读过滤。双侧按钮每次先核详情，再复用原证据检查器；没有新增模型调用或页面提醒AI解释入口。SDK新增独立三方法及可选取消信号，旧通知合同保留。

AI草稿仍仅支持原来的两类提醒。Apply在新写入前核提交kinds属于冻结capabilities；合法已应用payload保留提前幂等返回，改payload保留原409，不能借扩展通用RuleCreate绕过能力门。

原安全回归入口的cleanup改用 `vars(loaded).get('app')`，不触发lazy默认app构造；已有实例才dispose。显式测试清单实际179项（177 API+2 Worker），新模块已登记。只针对本轮范围修改，17个旧文件及8个新文件初始状态见 `plan-before.json`，不以全仓dirty差异代替本轮范围。

## 实际验证与范围

所有后端业务测试复用原 `run_api_worker_regression.py` 守护、新私槽和工具require_escalated。未打开正常或保留SQLite，未启动默认API。使用项目venv Python3.12.10；它不同于C2冻结的3.14环境。

| 证据 | 实际结果与界限 |
|---|---|
| cleanup纯stdlib小用例 | helper加入前4 errors，加入后4通过；不冒充完整pytest/应用守护 |
| selfcheck / collect | 自检通过；57项只收集，protocol/test执行0 |
| 初稿core-a | 57/57，后续补过旧表夹具和坏JSON负例，不能替代最终新增覆盖 |
| 最终core-b | 两个来源页面模块47/47，0失败/跳过/incomplete，sources_stable/resources_closed=true、unexpected denials0 |
| 相关regression-a | 160/160，涵盖旧监控/条件/AI草稿/任务、Worker页面规则真实调度入口、旧迁移精确节点及启动schema；稳定、关闭、拒绝门通过 |
| 前端 | Web/desktop/mobile各noEmit exit0；新SDK tsc exit0、Node6/6。收据是事后工具摘要，仅检查后采pin及再次复核，未采执行起止或运行前pin，不冒称全过程监测 |

两批pytest数字不能相加冒称独立测试总数。旧028迁移夹具补四张关键父表、三个索引和非空历史行，对对象、行和cell字节保全；它是独立历史监控切片，**不是完整已部署旧库升级验收**。Worker通过测试内实际入口；生产UI没有启动Worker守护进程。

最终a134 Web生产构建通过，三阶段0，181个源记录、8983个依赖记录稳定，生成原件恢复；Next Job25/25、全观察、active空、自然资源关闭。freeze为2137495 B / SHA `c5459ab3dba957f9b05980638af565ba9066ff408186610334121cb7bbe528a6`；verification为129130 B / SHA `6470197021ab106e011c9d4d5e10e6a8f0449d177fa3cac18f47dafa512f1b83`。构建和PWA生成不代表离线/安装验收。

首UI a134在7条检查后等待类型选择超时；实际弹窗已打开但类型仍为原模式，无保存POST，错误门空。静读确认exact隐式label包含select选项文本，随后只改三处select定位为label内精确标题定位其select。首失败、原脚本和资源终态保留；没有改产品或放宽请求/控制台/cleanup门。之前工装元数据把12400字符误写成UTF-8字节，已校正为12584 B，单独修正不改变JS。最终脚本SHA `65e874672601b15bead382c1cec8e56216ab8703ef98a107b0400086c0fcd723`，差量独审ACCEPT。

最终b134同批生产UI4场景/49检查通过：真实私库注册管理员、实际UI创建启用规则；UI对两源各查询两次。两源variant ID及facts投影SHA完全不变，仅A原文变化产生新snapshot、一条来源级提醒；B沿用原snapshot。实际UI已读PUT及未读过滤通过，两次detailGET后打开两次证据GET，正文SHA各匹配冻结引用。全批页面59个请求（含静态）；初始化/核对使用APIRequestContext，未合并成页面请求数。

合成来源fetch4；真实外部来源、Provider、model、embedding均0，外连/子进程/正常库attempt计数0。实际UI规则POST1、已读PUT1、详情GET2、证据GET2。page/console/HTTP/外源/cleanup错误全空，console_events也为空；9306输入和prepared runtime稳定来自QA记录，Root没有另重扫全量。后端7个产品pin显式连接独审、当前文件、fixture.sources_before/after，14个后端相关输入连接两批pytest源记录；不靠Web freeze声称后端已绑定。

Root实际看完1365×900表单、通知及390×844原文三图。表单图可见尺寸后直接到间隔，没有SKU/字段/技术区域；独立的SKU exact-label负例本身证据较弱，结合条件渲染源码和截图判断，不把单独count=0当强证。默认暂停由可靠checkbox断言证明，截图已手工启用。通知两侧信息和按钮可读；390px哈希换行且原文展开，`page_text_revision=1`可见。底部toast/导航遮挡部分长原文，顶部表单标签因滚动位于粘性标题后，不能声称任意位置全文无遮挡。

最终host三子进程0/0/0、forced空，Chromium0/null及server-close；Web Node143、Job2/2全观察、active空，fixture shutdown_complete。Root实际核35个指定PID全缺席、无查询错误，18986/18987各5秒上限探针10061；首红批资源另有相同数量终态观察。执行均已结束，不需重跑通过批。汇总资源关闭不等于逐DBAPI句柄关闭或删除私库；Python guard/Job不是OS sandbox，保留R133已验证的require_escalated执行上下文，不改ACL/guard。

Root收尾脚本首次因误从stopped读取仅started有的标记而KeyError，未生成成功回执；修正为读取真实started记录后实际exit0/71项通过。最终root-closeout SHA `46915fc540536d9a9ffb538d503feb17e29d1ab3730d8cc2f30206c4a7ba0dab`。产品/构建冻结/QA差量的静审ACCEPT与实际运行、看图分开记录。运行证据独立复核ACCEPT，确认后端/前端/runner哈希映射、35PID并集、三PNG字节与尺寸及上述范围；该复核只读文件，不代替Root实际执行或观察。

## 留账与接续

本轮覆盖已登记来源固定query的成功采纳文本，不是任意网页/二进制/PDF差异监控。真实上游、真实Responses/Provider、专业精确SKU/真人Golden、正常库整体升级、真实PG、原生宿主/设备、完整WCAG/读屏及PWA离线继续留账。EPREL无Key不再询问。C2原UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0`仍processing_unconfirmed，PDF未取得，不能换UUID重发或重开保留私库。

下一候选为本人关注范围的轮胎来源质量隔离提醒：目前SourceQuarantine只入质量面板，不发布兴趣通知。它是原质量管理/相关变化需求与既存待办的交集，原规格未逐字单列该名称；计划先冻结采集状态语义与显式订阅，再实施。候选不是采纳事实，不能据隔离断言SKU消失或参数变化。本轮未实现这项。

未commit/push/reset/stash/clean，保留其他dirty；HANDOFF更新时以本轮before副本为原字节尾文保全。

## 证据入口

- [计划](../../plans/2026-10-25-source-page-change-monitoring.md)、[wire](../../../.artifacts/r134-source-page-monitoring-20261025/wire-contract.md)
- [最终47项目标](../../../.artifacts/r134-source-page-core-b-20261025/result.json)、[160项相关回归](../../../.artifacts/r134-source-page-regression-a-20261025/result.json)、[前端实际工具摘要](../../../.artifacts/r134-source-page-monitoring-20261025/frontend-checks.json)
- [生产构建](../../../.artifacts/r118-material-workbench-20261021/web-build-a1340a1b2c3d4e5f/verification.json)、[最终UI](../../../.artifacts/r134browser-b1342c3d4e5f6071/result.json)、[保留首失败](../../../.artifacts/r134browser-a1341b2c3d4e5f60/result.json)
- [Root71项收尾](../../../.artifacts/r134-source-page-monitoring-20261025/root-closeout.json)、[实际三图观察](../../../.artifacts/r134-source-page-monitoring-20261025/root-visual-review.json)、[实际资源观察](../../../.artifacts/r134-source-page-monitoring-20261025/root-resource-observations.json)
- [后端独审](../../../.artifacts/r134-source-page-monitoring-20261025/product-review-backend.json)、[前端独审](../../../.artifacts/r134-source-page-monitoring-20261025/product-review-frontend.json)、[QA差量独审](../../../.artifacts/r134-source-page-monitoring-20261025/qa-review-exact-label.json)
- [运行证据独审](../../../.artifacts/r134-source-page-monitoring-20261025/runtime-review.json)
