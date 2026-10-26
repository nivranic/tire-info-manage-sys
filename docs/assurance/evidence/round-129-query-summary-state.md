# R129：查询总栏终态与可读性修复

2026-10-23。**本轮通过，完整 V1 仍 active。** 所有来源已结束却没有可用结果时，总栏不再显示“等待可核验结果”；待授权、提交决定、全部拒绝、部分成功和成功零匹配分别呈现。首批看图发现新文案沿用旧计数标签的小字号，随后补专用样式并完成新构建、新页面批次。

## 问题与最终实现

原规格要求在线失败后明确显示来源不可用，再询问回退授权。旧总栏只判断 `runs.some(hasQueryData)`，无可用 DTO 时固定写“等待可核验结果”；来源卡片本身已有正确错误和授权反馈。本轮修复这处总栏与卡片状态不一致，没有改后端协议或授权流程。

按[冻结计划](../../plans/2026-10-23-query-summary-state.md)新增纯 `getQuerySummary()`，复用原有 `hasQueryData()` 判定与 SKU 计数。HTTP200 不直接算成功，`live`、`live_verified_304`、`local_snapshot` 才是可用 DTO；成功零匹配仍显示 `0 MATCHED SKU`。摘要不新增请求、effect、计时器或持久化。

| 状态 | 总栏行为 |
| --- | --- |
| 正在请求来源 | 正在在线查询，busy=true |
| 正在提交允许或拒绝回退 | 正在处理回退决定，busy=true；不声称已读取快照 |
| 在线结束、尚待用户授权 | 在线查询未完成，等待回退授权，busy=false |
| 全部拒绝 | 已拒绝全部回退，本次无可核验结果 |
| 请求失败、业务不可用、目录/许可阻断 | 本次未获得可核验结果；各来源卡片保留具体原因 |
| 授权提交失败但仍有旧 consent_required DTO | 按当前错误进入无结果终态，不误报仍在等待 |
| 有可用结果或零匹配 | 保留 MATCHED SKU 和来源数量；其他来源的查询、决定、待授权、拒绝或失败按数量并列显示 |

原 status span 加 `role="status"`、`aria-atomic` 和由真实动作派生的 `aria-busy`。专用 `.query-summary` 样式为 12px、1.6 行高、正文颜色及可换行，覆盖原 7/8px 计数样式；其他标签、toast、菜单、表单未重设样式。范围增加依据见[可读性补充](../../../.artifacts/r129-query-summary-20261023/scope-amendment-1.json)。

最终只改三个产品文件并新增一个测试文件：

| 文件 | SHA-256 |
| --- | --- |
| `apps/web/components/query-summary.ts` | `c67e4b44142e0bedf00395477cde82c5b0601f25db052fe653134216f0eed62e` |
| `apps/web/components/workbench.tsx` | `f2954ce1496a01449f85cf3c1c3bb8b060c0c33a499523e3785f4bdcf9a43265` |
| `apps/web/app/globals.css` | `f38c27b9cd63a50b8d6f93e69531b8919e3d6c931754b081c1b4a72580e785d5` |
| `apps/web/tests/query-summary.test.ts` | `64d9af5a97106303657c38a8aee9c356967d5c5f6dac30a67298aa189ff235f3` |

## 实际验证

- `node --test --experimental-strip-types apps/web/tests/query-summary.test.ts`：22/22 通过，覆盖状态与混合分支、304/历史快照/零匹配、错误残留 DTO、输入不变等。helper 和测试在可读性修正前后原字节相同。[静态运行证据](../../../.artifacts/r129-query-summary-20261023/static-checks.json)及[执行结果](../../../.artifacts/r129-query-summary-20261023/static-checks-execution.json)保留。
- 初稿 Web、desktop、mobile 的 `tsc --noEmit --incremental false` 均 exit0；新增 class 后再次运行 Web noEmit，exit0。原生两端是此前绑定源码的类型证据，没有把它们宣称为 class 修改后的重跑。[补充检查](../../../.artifacts/r129-query-summary-20261023/readable-static-checks.json)还记录最终 QA 的 `node --check` exit0。初版薄宿主已实际 AST parse，未为语法检查导入执行。
- [最终 b129 构建](../../../.artifacts/r118-material-workbench-20261021/web-build-b1292c3d4e5f6071/verification.json)passed：icons、Next、PWA 三阶段 supervisor 全 0；源码/依赖稳定，生成原件恢复。使用未改的 `build-web-v3-r120.mjs`，没有启动默认 API。Next 保留关于私有 home 下 tracing root 的 warning，未将它记作无 stderr 构建。
- [最终 b129 浏览器](../../../.artifacts/r129browser-b1293d4e5f607182/result.json)同批 **12 个场景标签、104 条检查记录**通过；104 不是独立测试数。9299 输入稳定，6 个 UI-only 观察窗口零业务请求，20 个精确请求门全部完成并移除。

页面实际走 UI/SDK：来源请求期间 busy；两来源 HTTP503、两来源 source_unavailable、consent_required → 两次拒绝、授权提交503且旧 DTO 残留、live 零行、部分成功与另一个来源仍进行/已失败、目录核对失败不发来源查询，以及解除注入后的重新查询恢复。卡片原因保留；改草稿和拒绝后的观察窗口无隐式查询或快照请求。等待观察窗口有界，不据此证明无限未来都无请求。

