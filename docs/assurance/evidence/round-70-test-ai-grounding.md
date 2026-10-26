# 第70轮：交接复核、测试 AI 边界补修与界面优化

结论：交接卡及 R69 子范围有证据支持，**完整 V1、性能推荐和 AI 推荐仍未完成**。本轮发现并补修未建立身份桥时的 AI 推荐绕过、空白文字校验绕过和 SSE 终态延迟，优化手机顶栏。未提交、推送或发布。

## 复核与实现

实施前现场复核 R69 清单通过：871 源码、256 展开 dirty、98 本轮证据、15 文档，R68 的244份证据保持，无 staged/unmerged。旧回执和封存 artifact 未改写。

[本轮计划与精确合同](../../plans/2026-10-18-test-ai-grounding.md)记录了取舍：仅禁止单条 claim 同引测试与 SKU，无法阻止单侧引用或 uncertainty 写入相同推荐。因此**整个含仓库 TestEvent 的包只允许服务器事实摘录**，包括纯测试包；普通无测试包和设备独立合同保持，召回混包同时满足两套门禁。

- 拒绝 inference、非空原始 text/uncertainty（含空白），含测试的单条 fact 只能来自一个 evidence、最多一个参测对象。不同对象、不同场次或规格可分别摘录，不拼成关联断言。原始数值/小数、来源名次、条件与人工未核验状态保留。
- Responses、chat、Anthropic、同步/流式、projector 与直接 store 共用纯函数合同；选择的 prompt/schema 纳入实际预算与 request_contract。固定 `test_boundary` 明确没有参测对象↔SKU桥、没有适配/性能推荐或跨场榜。
- 新测试报告固定正文 schema `research-report@4`，使用 renderer @5；其他新报告及旧历史报告保留原 schema 和 renderer @4。保存时重验分析；导出验证边界和作用域，MD/HTML/PDF都呈现固定边界。9份旧导出基线字节一致，旧缓存不重渲染；旧完成记录和旧报告不被补写等级。
- 三端共享界面显示服务器测试边界，入口改为“AI 摘录本场事实”；R65“按我的偏好解读本场”保留。旧结果明确标为未按本轮重新复核，原历史内容保留。
- 手机顶栏采用两行布局，保留完整 API 状态、全部按钮及44px触控目标；390与320宽度均无整页横向溢出。完整移动体验和 WCAG 仍未关闭。
- 真实浏览器发现 SSE 在终态后仍保持25秒窗口，开发代理下终态展示约25秒。追加在**终态且页耗尽**时结束连接，分页未尽继续发送；pending窗口、心跳、事件上限和reset保持。最终同合成模型路径展示耗时1169/1166/1180ms，分别对应1440/390/320视口；不是SLO、真实模型延迟或生产网络测量。

后续[精确测试身份桥设计卡](../../plans/2026-10-18-test-sku-evidence-bridge-design.md)区分人工关联、来源明确标识、人工复核和在线核验，列出双侧证据、修订代次失效及桥→条件化解释→AI推荐的顺序。它是设计建议，尚未实现或冻结新 wire 合同。

## 实际验证（各阶段分别计数）

证据根：`.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737`。

