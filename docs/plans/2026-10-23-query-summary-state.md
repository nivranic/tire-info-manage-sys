# R129 查询总栏状态修复计划

2026-10-23。依据原规格在线优先状态机（失败后明确显示来源不可用，再询问回退授权）及当前 Workbench 实现，继续既有实施授权；不需要 EPREL Key。范围内新增代码前保存计划及现文件指纹。

## 已确认问题

`apps/web/components/workbench.tsx` 总栏只判断 `runs.some(hasQueryData)`，无结果时固定显示“等待可核验结果”。全部来源 `loading=false` 且 HTTP 异常、业务状态 `source_unavailable`、`consent_required` 或全部拒绝时仍如此。来源卡片已分别提供错误、原因和授权动作，因此只修正总栏派生反馈，不重写查询状态机。

HTTP200不代表可用结果；`live`、`live_verified_304`、`local_snapshot` 才属于可用 DTO。成功零匹配仍是已完成查询。来源目录核对失败及许可变化取消均须进入无结果终态，不保留等待文案。

## 实施合同

1. 提取纯摘要函数，输入仅为现有 run 字段与现行 resultsCount，输出显示文案和 busy/state；复用同一 hasQueryData 判定。不得新增持久化、effect、请求、计时或状态机。
2. 未查询保留原提示。实际存在 loading 时可显示“正在在线查询”；仅 consentPending 时显示“正在处理回退决定”（包括拒绝提交，不声称已读取快照）。所有请求结束后不得显示网络仍在等待。
3. 尚有未拒绝、无当前错误的 consent_required 时显示“在线查询未完成，等待回退授权”；全部拒绝显示明确拒绝/无结果。其余无可用 DTO 的终态显示“本次未获得可核验结果”，原因仍由来源卡片展示。授权提交失败不应被旧 consent_required 数据误当成仍在请求。
4. 有可用 DTO 时保留 MATCHED SKU 数及来源数，包括零匹配、304和历史快照；部分结果与仍在查询/处理决定/待授权/未获得结果应并列反馈，不误称所有来源已成功。沿用原 SKU 计数，不改去重或筛选。
5. 总栏使用明确 `role="status"` 与 `aria-atomic`，busy 仅标真正进行中的动作；不得抢焦点或改变表单/比较/授权。窄屏下状态文案可读，必要样式变更须先给出实际布局证据后补范围。

## 文件职责

- `apps/web/components/query-summary.ts`（新增）：共享可用数据判定和纯摘要。
- `apps/web/components/workbench.tsx`：仅导入 helper、移走旧判定并替换总栏呈现，保留查询/回退/卡片逻辑。
- `apps/web/tests/query-summary.*`（新增，沿用现有Node/TS测试约定）：有业务意义的状态/混合状态/空结果/错误重试/只读输入回归。
- `scripts/query_summary_ui_qa.mjs`（新增）：当前生产 Workbench 中的定向场景，复用既有私槽/浏览器与请求门，明确合成响应与真实私槽响应。
- 本轮 `.artifacts/r129-query-summary-20261023/`：受审薄宿主、前态及检查结果。复用现有 build-web-v3-r120，不改历史构建/QA/结果，不复制进程守护或数据库封装。

后端、SDK、DTO、数据库、授权策略、toast、CSS和原生宿主暂不在产品变更范围。保留现有 dirty，不 commit/push/reset/stash/clean。

## 验证与完成门

- 纯逻辑表驱动：初始、在线等待、回退决定处理中、全网络失败、source_unavailable、待授权、全拒绝、许可/目录阻断、授权失败残留DTO、live/304成功零匹配、local_snapshot、部分成功与各种待办/失败组合；输入不变。
- 三端 noEmit 类型检查；独立 ultra 审查代码和定向 QA。保持源码变更与 QA 验证证据分别记录。
- 新生产 Web 构建并恢复生成原件。沿用受审新私槽宿主，不启动默认 API、不打开正常/保留 SQLite。
- 生产页面通过真实 UI 提交，至少覆盖等待→全 HTTP 异常、业务不可用、待授权→拒绝、决定处理中、零匹配、部分成功及新查询恢复。浏览器合成 DTO/故障明确单列；至少一个恢复查询由私槽真实 HTTP 返回 live。
- 检查状态文案/busy、卡片原因、无隐式重试/快照读取，重新提交才有新查询；确认只改草稿不重新查询。宽/窄屏截图由 Root 实际查看。请求错误、合成故障、清理、源/构建绑定分开记录。
- 所有运行资源退出，保存原批失败，不覆盖、不拼绿。形成正式报告并前置 HANDOFF、保留原尾字节；完整 V1 仍 active。真实来源、Provider、设备、读屏和完整 WCAG 不由本轮证明。
