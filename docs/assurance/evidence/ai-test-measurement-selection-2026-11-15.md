# AI测试成绩选择验收

2026-11-15，基线6e0aa65。真实22成绩整场准备超过44,000字节，上阶段保留61,421字节的原始失败。本阶段增加显式选择。[计划](../../plans/2026-11-15-ai-test-measurement-selection.md)

## 合同

历史test_event引用增加可选measurement_numbers，原场次1起算、严格整数1至1000、非空且无重复，排序后准备。缺省及null省略新字段，保持原完整场次序列化和指纹。越界及错误领域选择在保存证据包前拒绝。

所选成绩保留原7项场次条件、完整参测胎和指标条件，以及本场成绩N／manual_test_*.field_(N+7)。附加所选成绩范围事实，包含原序号及原成绩总数。PDF绑定、原件用途、修订检查和撤销继续经过现有正常入口。

通用Web AI对话框读取精确场次修订，提供原成绩复选框、整场恢复及清空，空选择禁用准备。改变选择清空旧包和发送授权，提交期间冻结。现有SDK通过共享类型发送显式序号，引用去重包含排序后的选择。知识检索和测试详情入口复用该对话框。

## 真实材料验收

从前阶段隔离SQLite只读备份到新隔离库，并复制其原件对象。使用正常注册、证据准备、报告保存／回查和导出入口，真实Provider调用、精确SKU正例及真人Golden均为0。

验收由agent明确选择1至10和11至22两组，全部22条各出现一次。两个包分别30,120及35,558字节。原始数值、混合尺寸、原成绩序号、PDF引用和50 km/h例外均核对通过。两份报告各自保存范围事实，Markdown／HTML／PDF导出及下载摘要通过。共7项检查通过。原整场请求继续返回422，记录保持manual_transcription／unverified。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| API首批5模块 | 233通过、6失败，239项全部执行，867输入稳定，资源关闭 |
| 对应11参数用例独立诊断 | 11通过、0失败，867输入稳定，61个子进程exit 0并回收 |
| 最终5模块受管回归 | 239通过，0失败、跳过或不完整，867输入稳定，143子进程全部exit 0并回收 |
| 全前端工作区类型检查及Web生产构建 | 通过 |
| Web测试 | 69通过 |
| 桌面／移动JS | 22／24通过 |
| Web离线合同 | 14通过 |
| 独立非拥有者PG18.3／TLS正常HTTP | 6项通过，显式选择、旧完整指纹、报告、重启及变更拒绝 |
| 生产浏览器复跑 | 11项通过，完整422、空选择、最后两条选择、PDF恢复、正常报告保存、修改选择及整场恢复 |
| 资源与临时秘密 | 8条服务记录、10个记录进程、7端口关闭，最终及诊断子进程清理，临时会话文件、PG口令及TLS私钥已清理 |

数据库迁移036，PG运行合同postgres-runtime-schema@4，本阶段隔离合同摘要b12577f4c91d2799077852f0b939ad02a3ba7e98f5464722d72064771e922f08，180关系。实际部署须根据自身catalog与当前API源码生成批准合同。

## 首次失败及边界

- API首批失败集中在既有PDF流式授权撤销、调度后变化及冻结损坏用例。受管独立诊断的对应11参数用例及最终完整5模块239项均通过，产品源码保持相同，首次失败根因尚未确认。
- 浏览器首批完成3项后，最后两条成绩准备返回409。直接API和同一长临时目录复现均200，第二次生产浏览器11项通过。两次浏览器之间仅为私有验收脚本增加错误记录，产品源码保持相同。首次409根因尚未确认。
- 首次失败和复跑分别保留回执。该阶段新增选择与许可报告属于本地证据工程，真实Responses、Embeddings、精确SKU、真人Golden、EPREL、Native及完整V1 Gate继续待验。
- 历史54项专业Golden依赖缺失R74原件，尚需恢复。Android instrumentation及设备、WCAG、自然长期监控、部署恢复与SLO仍按历史边界继续。

## 回执

以下位于Git忽略的.artifacts目录，完整原件、隔离库及截图由接手环境自行复现。

| 回执 | SHA-256 |
| --- | --- |
| ai-measurement-selection-20261115-real/result.json | 95bbf36d45fde8984e254b0aac200dea17ad60857b19ee4108175c22ea314046 |
| ai-measurement-selection-20261115-regression/result.json，首次失败 | 0ab7bd06a3e6566fc2e9f789a6b96a0aec4902d5c52cef6165f2919d23609398 |
| ai-measurement-selection-20261115-diagnostic/result.json | 891e45467a640a385599b113d1437dbd6ee88393d66cb7440541ce272830beb4 |
| ai-measurement-selection-20261115-final/result.json | 303bbc95a8c7e424c0f4b8407e6ca6808bc6c3c3456e9f110d13ab0e79925fc7 |
| ai-measurement-selection-20261115-pg/resource-audit.json | dce2be3dc1f1fc7ffdc305f9922436b9f02bd84a4955ba2f18ef0608b22bab5f |
| PG report.json | fbec7f32e8331554303f872c937b6091d85fdc8482036fc6320110ca8e9ac8d7 |
| Web首次report.json | 1ca8b77d115ed0545afa64535236d663d8f433dad256e87c5eb14bc3e0bbd24e |
| Web最终report.json | bdbcacd3dcafbf014e8393febd5180d477a2d485df56d6e95d03d44709bbb0f4 |
