# R130 已加载规格摘要预览：实施与验收

2026-10-23。本项通过，完整 V1 仍 active。没有 EPREL Key，继续不依赖该凭据的工作，不再重复询问。

## 本次行为

查询与关注的原“查看证据”按钮现在支持本地摘要：鼠标停留300ms打开，键盘focus-visible立即打开；鼠标、键盘焦点和浮层悬停共同保持，最后离开150ms关闭。点击仍同步调用原证据入口并使用原按钮回焦。摘要无业务请求，不新增可交互内容或tabstop。

同一工作台最多一个预览。query沿来源rowKey、watch沿关注记录ID分配owner，防止同SKU跨来源/关注记录串内容；过期timer只释放自己的owner。Escape、点击、外部焦点/指针、滚动、视口变化、隐藏、菜单/dialog、卸载和快照变化使预览关闭，原停留不能立即重开。原生右键保留，portal正文只阻止事件冒泡到卡片菜单。

摘要标明“已加载规格摘要”“摘要节选，完整信息见卡片”，分开显示原记录规格和本次加载的身份状态。保留0，普通字段最多32 Unicode码点、身份最多64，受限空间进一步缩短并显示省略号。六类固定风险完整显示：撤销、身份修订待核对、未resolved来源冲突、参数异常、字段判定冲突、关注身份复核。关注外层tracking_state明确传入。不用当前身份代码、事实默认值或人工覆盖替换原字段，不把历史值称为LIVE。

新增专用hook/portal，Workbench与CSS局部接入；后端、DTO、SDK、数据库和依赖未因本项修改。设计见[冻结计划](../../plans/2026-10-23-variant-hover-preview.md)。

| 最终产品文件 | 字节 | SHA256 |
| --- | ---: | --- |
| `apps/web/components/variant-preview.tsx` | 14697 | `907f8f6e43dcd7813f7d476a81d20fb3390b8f9eb48efea7b5373728d101a862` |
| `apps/web/components/workbench.tsx` | 120878 | `aad131c4e8f5c77aabe63ef14773300df659aa630c35fb3d40b5a46da81e0e41` |
| `apps/web/app/globals.css` | 146639 | `2336c5ecc5e24e0132f0cc0fa995d2ffe956d31fb38eea21ab6fa5ec14540f71` |

## 发现与修复

首稿产品独审发现P2：持久Tab epoch会把证据区内较早的Tab当作解除抑制的依据，Enter关闭证据后的程序化回焦可能重开摘要。已改为匹配当前Tab产生的同一次原生focusin事件，消费后失效；非Tab按键、指针、当前任务timer和卸载清除意图。首稿三文件归档在`pre-focus-fix/`，原[REQUEST_CHANGES](../../../.artifacts/r130-variant-hover-preview-20261023/product-review.json)保留，另有[修正ACCEPT](../../../.artifacts/r130-variant-hover-preview-20261023/product-review-final.json)。

三个浏览器失败批次均保留，未拼接为成功：

| 批次 | 原结果 | 后续处理 |
| --- | --- | --- |
| `a1301b2c3d4e5f60` | failed，38条检查后Tab前置断言失败 | 原QA按DOM列表推算Tab前驱，未记录实际焦点，具体落点不可追认。改为原按钮预置后真实Shift+Tab/Tab，并逐步记录焦点。 |
| `b1302c3d4e5f6071` | failed，84条检查后菜单等待超时 | Root截图确认页面已滚至更多按钮；自动滚动与菜单滚动关闭竞争仍属推测。改为两按钮同屏、4次位置与命中稳定，再开预览；增加有界被动事件时序。 |
| `c1303d4e5f607182` | failed，157条检查后零请求窗口失败 | 合成hidden只改document.hidden，visibilityState仍可见，触发原auth/source监听的两次GET。修为双状态一致、finally按原descriptor恢复，不放宽零请求门。 |

对应旧QA完整归档为`qa-first-run-8b52cbbef840e947.mjs`、`qa-second-run-649f5a4a23aaa3de.mjs`、`qa-third-run-c5e1d6958015459f.mjs`。产品在修正P2后的四批UI之间没有改变；始终使用同一a130生产构建。各批的Root说明和35个精确PID缺席/双端口关闭观察分别保存，原failed不变。

## 当前验证

修正P2后Web、desktop、mobile三端`tsc --noEmit --incremental false`实际均exit0，见`typecheck-*-b.json`。初稿a检查仅为历史证据。最终QA `node --check`实际exit0（`qa-syntax-e.json`）；未变薄宿主AST解析exit0（`qa-syntax-a.json`），该解析未导入或执行宿主。

[生产构建a130](../../../.artifacts/r118-material-workbench-20261021/web-build-a1300a1b2c3d4e5f/verification.json)实际exit0/passed，三阶段0，源码/依赖稳定，生成原件恢复。128204 B，SHA `2054527daa5bcb3135925c480b61e43c53d2993fa8da1c94b7d141a135e11052`。沿用原受审构建器、进程守护与薄宿主，没有启动默认API。

