# 第64轮：交接目标复核与补修（2026-10-18）

本轮核对用户所说的“交接目标已完成”，并修复实际发现的问题。结论分为三层：**交接资料已完成并补强；第63轮请求合同/输入迁移有历史限定验收，本轮修复后有新的目标验证；同场偏好解读与完整V1均未完成。**未提交、推送或发布。

## 发现与修复

| 发现 | 触发与影响 | 修复 |
|---|---|---|
| P1：GET读取视图被按POST结果校验 | 服务端`device_ai_routes._view()`没有`replayed`，lookup/detail直接返回该视图；TypeScript、Rust、Java三个Host共用要求该字段的POST checker，合法GET 200也会被拒绝，影响准备记录读取与恢复 | 共享类型新增`DeviceAiPreparationView`；POST专用`DeviceAiPrepareResultView`扩展基础视图并保留必填boolean。三端GET使用基础校验、原样保留响应，POST继续严格检查；未给GET补造`replayed` |
| P2：Windows checkout使E1源码pin漂移 | E1测试按原字节SHA绑定两份生产Python源码；`core.autocrlf=true`会转CRLF，原fixture属性只保护向量目录，源码语义不变但测试失败 | 根`.gitattributes`只对`device_ai_projection.py`与`device_ai_value_encoder.py`设置`text eol=lf`。只读Git checkout过滤验证恢复原封存SHA，未改源码、向量或expected |

旧Host自测把带`replayed`的POST fixture复用于GET，公共入口测试则只注入409，因而未覆盖真实成功响应差异。本轮用无POST专属字段的GET fixture补齐三端正负例；新增Python跨语言回归，将实际FastAPI TestClient生成的fresh/replay/lookup/detail响应原样交给公共SDK消费，防止两侧独立mock再次漂移。

保持原请求12/6/4键、域/mode、同意/归属/权利门与所有封存预期不变。opaque响应内部、完整value/citation和mixed/personal/test_event后续协议义务继续保留。孤立surrogate的纯函数疑点经真实请求模型核对已有422约束，未据此改动生产代码或宣称submit会500。

## 实际验证

| 范围 | 结果 | 证据与适用边界 |
|---|---|---|
| 公共SDK | 192 Host检查＋34 decoder检查、public-contract编译及运行通过 | `.artifacts/runtime/device-ai-public-get-review-2ff80dd022aa460d9c103d01ba5cb1ba/`；包括修前GET失败及修后成功、GET/POST类型区别、POST缺/坏flag、GET关键字段、404/传输错误 |
| 实际API响应→公共SDK | 5通过、19项未选；1条既有Starlette弃用warning | `.artifacts/review-recovery-d709c14ee6b74900824863dc350dd448/api-contract-final.{log,xml}`；真实隔离路由/内存SQLite/合成材料，Node使用注入transport，无Provider/官网 |
| Windows Rust Host | 23通过、1项既有OS凭据测试保持ignored | 同目录`rust-host-outside-sandbox.log`；前置真实GET复现失败保留。首次sandbox运行22通过/1文件journal失败/1ignored，同一目标sandbox外23通过；没有把该环境差异当产品修复，也未开启OS凭据测试 |
| Android Java Host | JVM 36通过，0失败/错误/跳过 | `.artifacts/review-java-prepare-view-8f98086888c042eaa073d98564023d5e/`；修前36项中GET用例1失败，修后全过。不是设备、Keystore或仪器验收 |
| E1与checkout | 73通过；Git属性及`core.autocrlf=true`过滤后的字节与原pin一致 | `.artifacts/review-e1-checkout-fix-bd26a2811622437d94f7977f07b0bf05/`；只读模拟checkout，不声称做过整仓fresh clone恢复 |
| 工作区类型检查 | `npm run typecheck`通过 | recovery目录`workspace-typecheck.log` |
| 独立复核 | 三端视图拆分、真实路由输出消费、请求键集/向量与属性规则的只读复核未发现其他可行动缺陷 | 不替代完整安全审计、浏览器或原生宿主运行 |

本轮没有重跑完整API/Worker套件、构建安装包、浏览器UI、真实设备/系统凭据、正常库迁移、官网或模型。第63轮`2705 passed＋77 subtests`继续是**修补前源码的历史结果**；其运行中826文件采样及旧复核回执原样保留，不能重新绑定到本轮已修改的源码。

新Python跨语言测试首跑使用旧服务端测试helper，遗漏SDK要求显式携带的`approved_closure:null`，因此1失败/4通过；只修正新测试请求后5通过。首跑日志保留在`api-contract.log`，没有放宽产品decoder。Node库存探针曾有Windows URL转换的工装错误，也保留原失败与更正。各组验证分别记录，不累加为一套完整回归。

## 交接补强与恢复方式

1. 原始需求位于仓外，现新增`docs/requirements/2026-09-26-tire-intelligence-original.md`原字节副本。53,843B，SHA-256 `f8a2a4434d83824afe36d3e46730ee183e4506acc0c91041b8a122b36e6fc46d`，与用户原件完全一致；Git属性禁止转换该副本。内容作为需求资料，不自动授予外部操作权限。
2. 本轮机器回执：`.artifacts/review-recovery-d709c14ee6b74900824863dc350dd448/handoff-final.json`。列出HEAD、展开后的dirty文件长度/SHA、原文副本、必要证据allowlist及SHA、本轮各目标结果、旧全量适用边界与后续缺口；不包含私有数据/凭据，也不是可恢复的整仓归档。
3. 跨目录/机器交接须另外携带完整工作树及回执列明的证据文件，依赖按锁文件恢复，再核长度/SHA。只clone当前HEAD仍缺未提交实现；只有哈希清单不能恢复文件。正常`data/`与凭据按本机保全，不作为公共交接材料复制。
4. 旧`summary-awaiting-full.json`仅“仍运行”状态被后续终态取代，旧失败、旧run.json和封存向量都不重写。未采集的历史argv/工具版本等明确为unknown，不用当前环境版本冒充历史实测。

本轮回执与[最新交接卡](E:/Mix/project/tire-info-manage-sys/docs/HANDOFF-2026-10-18.md)、[实施计划](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-09-26-tire-intelligence.md)、[ADR-063](E:/Mix/project/tire-info-manage-sys/docs/assurance/decisions/ADR-2026-063-device-ai-v1-contract.md)共同阅读。下一步仍是先冻结同场偏好解读的hash/响应证据DTO/稳定ID与错误码，再实施和验收；没有把这项设计或原规格剩余Gate声明为已完成。
