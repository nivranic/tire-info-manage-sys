# R131 来源冲突记录文案：实施与验收

2026-10-23。本项通过；完整 V1 仍 active。没有 EPREL Key，继续独立工作，不重复询问。

## 问题与修改

来源冲突的 `resolution` 是兼容字符串，没有裁定 ID、人员、时间或依据。已查正式后端生产者仅写 `unresolved`，本轮没有观察到正式生产 `resolved` 或实际库命中。兼容 facts 可透传其他状态，原界面可能同屏显示“尚未裁定”和“已有裁定记录”；这是代码可达的展示语义问题，不能称为已经发生的生产事故。

本轮只替换 `apps/web/components/workbench.tsx` 五处文案，DOM、条件、请求、样式与数据逻辑未改：

| 位置 | 当前文案 |
| --- | --- |
| 查询汇总 | 当前来源快照有 {n} 项字段冲突记录 |
| 查询/关注卡片标题 | 原记录中的来源字段冲突 |
| 卡片说明 | 下列保留原记录的不同取值及处理状态；默认展示值和人工核验不会改写这些记录。 |
| 保存比较标题 | 保存时的来源字段冲突记录 |
| 精确 `resolution === "resolved"` | 原记录标记已解决 |

其他状态仍为“待核验”。保留 `hasFieldConflict`、摘要风险和当前比较的“默认值不代表裁定”；默认展示值、人工核验与原快照冲突继续独立。计划见[冻结方案](../../plans/2026-10-23-source-conflict-record-wording.md)，五次单处字节替换见[变更记录](../../../.artifacts/r131-source-conflict-records-20261023/product-changes.json)。最终 Workbench 为 120900 B / SHA256 `191faf6df251908e6369d9ca0adfdab5bf0de3af4c8546774ae2fd32512bb1e3`。

## 验证与修正

Web、desktop、mobile 三端 noEmit 实际均 exit0；最终 QA 的 Node 语法检查 exit0，未变薄宿主 AST 解析 exit0。记录位于[本轮目录](../../../.artifacts/r131-source-conflict-records-20261023/)。

首构建 `a1310a1b2c3d4e5f` 保持 failed：Next 根进程 exit0，但 Job 总进程25、只观察24，严格进程清单检查失败。没有改守护阈值。生成原件已恢复、自然宽限后 active 空；Root 后续确认26个已知 PID 缺席，不能追认漏掉的那个身份。见[原失败回执](../../../.artifacts/r118-material-workbench-20261021/web-build-a1310a1b2c3d4e5f/verification.json)和[后续观察](../../../.artifacts/r131-source-conflict-records-20261023/first-build-observation.json)。

新[生产构建 b131](../../../.artifacts/r118-material-workbench-20261021/web-build-b1311b2c3d4e5f60/verification.json) passed：三阶段0、源码与依赖稳定、生成原件恢复；Next Job25/25全部观察、根进程0、active空。回执130931 B / SHA256 `0bfd6beb5a0e770ab56376757cc31180b77e2ac3f22889f46ff647ad6c5d0e47`。构建器和守护未改。

QA 首稿独审发现 P2：保存比较截图的 `scrollIntoView(start)` 会把新标题放到 sticky header 后面。只修改 `shot()`：实际测量 sticky 下边缘留8px、逐行 Range 和三点命中检测，并检查汇总自身横向范围。首稿及 [REQUEST_CHANGES](../../../.artifacts/r131-source-conflict-records-20261023/qa-review.json) 保留；[最终独审](../../../.artifacts/r131-source-conflict-records-20261023/qa-review-final.json) ACCEPT。

## 同批浏览器证据

[最终 a1312c3d4e5f6071](../../../.artifacts/r131browser-a1312c3d4e5f6071/result.json) passed，2477769 B / SHA256 `dd38672f252b0b35488916d8ade70da6330b38eb1237131dae80ceca2fdc284f`。5场景、128条检查记录（不是128个独立测试）、38条观测，9298项输入及准备运行时稳定。

