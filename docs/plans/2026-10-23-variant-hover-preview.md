# R130 规格摘要预览：设计与实施计划

2026-10-23。按原规格桌面交互清单的 hover 预览、移动端不依赖 hover、键盘可访问要求继续现有实施授权。当前 R129 已收尾；本稿冻结后实施，不新增确认、commit/push 或工作树流程。

## 依据与方案

当前查询/关注共用 VariantCard；原“查看证据”是 `.variant-actions` 内始终存在的原生按钮。点击会同步记录回焦对象并请求证据，不能直接用作 hover 回调。原规格没有要求所有表格行都增加预览。当前菜单 hover 与 toast 暂停不构成规格预览。

| 方案 | 取舍 |
| --- | --- |
| 现证据按钮上的本地摘要预览（采用） | 不增业务入口或请求，键盘沿原按钮访问，完整信息已有原卡与证据路径。 |
| 整张卡片 hover 打开 | 容易在勾选、拖选文字、比较/关注时干扰；本轮不采用。 |
| hover 预取证据原文 | 增加隐式请求与权限/取消链，不符合本轮本地摘要用途。 |

## 数据与文字合同

标题“已加载规格摘要”；说明“摘要节选，完整信息见卡片”。原规格字段与“本次加载的身份状态”分开标明。仅用当前卡片 props，不建立按 SKU 缓存的内容副本。

- 原记录品牌/型号、尺寸/载重/速度、地区、产品代码。缺失复用现 `displayValue` 语义；保留0，不用 `value || fallback`。不接受任意对象为字段，不输出 JSON/HTML。
- 复用 `identityContractText` 呈现本次已加载的合同状态；绝不以 current_identity 的产品代码替换原代码，不解释为 LIVE 或在线参数。合同缺失保持已有明确文案。
- 短风险提示完整保留：已撤销；身份修订/待核对且未替换原规格；未 resolved 的来源冲突；参数异常；field_resolution 冲突状态；关注 tracking_state 或合同 tracking_state 需要身份复核。关注外层风险明确传入，不自行合并合同。
- 不遍历 facts/effective_facts/curation，不用 field_resolution 的默认值补原字段，不展示候选、长理由、来源URL、hash、在线时间或猜测的来源状态。可以复用既有经过结构校验的冲突/异常判定。
- 这是有界节选：普通字段按 Unicode 码点最多32，超出明确加“…”；标题说明始终可见，不用 title 承担完整值。身份文案最多64，先保留状态前缀；关键风险使用固定短句且不截断。布局允许显示字段节选的省略号，完整值保留原卡。
- 浮层正文不要求内部滚动，不放按钮、链接或额外tabstop。默认字号至少13px，辅助说明至少12px；原卡是完整信息与键盘阅读入口。支持矩阵内摘要整体必须位于视口内且可见，不能把必需滚读的长文塞进无焦点tooltip。若实际长值/多风险不能满足，需要修订节选布局后验收，不能仅把overflow隐藏作为通过。

## 交互合同

1. 保留原证据按钮节点、名称、图标、点击时同步 `onEvidence()` 和回焦路径；只增加ref/data属性与预览事件。禁止包成会在开关预览时换key/卸载按钮的结构。
2. Workbench 只保留一个 previewOwner。query用现 `query:${rowKey}`，watch用 `watch:${recordId}`，不能以variant.id/snapshot_id替代。旧timer/cleanup只能compare-and-close自己的owner，不清新卡片。
3. 鼠标正常悬停300ms打开，拖拽/按住按钮与touch pointer不打开；键盘focus-visible立即打开。触控点击继续打开证据，不因pointer触发的focus留下预览。预览不抢焦、不滚动、不切换证据、不发业务请求。
4. trigger hover、trigger keyboard focus、popup hover 任一保持时不按时间自动消失。最后一项离开后150ms关闭，允许跨小间隙移到浮层；重新进入取消待关闭。换owner优先于旧焦点/hover。
5. Escape、证据点击、外部pointer/focus、页面外滚动、resize/visual viewport变化、blur、hidden、菜单/对话框、卸载或snapshot变化关闭并清理pending timer/observer/listener/frame。显式关闭优先于旧hover/focus；同次停留不得立即重开，尤其证据关闭后的程序化回焦。重新离开再进入或明确新的键盘焦点交互才能重开。
6. 菜单/对话框存在时阻断待打开timer；tooltip的Escape不抢菜单或dialog处理。Ctrl/Cmd+K照常打开命令面板。保留证据按钮的原生右键；portal正文contextmenu只stopPropagation防止React冒泡到卡片菜单，不preventDefault吞原生复制菜单。
7. 唯一已挂载tooltip使用稳定id和 `role="tooltip"`；仅open时合并到trigger的aria-describedby，关闭同次移除节点和关联，保留其他描述token。不添加aria-haspopup/expanded或dialog语义，不新增键盘陷阱。
8. 使用body portal、现有主题token与本次palette，避免剪裁；无入场动画。定位参考现菜单，但不复制抢焦行为。限制在可见视口8px边界，避让trigger，测实际popup/trigger尺寸；显示项和字体变化重测，不建立全局浮层基础设施。

## 修改范围与职责

- 新 `apps/web/components/variant-preview.tsx`：专用hook与只读portal，管理本轮状态/定位/清理；接受已格式化摘要，避免引入第二套事实解释。
- `apps/web/components/workbench.tsx`：单owner、共用VariantCard、原证据按钮接入、用既有formatter/helper构建有界摘要及关注风险布尔；不改业务请求、菜单七动作、查询/选择/比较、证据取消合同。
- `apps/web/app/globals.css`：仅专用preview布局、文字、主题/forced-colors样式；不改旧popover/menu/toast/查询摘要样式。
- 新 `scripts/variant_preview_ui_qa.mjs` 与本轮artifact薄宿主：复用受审生产Web/私槽/浏览器生命周期和输入指纹；不复制进程守护/数据库封装。

后端、DTO、SDK、数据库、依赖、持久化、原生宿主不在范围。保留其他dirty与历史回执，不打开正常/保留SQLite、不启动默认API。

## 验证与完成门

- 产品和QA独立ultra审查；三端noEmit；新生产Web构建、生成原件恢复。Root统一执行，使用新私槽批和headless Chromium。
- 实际UI覆盖鼠标延迟、focus-visible、hover+focus交叠、移入popup/离开、Escape同次不重开、A待开切B/同SKU跨source、watch记录owner、snapshot变更或导航卸载、菜单与命令dialog互斥、popup右键不触发卡片菜单、touch不hover且原点击可用。
- 点击证据仍真实私槽HTTP，关闭回焦原按钮且不自动重开tooltip；待开/打开期间请求数严格不增加。保全当前查询输入节点/值/焦点和比较状态；摘要不调用业务API。
- 1365×900、390×844、320×844、320×420检查真实边界/无横溢出/触发者不被遮挡，长值节选与多风险明确合成且标示；默认字号与宽屏局部200%文字放大可见。浅/深/高对比/forced-colors图由Root实际看。不能把局部字号调整称浏览器真实zoom。
- 最终错误/请求/合成场景分开记录，关闭timer与监听的代码路径独审；浏览器导航/卸载后的有界行为和最终进程退出实际观察，不声称测试计数已证明逐个React内部资源释放。
- 真实来源、设备/IME、读屏、完整WCAG与完整V1仍独立留账。失败保留、新批验证；报告和HANDOFF前置摘要保留旧尾，不因单项通过宣称完整V1完成。
