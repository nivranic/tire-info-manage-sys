# Android instrumentation构建与设备执行验收

2026-11-15，基线b6b1923。本阶段完成移动端instrumentation测试的完整构建与Android设备执行，此前该项一直因Gradle发行包下载失败与重复类冲突未能构建。[根因确认](first-batch-pdf-failures-and-browser-409-2026-11-15.md)

## 构建链路

Gradle 8.14.3-all发行包在本机网络下多次于约10%处中断（前阶段`personal-records-android-compile.log`即卡死于此，为该项长期待验的直接原因）。本次以8段并行Range请求从镜像取得完整224,584,249字节，SHA-256 `ed1a8d686605fd7c23bdf62c7fc7add1c5b23b2bbc3721e661934ef4a4911d7c`与services.gradle.org官方校验值一致后，种子化到项目`GRADLE_USER_HOME`的wrapper dists目录。

随后`assembleDebug assembleAndroidTest`在生成的`capacitor-cordova-android-plugins`模块androidTest重复类检查失败：`kotlin-stdlib 1.8.22`与旧的`kotlin-stdlib-jdk7/jdk8 1.6.21`传递依赖并存。修复为在[根build.gradle](../../../apps/mobile/android/build.gradle)的subprojects中对全部Kotlin stdlib坐标强制1.8.22（该版本起jdk7/jdk8为空重定位壳）。根build.gradle属于`OFFLINE_HOST_BUILD`摘要输入，该值仅运行时自引用比对，无测试钉死字面量。

前端按合同先`npm run mobile:frontend`再`cap sync android`，gradle的preBuild陈旧资产硬校验通过。

## 设备执行

| 执行 | 设备 | 变体 | 结果 |
| --- | --- | --- | --- |
| 首次connected（debug变体） | vivo V2606A真机，Android 17（API 37） | debug | 安装被厂商USB安装确认弹窗阻塞，收集0项 |
| debug变体探针 | pvoice AVD模拟器，Android 14（API 34） | debug | 175项执行，85通过、90失败，失败均为“Dedicated QA application required”守卫断言 |
| 正式执行 | pvoice AVD模拟器，Android 14（API 34） | offlineQa | **175项通过、0失败、0错误、0跳过**，158.5秒 |

offlineQa专用QA应用变体是全部instrumentation测试的既定要求（测试断言目标包名以`.offlineqa`结尾，不触碰正式应用别名）。19个测试类覆盖OfflinePackStore（23）、OfflineSyncPolicy（17）、OfflineFallbackPolicyStore（16）、NativeQueryDenials（15）、OfflineFallbackV2Store（13）、NativeSecurity（8）等离线包、回退策略、同步合同、原生HTTP桥与安全拒绝路径。测试网络仅绑定127.0.0.1 MockWebServer，无外部调用。

## 真机余项

vivo V2606A（Android 17）两次`adb install`均停在厂商USB安装确认弹窗，属用户物理操作项：需机主在手机上批准安装（或开启开发者选项中的USB自动安装授权）后，以`ANDROID_SERIAL`指向该真机重跑`connectedOfflineQaAndroidTest`。模拟器执行链路与APK均已就绪，回执中的offlineQa APK可直接复用。未修改手机任何安全设置。

## 实际验证

| 验证 | 结果 |
| --- | --- |
| Gradle发行包 | 224,584,249字节，SHA-256与官方一致 |
| assembleDebug/assembleDebugAndroidTest（修复后） | BUILD SUCCESSFUL |
| connectedOfflineQaAndroidTest（模拟器） | 175通过、0失败、0跳过 |
| debug变体守卫探针（模拟器） | 175执行，90项QA守卫失败，证明offlineQa为必要变体 |
| 真机 | 安装被用户确认门阻塞，instrumentation未执行（待用户批准） |

回执位于`.artifacts/android-instrumentation-20261115/`：receipt.json含全部产物SHA-256，results/含模拟器两份JUnit XML，connected-*.log为三次gradle执行完整输出。offlineQa应用APK摘要`273549745323e0b497007e985eaf07fa7290bd2488ca84077ceda627613dabb2`，测试APK摘要`51a57e242f6a0fec9490acd966777e8f88f48b094ee72b794b7d963847e9aca4`。

本阶段修改仅`apps/mobile/android/build.gradle`（Kotlin对齐）与文档；JS/Rust/API源码未动，未重跑API回归（无涉改动）。跨设备E2E、iOS、Windows/macOS/Linux矩阵及真机instrumentation继续待验。[本轮交接](../../AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md)
