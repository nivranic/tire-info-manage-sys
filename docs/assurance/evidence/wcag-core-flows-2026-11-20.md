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

## 待验范围（如实声明）

- 读屏讲解（Narrator/VoiceOver/TalkBack）、200%文本缩放、Reduced Motion、高对比模式、全部交互状态与完整流程人工核对：**本轮未做**，发布Gate该项仍为部分完成（自动半已建立）。
- axe为自动规则子集，不等于WCAG 2.2 AA全部成功准则的人工判定。

回执位于`.artifacts/wcag-audit-20261120/`：run-40e0d1d1为通过批完整报告（含键盘focus轨迹与对话框trace），run-9aed12fc为首轮发现批，dialog-focus-diag.mjs为对话框焦点诊断脚本，wcag-audit.mjs为可复跑编排器（axe-core以`npm install --no-save`安装，未写入package.json）。[本轮交接](../../AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md)