- 11道受控请求门完成并移除：3道真实私槽 HTTP（两次来源查询26/3行及一次证据 GET），8道 route 合成（4 query、watch GET、只读 compare POST、saved list/detail GET），合成响应没有后端 dispatch。全批实际33次业务请求（含初始化与视图只读 GET）、总42请求/126事件；11不是全批请求总数。
- 10个纯 UI 操作窗口零新增业务请求。没有真实关注或保存写入；兼容状态、默认值与人工视图组合明确合成，不冒充后端已生产 resolved。
- 11种兼容状态包括精确 resolved、unresolved、缺失、null、空串、未知值、大小写变体、前后空格与纯空白。精确匹配才显示“原记录标记已解决”；false、0、null原值语义保留，默认值与人工视图不改写原状态。
- 查询、关注、当前比较及保存比较覆盖；page/console/异常来源/异常HTTP/gate/coverage/cleanup错误全空。fixture source_calls=2，真实外部来源、Provider、模型、embedding调用均0；外网、子进程与正常库尝试均0。

[独立运行证据复审](../../../.artifacts/r131-source-conflict-records-20261023/runtime-review.json) ACCEPT，静态重算同批请求、状态矩阵、标题断言、截图指纹与终态。审查员未运行服务、浏览器或探针，未看图、未重扫9298输入，与 Root 的执行及看图区分。

## 视觉与结束状态

Root 已实际查看最终九图，见[视觉记录](../../../.artifacts/r131-source-conflict-records-20261023/root-visual-review.json)：查询汇总、混合冲突卡片及保存比较在宽屏和320px下可读；关注与当前比较完成宽屏查看。新标题、说明及状态无横截断。保存比较标题宽屏 top137.375 > sticky129，320px top106.65625 > sticky99；范围与命中断言均通过。长列表需要滚动，不声称11/13条记录全部同时同屏。未完成全部主题、真实设备、读屏或完整 WCAG 验收。

[宿主](../../../.artifacts/r131uihost-a1312c3d4e5f6071/receipt.json)实际自然0/0/0、forced空；Chromium45556自然0/null/server_close；Web Node52552退出143、Job2/2、active空；fixture shutdown_complete。Root 实际核对35个精确 PID 缺席且无查询错误，18986/18987各5秒上限探针10061，见[资源观察](../../../.artifacts/r131-source-conflict-records-20261023/root-resource-observations.json)。所有本轮执行均已结束，无需重跑已通过的检查。

[Root 收尾核对](../../../.artifacts/r131-source-conflict-records-20261023/root-closeout.json)实际 exit0、47条检查通过，7802 B / SHA256 `4b0a8748b09f1c0cfcb6934d411dc9c10e5fdb4bf14f7104eddb882137d17614`。核对五次精确替换、类型/语法、构建/UI/评审/终态回执与九图；9298完整输入稳定来自 QA 回执，Root 未重复全量扫描。汇总关闭不等于逐 DBAPI 句柄关闭或私库删除证明；Job/guard 不是 OS sandbox。

## 后续业务缺口

下一项推进 KIT C2 真实专业材料捕获及原页核对：先把旧固定捕获工装与已恢复的受限执行入口对齐，再用新 UUID、新私槽和新 manifest 单次运行。旧 C2 批已 exit3，停在 `before_product_import/child_process_forbidden`，POST/GET均0、network未观察；不是运行中或站点拒绝，不能重用旧批次。已知245/45 R18及匿名BB/SB/CR仅是候选研究，取得原件后还需核版权、页码和实测值；匿名身份不能升级为精确 SKU Golden。

真实 R74 原件已存在，但其离线解析与 R119 合成 Golden 不构成真实精确 SKU/真人审核闭环。真实 Responses API/Provider、EPREL Key、正常库升级、PostgreSQL、原生宿主/设备与完整 WCAG 继续留账。本轮 SW blocked，不给当前 PWA 安装/离线结论。正常/保留 SQLite 未打开、默认 API 未启动；未 commit/push/reset/stash/clean，保留其他 dirty，完整 V1 保持 active。
