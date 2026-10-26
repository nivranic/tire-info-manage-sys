# 第75轮：同场精确候选的本地条件化解释

R75 已交付 B 工程链：把当前已审精确轴位候选、当前参测对象身份桥和本人已保存偏好连接到同一测试场次的原始观察。完整 V1、代表性真实精确 SKU／真人 Golden 和 C 专用 AI 推荐仍未完成。R74 的公开 TRWP 论文缺完整 SKU，本轮未把其商品名称造为正向身份；所有完整正例均为明确标识的项目合成材料。

合同：[冻结计划](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-same-event-candidate-interpretation.md)，SHA `a568e759bb71c221cdf9240a65952561fc70b3923075919e8abdcd1866a96ab3`。顶部“尚未验收”为冻结时状态，终态以本报告为准。根证据目录：[R75](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-same-event-8e1d820cc22f43c8bbac303b8250fe06/)，最终清单为其中 `verification-final.json`，必须同时核其根外独立审计。

## 实际行为

- 新只读 `POST /v1/test-events/{event_id}/candidate-interpretation?mode=history`，八键请求、五键候选引用，2–60 项；原值、排名、权重、participant ID 及资格均不由调用者替代。
- 复用 R69 精确轴位候选、R71 全证据重建和 R65 Decimal 解释；先核最新事件／桥的完整修订元组。组合 SHA 绑定当前账户、完整事件、偏好、R69 签名、完整桥、当前身份／生命周期／目录代次和显式映射。读尾 rollback＋expire_all 后重新读取所有依据。
- 任一所选项不准入，整次 `personal_interpretation=null`，保留明确排除和来源参测对象观察；不静默缩为子集。全 null 映射仍可核证据，但无个人数值比较。原始小数、负零、并列、来源名次和缺失保持；不生成综合分、跨场排名、官方 OE 或安装安全结论。
- 首页候选区显式选场、分页读桥、逐 SKU 选桥、逐指标映射和计算。展示适配关系、桥材料页码／定位／许可／hash、原始成绩、取舍与覆盖。账户 epoch、选择／桥／偏好变化、409 和迟到响应均清空旧结果。
- 全过程保留 `operator_supplied/unverified`、`participant_only` 和 `provider_use/export:false`；无新增表、AI／导出用途或正常库迁移。R70 的测试 AI 事实摘录门禁保持。

## 验证及证据边界

| 阶段 | 实际结果 | 范围 |
|---|---|---|
| 初始后端相关回归 | 229 passed，exit0 | 包含初始新目标；属于固定422补修前，不与后续相加为全量 |
| 最终错误处理器回归 | 81 passed，exit0，7输入稳定 | 26新目标＋R65 routes＋4 auth输入＋1管理先验门；[回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-backend-final-handler-14cd8b617a004548b7a2918af2adce32/verification.json) |
| 独立后端反例 | 17 passed，exit0，32输入稳定 | 独立字面 JSON/SHA、latest／ABA、原件同长损坏、只读SQL、账户／偏好和完整尾读；[审查](E:/Mix/project/tire-info-manage-sys/.artifacts/review-r75-design-456463f2d0834a63bd12a85dd480c2bc/REVIEW.md) |
| 独立新会话补验 | 1 passed，exit0，32输入稳定 | 新会话已认证账户无本人偏好时409，不能借用其他会话偏好；保存本人偏好后200；[回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-actor-6a588df7532c49ef9d279e9a5a68088b/fresh-a82b4d69bede4de29be29a7a76f9bd4e/result.json) |
| 前端／集成独立静态审查 | 无阻塞，12输入稳定 | [报告](E:/Mix/project/tire-info-manage-sys/.artifacts/review-r75-design-456463f2d0834a63bd12a85dd480c2bc/integration-59e68a41555947e890f5d537457bbd24/REVIEW.md)；没有重复执行测试，不冒称浏览器审查 |
| 公开 SDK | 编译正反例及注入传输通过 | 八／五键公开类型、精确请求／URL、no-store、错误码及取消；不是后端验收 |
| 最终前端验证 | workspace typecheck＋Web／Desktop／Mobile 前端构建均exit0，282源稳定 | [回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-frontend-final-8f17fb2d4dc14d0c90c1ecc80202748a/frontend-checks.json)；生成文件按原字节恢复；不是原生设备验收 |
| 真实私有HTTP | 34项通过 | [回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-same-event-8e1d820cc22f43c8bbac303b8250fe06/http-api-qa-final-tool.json)；生产路由／SQLite／对象仓库，两SKU合成闭包，固定错误、原始值、排除／恢复及业务／审计行计数 |
| 真实桌面React | 24项通过，实际1448×904 | [回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-same-event-8e1d820cc22f43c8bbac303b8250fe06/react-desktop-tool.json)；真实控件与实际HTTP，包含全null、正例、旧桥409、当前排除、账户epoch及延迟实际响应丢弃 |
| 390×844／320×740 | 各12项通过 | [390](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-same-event-8e1d820cc22f43c8bbac303b8250fe06/react-390-final-tool.json)／[320](E:/Mix/project/tire-info-manage-sys/.artifacts/r75-same-event-8e1d820cc22f43c8bbac303b8250fe06/react-320-tool.json)；窄屏共享选场／选择／计算与布局，无页面横溢；未重做完整桌面反例或原生触摸设备验收 |