| 阶段 | 观察结果与入口 |
|---|---|
| 后端核心受影响回归 | 212/212通过，26具名源/测试/runner前后SHA稳定，私有engine105，外联/子进程/正常库尝试0。[后端报告](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/backend/REPORT.md)、[冻结回执](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/backend/source-freeze.json)。此阶段之后仅追加独立SSE结束判断，另列验证 |
| 独立 AI 反例 | 同次66/66通过，12具名SHA稳定，含双侧/单侧/uncertainty/raw空白、三Provider、sync/stream/store、普通SKU/R65/召回兼容。[独立报告](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/review/R70-REVIEW.md) |
| 报告相关回归 | 同次126/126通过（45新、21旧reports、39rendering、21召回），14具名SHA稳定；9份旧基线与三格式缓存复用保持。[报告交付](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/reports/REPORTS-DELIVERY.md) |
| 追加 SSE 机制验证 | 独立12/12通过，14具名SHA稳定；终态无sleep、terminal分页、pending假时钟25秒/心跳、cap/reset/disconnect及真实私有SSE续读无重复。[追加报告](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/review/stream-terminal-57c7cdece39947ba9d7c460e48694072/REVIEW.md) |
| 类型与生产前端 | workspace typecheck与Web/Desktop/Mobile前端生产构建分别exit0；25具名源一致、23制品、Web静态5/5及PWA18 allowlist、7生成文件恢复。[前端回执](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/frontend/verification.json) |
| 最终真实私有 HTTP | 29条断言通过：测试/混包、同步及流式拒绝、有效结果、版本边界、三格式导出与护栏。仅模型adapter为合成，HTTP使用生产端点。[最终API回执](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/runtime/api-after-sse.json) |
| 最终真实浏览器 | 1440×1000桌面16条、390×844与320×740各18条断言通过；事实摘录→真实stream结果→保存→冻结报告，原值/边界、无自由推断、无新模型调用与顶栏可用性。[桌面](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/runtime/ui-desktop-final.json)、[390](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/runtime/ui-mobile-390-final.json)、[320](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/runtime/ui-mobile-320-final.json) |

这些数字不累加为全量，断言数不是业务场景数。前端生产构建和手机视口不等于原生设备验收。SSE机制测试不冒充浏览器速度测量，浏览器耗时也不扩大为真实Provider质量验收。

## 失败历程与证据边界

旧源码3种推荐绕过红例、独立首轮空白绕过、所有早期运行均保留。独立runner曾误拦 Windows asyncio 内部 socketpair，只修夹具为精确内部loopback放行，外联仍禁。召回对象留存失败发生于grounding之前：后端诊断观察到WinError3及短路径后WinError5；宿主相同隔离规则通过，未修改产品os.link或Parser预算。报告夹具的295字符路径失败仅有前后对照，不将其清洗后的OSError描述为已证实长路径根因。

Root初轮typecheck编译exit0但同时编辑导致source drift，保留attempt-1后在稳定源码重验。API首次QA遗漏必需history参数、第二次没有解除Markdown正常转义而产生错误预期，均只修QA；最终前后各29断言分别保留，不累加。第一次UI的16秒等待小于既有25秒SSE窗口，原失败保留，并进一步修复实际终态结束机制；最终脚本上限40秒，实测约1.17秒。

## 资源、保全与未完成项

每个运行使用新GUID私有SQLite/对象/Parser bundle，导入应用前清理宿主配置；模型仅合成adapter，真实外联、Parser子进程与正常库护栏计数0。为避免Windows多级路径，部分测试私有存储位于工作区`.artifacts/r70-store-*`及`.artifacts/r70-web-*`，精确根在各回执和`started.json`内；不是正常库，移交清单也不是私有数据备份。Parser预算保持8秒/并发2/CPU5秒/384MiB。

两次私有API均HTTP200 shutdown且实测exit0，Next主动Ctrl+C实测exit1。宿主确认8970/3371无监听；关闭测试页15、原空白页12保留。运行3配置按SHA恢复，构建7生成文件另记账。[运行恢复](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/runtime/restoration.json)、[端口终态](../../../.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/runtime/host-ports-stopped.json)。截图在聊天原生返回并目视，未归档截图文件。

当前最终清单为`.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737/verification-final-v2.json`，按实际封存与独立审计判断。v1保留为三处旧入口/版本文案勘误前的历史快照，v2仅更新文档绑定与当前清单入口，产品/测试未变。R69及其列出的历史证据保持原字节；本轮后续文档只记录终态，不声称所有文档仍符合旧SHA。

**仍未完成：**精确参测身份桥及代表性Golden、完整性能/AI推荐、真实模型完整语义评测、新来源/许可、更多平台/原生设备与全部V1发布Gate。完整API/Worker、PG、真实Provider/来源、正常库迁移和新原生运行未由本轮验收；Goal继续active。
