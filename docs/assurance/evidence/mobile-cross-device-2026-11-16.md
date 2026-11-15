# 移动端跨设备真实E2E验收

2026-11-16，基线5a48c02。本阶段补齐前阶段余项「移动端跨设备」：真实Android应用（offlineQa专用QA构建）与Web生产构建在同一真实账户下双向交换车库数据，全部经各自真实UI完成。[Android验收](android-instrumentation-2026-11-15.md)｜[Native宿主验收](native-desktop-host-e2e-2026-11-15.md)

## 链路

- 真实API：隔离SQLite全新slot的fixture API（本机127.0.0.1:8000，`MATERIAL_QA_TOKEN`控制关停），同一实例同时服务两个平台。
- 移动端：pvoice AVD（Android 14 API 34，emulator-5554）安装offlineQa应用与测试APK（与Android验收同一产物，app sha256 `273549745323e0b497007e985eaf07fa7290bd2488ca84077ceda627613dabb2`）。App经其设计内建的本机调试通道连接：`adb reverse tcp:8000 tcp:8000`（App设置页明文「当前调试包使用固定本机端口，经ADB reverse连接开发机API」），请求走真实原生transport（Android Keystore加密会话）。
- 驱动：offlineQa继承debug可调试性，WebView调试开启；宿主经`webview_devtools_remote_<pid>`套接字转发后用项目既有原始CDP方式在真实App WebView内执行UI脚本。移动端挂载与Web同源的共享Workbench组件，选择器与桌面E2E一致。
- Web端：生产Next.js（`next start` :3000，代理API走:8000）+ 无头Chrome CDP驱动真实页面。

## 九项检查（run-f556b870，三阶段全部通过）

| 阶段 | 检查 | 结果 |
| --- | --- | --- |
| 移动端创建 | mobile_native_transport_connected_via_adb_reverse | 真实App原生transport经reverse连接成功（连接栏「本机调试已连接」） |
| 移动端创建 | register_qa_mob_a_admin | App内注册首个账户qa_mob_a为管理员 |
| 移动端创建 | garage_vehicle_created_via_mobile_ui | 车库经App UI创建「QA移动轿车」（QA Mobile · QA Cross 型） |
| Web消费+创建 | web_login_same_mobile_account | Web生产构建以同一账户qa_mob_a登录 |
| Web消费+创建 | web_garage_shows_mobile_created_vehicle | Web车库显示移动端创建的车辆 |
| Web消费+创建 | web_garage_shows_mobile_vehicle_fields | 车辆品牌/车型字段完整 |
| Web消费+创建 | garage_vehicle_created_via_web_ui | Web侧创建「QA Web 版」（QA Web Motors · QA Web 型） |
| 移动端消费 | mobile_garage_shows_web_created_vehicle | App重开车库显示Web创建的车辆 |
| 移动端消费 | mobile_garage_keeps_mobile_created_vehicle | App自身创建的车辆仍在 |

双向闭环：移动端设备A创建→Web设备B消费，Web设备B创建→移动端设备A消费，同账户、同一数据库、两个真实平台各自走真实UI与真实网络栈。

## 资源与清理

| 项 | 结果 |
| --- | --- |
| 进程与端口 | fixture API优雅关停（exit 0）、Chrome正常关闭（exit 0）、next经进程树强杀；8000/3000无监听残留 |
| adb映射 | reverse与forward均已移除（`--list`为空） |
| 模拟器 | 两个QA包（app+androidTest）已卸载，AVD无残留 |

回执位于`.artifacts/mobile-cross-device-20261116/`：run-f556b870为完整报告（report.json含三阶段检查、进程生命周期与页面URL），移动端两遍驱动为mobile-ui.js/mobile-ui2.js、Web侧为web-ui.js、编排器mobile-cross-device.mjs。本轮未修改任何仓库源码（QA脚本全在忽略目录）。

vivo真机instrumentation仍待用户批准USB安装（等待器与全自动链已就绪）；iOS/macOS/Linux矩阵、WCAG、长周期监控、生产部署恢复、SLO及真人Golden继续待验。[本轮交接](../../AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md)