独立容量6／7／60是请求 schema 边界，完整HTTP正例只有2 SKU。truncated 用真实 SQL 与证据投影、临时降低扫描预算到1触发，不是201关系压力测试。重复 derived participant 被 R71 唯一创建门先行409拒绝，未弱化 schema 构造不可达状态。

账户沿用既有 `session_scope`：同一 cookie 换绑账户，当前会话的数据会随之聚合。本轮验证当前账户改变组合签名、独立新会话不继承偏好，以及 UI 账户变化后不恢复旧结果；不宣称严格服务端账户／租户隔离。浏览器的迟到响应测试仅延迟实际 HTTP 的交付，未 mock 响应内容；session-unavailable 是显式合成事件，不是真实网络断连。

## 发现、修正与保全

1. 独立审查发现新路由的框架422缺固定code，已在 main 增加 `test_candidate_invalid_request`，保留脱敏 loc/msg/type，不回显 input；旧 R65 handler 不改。
2. 沙盒对象仓库硬链接拒绝，失败日志保留；使用相同 GUID 私库／禁公网／禁子进程护栏在宿主验证真实对象存储，没有 mock 存储或提高 Parser 预算。
3. 首轮三端构建命令全部通过，但源快照与前端末次校正重叠，整体回执标失败；稳定源码下重跑四阶段均通过，旧阶段未覆盖。
4. 浏览器 API 初轮错误假设同 cookie 换账户会清空偏好，实际为既有会话聚合。保留失败并改验当前actor签名变化，独立新会话用例另验。首次窄屏检查假设 emulation 不重建账户树而失败，改为重新走当前控件／HTTP，再取得390和320实际视口结果。
5. 初始 Next 在根目录启动失败；沙盒 Next Ready 后回环超时，改为 apps/web 下限定回环的宿主进程。截图保存的 MCP 路径限制和单条代码体积限制通过保存原图字节解决，未绕过工作区或修改截图内容。
6. 全部原有 dirty 保留，R74及更早证据保持原字节。API和Next自有进程已关闭，自有页面19关闭、空白页12保留；最终运行源码稳定、三项运行护栏0。无正常库、Provider／真实模型、公网采集、设备运行、提交或推送。

## 下一步

优先建立专业 `TestEvent→精确SKU` Golden 评估器及代表性合法真实材料，保留拒绝／未知／同名不同SKU反例，并补真人复核。不要重做 R72/R74 捕获或 B 工程，也不再等待用户提供 URL。C 专用 AI 推荐需另行冻结用途／许可、同意、证据合同和真实模型语义验收；当前 Responses API、更多来源、平台矩阵、生产IAM／部署及全部发布 Gate 继续排队。Goal 保持 active。
