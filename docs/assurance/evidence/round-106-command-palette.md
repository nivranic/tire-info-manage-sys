# R106：共享命令面板的有限浏览器验证

2026-10-21。本切片涉及 5 文件：产品 `apps/web/components/command-palette.tsx`、`apps/web/app/globals.css`；专用 QA `scripts/command_palette_browser_qa.mjs`、`command_palette_browser_qa.tsx`、`command_palette_browser_qa_loader.cjs`。原生 modal 与关闭、焦点环绕/恢复、命令优先焦点、动态活动项、组合输入守卫及小屏样式在本组件范围完成调整。

需求定位沿用既有 PRIORITY-REVIEW：A6 原 md 第876、930–944行，以及 A8 Gate7/第1304行；这里只完成上述有限切片。

Root 只实际运行一次候选 d：工具 `db2330` 实际 exit 0，runner exit 0。真实 React/Chromium 隔离组件 fixture 在 1440/390/320 各完成 18 项，共 54 个互异 width/name 检查；生成三宽明暗六截图、9 组几何记录。覆盖快捷键开关、焦点和键盘环绕、选项执行一次、空结果/动态命令、Pointer/Escape、合成组合输入事件、命令打开业务 dialog、移动 DOM-back helper、StrictMode/卸载取消 rAF、44px 目标和缩放回流。旧 a/b/c 保留为准备候选，未执行其浏览器 QA，不合并为四次实跑。

`typecheck.json` 仅覆盖 fixture 及其真实 CommandPalette/Icon/mobile-back imports，errors=[]；`compile.json` 为 fixture errors=[]、warnings=[]，不代表全应用类型检查或生产构建。报告 page/console errors 与 unexpected page requests 均为 0，context_closed=true、inputs_unchanged=true。Root 对 prepare 的 33 项关键输入实核匹配；**33 项不是完整运行时传递依赖闭包**，不称完整 freeze。

静态独审无阻断；后续终态工件独核为 `passed-within-recorded-scope`：当前 33 项关键输入匹配，按既有回执复算 54/18×3 检查和 9 组几何断言，六 PNG 文件签名/尺寸/hash 匹配。独审没有重跑 QA、重新测量 DOM 或做截图视觉验收。工具终态来自 Root 观察，安全回读不是 raw 工具日志。本报告未重跑 QA。

边界仍开放：隔离组件及合成命令不是完整 workbench 集成；composition 事件不是真实 OS IME，DOM-back 不是设备返回，CSS 200% zoom 不是浏览器缩放验收。未验真实读屏、完整 WCAG 2.2 AA、六平台或 Native；页面请求拦截不证明 OS 网络隔离，context close 不证明所有 OS child/PID 缺席。没有正常 API/Web 服务/DB/Provider 使用；不构成材料、真实设备或完整 V1 验收，provider/export=false，V1 active。

证据：

- [d 实际报告](E:/Mix/project/tire-info-manage-sys/.artifacts/command-palette-qa-20261021-d/report.json)：12581B，SHA `f33ed5f28d148501f133e40055e2f77d999d943610993e9fd8248437677ac55c`。
- [Root 终态回读](E:/Mix/project/tire-info-manage-sys/.artifacts/command-palette-root-audit-20261021/terminal-readback.json)：10424B，SHA `966238c73b5e99150530f877855d12f2fae59eb2cf373b4fe6588a3947c059ea`。
- [现有静态独审](E:/Mix/project/tire-info-manage-sys/.artifacts/command-palette-review-20261021/REVIEW.md)：2216B，SHA `8152620f864aef54fc2843817bfcf8b67ccc52e57df2540e9a857abb41bb0709`。
- [终态工件独核](E:/Mix/project/tire-info-manage-sys/.artifacts/command-palette-review-20261021/terminal-review.json)：5635B，SHA `1342c90fc5914f37442149785393765a7a720863300973a0e69955254a2a8a2e`。