20 个门包含 16 次来源查询、3 次 consent 提交和 1 次目录 GET。来源查询中 **5 次为真实私槽 HTTP、11 次为 browser route 合成**；首尾恢复分别得到两来源 26/3 行，部分成功另有一次真实 A 来源查询。两次 deny201 与一次 consent503 都是明确合成响应：合成 QueryRun 没有对应后端记录，不能把它们称为真实后端授权验收。四次精确503（查询2、consent1、目录1）均单列并解除；其他未预期 HTTP、requestfailed、page、console、gate、coverage、cleanup 异常为空。

## 实际视觉与资源退出

Root 已逐张查看最终七图，见[视觉回执](../../../.artifacts/r129-query-summary-20261023/root-visual-review.json)。宽屏、390px、320px 默认浅色实测均为 **12px / 19.2px**；前景 `rgb(37,41,37)`、实际纯色背景 `rgb(246,245,241)`，对比度 **13.5318:1**。320px 的部分失败摘要正常换成两行，未横向截断，位于底部导航上方。这是指定显示状态的局部证据，不是全主题、读屏或完整 WCAG 验收。

[最终宿主](../../../.artifacts/r129uihost-b1293d4e5f607182/receipt.json)自然退出0/0/0，forced 空，Root exec 自然 exit0；Chromium PID60964 自然0/null/server close。[Web 服务](../../../.artifacts/r118-material-workbench-20261021/web-service-b1293d4e5f607182/service.json)Node143、Job2/2、active空；[fixture](../../../.artifacts/r129fixture-b1293d4e5f607182/stopped.json)shutdown_complete、sources_stable，外网/子进程/正常库尝试0。

[Root 资源观测](../../../.artifacts/r129-query-summary-20261023/root-resource-observations.json)对最终35个精确PID实际查询，均缺席且无查询错误；18986/18987 各5秒上限探针返回10061。汇总关闭不证明逐DBAPI句柄close或私库删除，Job/代码guard不是OS sandbox。

[Root 收尾检查](../../../.artifacts/r129-query-summary-20261023/root-closeout.json)实际 exit0/passed，绑定上述回执、当前三个产品与测试指纹、未变单测输入、可读性检查和七图。完整9299输入稳定性由最终QA记录，Root没有再把它全量重扫一遍。关键指纹如下：

| 回执 | 字节 | SHA-256 |
| --- | ---: | --- |
| 最终构建 verification | 131652 | `622f294a6b736b9ad5fae9f0851acb85372b4f9a0b395785b5e4069450bcc24b` |
| 最终浏览器 result | 2329195 | `77bbb7d94a93a21f1d1503a4fcdb16d129873cfde1a43fe25730f641b2d99d47` |
| 最终宿主 receipt | 7849 | `0bbbad3ddac6a517911c47aed82953fd89ff60c1d011af97f77ab941572887c3` |
| Root closeout | 4300 | `bc671cd10ec8eb6660a8cab8716e00e51554fbb79f7f88ca368802f57a340a98` |

## 首批保留与独立复核

首 a129 构建及 UI 的原自动回执均保持 passed，UI95条检查也原样保留；Root 实际看完其七图后发现 7/8px 继承字号过小，390/320 的状态行仅8px高，因此没有用这批自动通过宣布视觉验收。见[首批视觉问题](../../../.artifacts/r129-query-summary-20261023/first-ui-visual-review.json)及[首批资源观测](../../../.artifacts/r129-query-summary-20261023/first-ui-resource-observations.json)：34个PID缺席、端口拒绝。可读性补充后才有最终 b129 新构建、新UI；不覆盖原结果，也不拼成一批通过。

独立 ultra 已完成[初版产品审查](../../../.artifacts/r129-query-summary-20261023/product-review.json)、[初版QA审查](../../../.artifacts/r129-query-summary-20261023/qa-review.json)、[可读性增量审查](../../../.artifacts/r129-query-summary-20261023/readable-review.json)、[最终构建冻结审查](../../../.artifacts/r129-query-summary-20261023/build-freeze-b-review.json)。静审不替代 Root 运行与看图；最终文档另存独审回执。

最终 QA 为 `scripts/query_summary_ui_qa.mjs`，50547 B / SHA `a52bd5ac63b6a397eb3229c6d57da28703ece56489289296c3081ca025cba7cd`；薄宿主为本轮 `run-ui-host.py`，3563 B / SHA `5242dad9b4a44c2587f6f677ee1c7423bd650f32875c580b2e4d385fe01a50bf`，锁定原R127宿主四锚内存适配，没有复制守护或数据库实现。原 QA、首稿 Workbench、原 CSS 均另存本轮归档。

## 未完成项与下一步

全部材料和身份为项目自有合成私槽；真实外部来源、Provider、模型、embedding调用0。SW blocked，匹配public由页面route交付，不能宣称当前构建PWA离线、安装态、真实宿主/设备或真实Provider通过。正常/保留SQLite未打开，未commit/push/reset/stash/clean，其他dirty保留。无EPREL Key继续独立工作，不再询问。

下一候选是原规格桌面交互清单中的“hover预览”。只读窄审已确认当前VariantCard没有该交互，现有菜单hover和toast暂停不能替代它。原文未要求所有表格行都加详情；实施前明确本地已加载摘要、键盘等价与触控原入口，不能把hover接到会请求证据的showEvidence，也不能把原快照facts冒充当前权威值。该项尚未实施、验证。

专业SKU/真人Golden、真实Responses/Provider、正常库升级、PG、原生宿主/设备、完整WCAG等继续留账，完整V1未完成。HANDOFF原175246 B / SHA `c592d08cb1a8688dc797e3bc1c5a650354930f24e0bac60517428896e0c8fa12`已备份为本轮 `before/docs__HANDOFF.md`，仅前置本轮摘要、完整保留旧尾。