[最终浏览器d130](../../../.artifacts/r130browser-d1304e5f60718293/result.json)实际passed，2524395 B，SHA `9aeaf55da7f93e7fa7233efb28cce9f77dcefa95c69b02e856a56640729b0226`。同批10个场景标签、460条检查记录、184条观测，不能称460个独立测试；9301项输入及准备运行时稳定。

- 九道精确请求门全部完成并移除：两次真实私槽来源查询（26/3行）、三次真实证据GET、一次真实关注POST201；另两次长值/六风险查询和一次重复关注GET为有界route合成，无后端dispatch。
- 22个预览/交互窗口均零新增业务请求，原查询输入节点/值与比较选择保全；必要的显式键鼠动作允许转移焦点，鼠标窗口和held关注响应另有严格焦点断言。
- 实际覆盖延迟/桥接/持续保持、Escape抑制、旧timer与同SKU跨来源owner、watch外层身份风险、菜单/命令面板互斥、原生右键默认行为、外部关闭、拖拽、导航卸载及触控仿真。
- 三次证据读取分别经鼠标、触控仿真与键盘。键盘路径真实Tab273次到关闭按钮，再Enter关闭，同原按钮回焦且450ms内不重开；随后新的Tab/Shift+Tab可重开。不是调用内部关闭函数代替用户操作。
- page/console/异常来源/异常HTTP/gate/coverage/cleanup错误均空，无failed HTTP。fixture来源执行2次，真实外部来源、Provider、模型、embedding以及外网/子进程/正常库尝试均0。

独立复核见[QA及后续定向审查目录](../../../.artifacts/r130-variant-hover-preview-20261023/qa-review.json)和[最终生成证据复核](../../../.artifacts/r130-variant-hover-preview-20261023/runtime-review.json)。审查员重算九门与22窗口，不冒充Root实际执行。

## 实际看图与资源终态

Root逐张实际查看同批10张图并核哈希，见[视觉记录](../../../.artifacts/r130-variant-hover-preview-20261023/root-visual-review.json)。默认正文13px、辅助12px；所有字段节选和六风险无内部滚动、视口内完整可见且避开原触发按钮。

| 视口 | 浮层宽×高 | 上下边界 |
| --- | --- | --- |
| 1365×900 | 480×316.359375 | 478.46875–794.828125 |
| 390×844 | 374×354.046875 | 450.453125–804.5 |
| 320×844 | 186×599.015625 | 236.984375–836 |
| 320×420 | 186×391.734375 | 20.265625–412 |

320短屏通过缩短普通字段节选适配，风险未截断；未把no-fit关闭当作通过。浅色、深色、高对比、forced-colors文字和边界可辨认。宽屏局部200%字体为24/26px，480×880.234375整体可见；这是CSS文字压力场景，不是浏览器真实zoom。

[宿主](../../../.artifacts/r130uihost-d1304e5f60718293/receipt.json)自然0/0/0、forced空；Chromium69508自然0/null/server-close；Web Node68740退出143、Job2/2、active空；fixture shutdown_complete。Root另实际观察最终35个精确PID均缺席且无查询错误，18986/18987各5秒上限探针均10061，见[资源观察](../../../.artifacts/r130-variant-hover-preview-20261023/root-resource-observations.json)。所有本轮构建、宿主和浏览器执行均已结束。

[Root收尾核对](../../../.artifacts/r130-variant-hover-preview-20261023/root-closeout.json)实际exit0，42条检查，7279 B，SHA `7b67e0899fdb00410a4732044c08dc83a7431934839515ff3308e554880baa8f`。绑定当前产品/QA/宿主、类型与语法检查、构建/UI/终态回执、10图及旧失败批。9301全量输入稳定是QA记录，Root没有重复全量扫描。汇总关闭不等于逐DBAPI句柄关闭或私库删除，Job/guard不是OS sandbox。

## 尚未完成与续作

本轮是headless、私槽合成来源验收；长值、六风险、重复watch、hidden/blur/visualViewport以及局部字号场景均明确合成。未验收真实触控设备、IME、读屏、完整WCAG、原生宿主、真实浏览器缩放或当前PWA安装/离线；SW blocked，不套用R126旧构建证据。

完整V1还包括专业SKU/真人Golden、真实OpenAI Responses API及Provider、正常库升级、PostgreSQL、原生宿主/设备等独立缺口。下一候选是卡片正文对已有resolved冲突仍一律显示“尚未裁定”的语义问题，先窄核现数据合同与展示路径，再按实际范围处理。EPREL无Key保持缺口，不重复询问；未打开正常/保留SQLite、未commit/push/reset/stash/clean，保留其他dirty。
