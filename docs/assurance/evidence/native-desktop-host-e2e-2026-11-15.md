# Native桌面宿主真实E2E验收

2026-11-15，基线34179e7。本阶段完成Tauri桌面宿主的真实运行验收：debug版exe驱动真实WebView2前端，经应用内UI对正常隔离SQLite API完成账户切换与设备离线资料归属变化，覆盖前阶段遗留的"Native真实账户切换、离线owner变化"余项。[Rust基线](../../../apps/desktop/src-tauri)

## 链路

- 前端按debug构建合同走vite dev server（tauri.conf.json的build.devUrl=127.0.0.1:1420）；`cargo test`全量192项通过、0失败、4项默认忽略（lib 174+容量parity 8+E1 parity 10，较前阶段173多1项新增）。
- 真实uvicorn API（隔离SQLite、新slot）+ 真实`tire-desktop.exe`（`TI_DESKTOP_QA_HIDDEN=1`隐藏窗、`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`调试端口、随机`qa-*`会话命名空间隔离凭据与offline-v1目录）。
- 驱动采用项目既有生产浏览器验收的原始CDP方式，在真实WebView2内执行UI脚本；未启用任何代理，API仅127.0.0.1。

## 九项检查（run-e326fca1，全部通过）

| 检查 | 结果 |
| --- | --- |
| desktop_host_ready_with_secure_session | 宿主经系统凭据库会话连接本机API |
| register_qa_desk_a_管理员 | 应用内注册首个账户为管理员 |
| garage_vehicle_created_via_ui | 车库经UI创建车辆记录 |
| offline_plan_includes_garage_context | 设备离线计划含车库档案1份 |
| offline_pack_saved_to_device | 包经预览+明确授权保存到设备（0.01 MiB、归属版本1） |
| session_reset_returns_to_new_anonymous_session | 「重置本机安全会话」回到全新匿名会话 |
| register_qa_desk_b_研究员 | 第二账户注册为研究员 |
| previous_owner_slot_locked_and_marked | 旧归属槽位保持密文并标「旧归属 · 已锁定」，归属版本2 |
| previous_owner_unlock_keeps_old_owner_marker | 单独确认后可读旧归属文档，横幅保持旧归属标记不并入当前会话 |

## 调试中确认的环境事实

- 前几轮instrumentation同因的网络问题再现一次：宿主首连失败由**残留fixture进程占用8316端口**造成（旧库返回"用户名已被注册"），编排已加端口预检、绑定错误快检与进程树强杀；已定位并清理残留进程。根因记录于运行回执。
- React重渲染会使缓存的DOM节点失效、库与计划为同类名叠加dialog，驱动脚本已按动态重查与按目标按钮选dialog修正。

## 资源与清理

| 项 | 结果 |
| --- | --- |
| QA凭据清理 | 16个qa-*命名空间×2条目=32条全部删除（cmdkey核对） |
| offline-v1目录 | 本轮16个hash目录删除；历史轮次3个目录未动 |
| 进程与端口 | exe/api/vite全部终止，8316/8318/1420无监听残留 |

回执位于`.artifacts/native-host-20261115/`：receipt.json含输入指纹与产物摘要，run-e326fca1为通过批完整报告，cargo-test-baseline.log为全量Rust基线。本轮未修改任何仓库源码（QA脚本全在忽略目录）。

## 跨设备（桌面→Web）数据消费

同一workspace.sqlite上，生产Next.js（:3000）+ 无头Chrome以同账户qa_desk_a登录Web工作台（fixture API按Web构建代理默认走:8000），三项检查通过：Web同账户登录、车库显示桌面宿主创建的「QA轿跑」、品牌车型字段完整。同账户、同一数据、两个真实平台（Tauri宿主与Web生产构建）完成消费闭环，回执cross-device-2f1fac59。

真机instrumentation仍待用户在vivo手机批准USB安装；iOS/macOS/Linux矩阵、移动端跨设备、WCAG、长周期监控、生产部署恢复、SLO及真人Golden继续待验。[本轮交接](../../AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md)
