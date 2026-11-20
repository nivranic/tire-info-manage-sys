# WCAG 2.2 AA核心流程自动审计验收

2026-11-20，基线c04595f。本阶段建立Web生产构建核心流程的WCAG 2.2 AA自动化证据（axe-core 4.14.1标签集wcag2a/2aa/22a/22aa+best-practice）与纯键盘遍历证据，修复审计发现的真实标题层级违规及同类问题；读屏讲解、全部交互状态等人工项继续待验。[移动端跨设备验收](mobile-cross-device-2026-11-16.md)

## 首轮发现（run-9aed12fc）

| 发现 | 位置 | 定性 |
| --- | --- | --- |
| heading-order（moderate） | 车库空态`.vehicle-empty > h3`：页面h1后直接h3，跳过h2 | 真实违规 |
| 同类排查：车型适配视图空态同样h1→h3 | vehicle-fitments.tsx空态 | 潜伏违规（同类） |
| 同类排查：车型适配consent卡h4（h2后无h3直接h4） | vehicle-fitments.tsx | 潜伏违规（同类） |
| 同类排查：召回consent卡用h3但CSS只写了`.consent-card h4` | recalls.tsx vs globals.css | 既有样式不一致（h3从未吃到consent样式） |
| 对话框Tab出框（账号对话框） | 初判检查 | 复核后为**检查过严**：原生顶层模态回绕时activeElement瞬时为body，背景从未收到焦点（inert成立），见诊断trace |

## 修复（根因=区块缺真实标题层级）

1. 车库面板标题「我的车辆／归档车辆」span→`h2`（与查询视图「查询记录」h2约定一致），空态/车辆卡h3变为合法。
2. 车型适配面板标题「核验官方车型配置」span→`h2`；consent卡`h4`→`h3`（workbench查询consent的h4前序为h3，合法，不动）。
3. globals.css：`.panel-title > h2:first-child`补齐flex布局与`margin:0; font-size:inherit; font-weight:inherit`重置（视觉不变）；`.consent-card h3, .consent-card h4`统一选择器（同时修复recalls的h3从未被样式覆盖的既有不一致），三处选择器同步。

## 复审（run-40e0d1d1，全部通过）

| 范围 | 结果 |
| --- | --- |
| axe六视图：查询主页、账号对话框、注册表单展开、车型适配、我的车库、离线资料库对话框 | 0违规 |
| Tab可达性：主导航、个人研究空间、命令面板 | 全部可达，90次Tab无过早循环 |
| 对话框焦点容纳（修正后判据=焦点永不落到对话框外的可交互控件） | 通过（回绕经body/dialog元素为UA行为） |
| Escape关闭账号对话框（真实按键） | 通过 |

## 联动验证

改动组件（garage/vehicle-fitments）被Web、桌面（Tauri）、移动（Capacitor）三端共同打包：web typecheck+69项测试、desktop typecheck+22项、mobile typecheck+24项全部通过；审计对生产重建包执行。

## 第二轮：仿真媒体与布局约束（2026-11-21，run2-3167b1f1，15项全过）

对上一节"待验范围"中可程序化的四类条件建立证据（CDP仿真，生产构建）：

| 条件 | 检查 | 结果 |
| --- | --- | --- |
| Reduced Motion（2.3.3方向） | 仿真`prefers-reduced-motion: reduce`后，全局降级块实际生效：spinner动画时长坍缩为0s、迭代次数=1 | 通过 |
| 强制色彩 | 仿真`forced-colors: active`后媒体命中、调色板切换为系统色（CanvasText解析值），该模式下axe六标签复扫0违规 | 通过 |
| 重排1.4.10 | 320 CSS px下查询/车型适配/车库/账号对话框四状态页面级横向溢出均为0px；导航按设计切换至固定底栏「移动导航」，7个按钮全部可见可操作 | 通过 |
| 文本缩放1.4.4（200%等效） | 720px布局宽×2倍DPR（等效200%浏览器缩放）下查询/车库无横向溢出、导航控件7个可见、axe复扫0违规 | 通过 |

判据修正记录：首轮判据误将≤767px下按设计隐藏的侧栏主导航当作唯一导航（该宽度导航切换为底栏），已改为按可见导航（主导航或移动导航）计数；移动导航7按钮计数曾误入溢出映射导致假失败，已分离。

## 待验范围（更新于2026-11-21）

- 读屏讲解（Narrator/VoiceOver/TalkBack）与全部交互状态、完整流程的人工核对：**仍待人工**，发布Gate该项剩余此部分。
- axe为自动规则子集，不等于WCAG 2.2 AA全部成功准则的人工判定。

回执位于`.artifacts/wcag-audit-20261120/`：run-40e0d1d1（第一轮通过批）、run2-3167b1f1（第二轮通过批）为完整报告，run-9aed12fc为首轮发现批，dialog-focus-diag.mjs为对话框焦点诊断脚本，wcag-audit.mjs/wcag-audit2.mjs为可复跑编排器（axe-core以`npm install --no-save`安装，未写入package.json）。[本轮交接](../../AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md)
