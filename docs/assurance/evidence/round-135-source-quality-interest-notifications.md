# R135 本人兴趣范围的来源质量隔离提醒

2026-10-25。已接通显式订阅、查询质量隔离、本人通知及隔离原文／当时采纳基线重开链路。当前源码的最终相关回归为15模块294/294，另一个完整 Parser 发布模块为12/12；新私库生产 Web 为7场景、94条检查，Root 已实际看完四图。两批 pytest 分别执行，不合写成一次306项套件；94是浏览器检查记录数，不是94个独立测试。完整 V1 仍 active。

**交付合同与语义。** 本轮仅覆盖有合格历史采纳基线的轮胎 SourceQuarantine。它表达“与你关注范围相关的查询，本次更新被隔离”，不确认候选参数、不推断 SKU 消失、撤销或停售。普通 RejectedObservation、无可核对基线的解析／Schema 拒收、车型隔离及恢复提醒不在本片范围。

新增严格布尔 source_quality_notifications。创建省略为 false；编辑省略保留当前有效值，显式 false 才退订；null、字符串和数字不能充当布尔值。合并旧值后重新检查条件。true 仅支持 brand/model/size/oe/technology，且 metric_keys、changed_fields 均为空；不支持的组合固定422 source_quality_interest_filter_unsupported。界面保留原条件并解释限制，不静默删条件或清筛选。旧修订／DTO缺省按 false，false 指纹保留旧算法；true、false 互换追加修订，暂停／归档／恢复保留选项，恢复仍需另行启用。

030_interest_source_quality 为旧兴趣修订增加默认 false 的列。独立旧029兴趣切片、重复迁移、新鲜初始化和失败DDL回滚有目标覆盖；这不等于正常部署旧库的整体升级验收，也不建立活 PostgreSQL 或数据库原生防篡改的证明。

新域为 tire_source_quality，沿用 interest-event@1；action/state=quarantined、revision=1、subject_id 为隔离原行ID，before=null，changed_paths 仅 source_quality。after 明确 accepted=false，保存隔离观察、当时基线及可核对的历史成员。evidence_valid 仅表示引用图核对通过，不能将候选称为已采纳事实。候选身份／参数、正文及内部会话字段不进入事件；两份原始URL各自冻结，不借URL差异推断页面变化。

相关性只取同来源、同 canonical query 的合格历史基线。保留锁内实际传入的最近成功前驱 Verification，不能用同快照最早核验或今天最新记录替换；逐成员绑定历史身份、FactVersion、locator 与成员／事实哈希。全部 AND 条件须在同一成员成立，不能跨成员、来源或快照拼接，也不用当前身份、人工覆盖或本次候选补全。quality match 使用独立 source-quality-interest@1，冻结显式订阅、完整 criteria 和匹配成员引用；旧 explicit-interest@1 与九域合同保留。

首次构建时，合法旧资料确实缺少证明可以保留原隔离／audit而不建新事件或通知；真实错关联、哈希矛盾不能伪装成证明不足。成功冻结之后，绑定原行、查询、基线、成员或兴趣修订缺失／矛盾固定503 source_quality_interest_history_invalid，不用当前记录修补。回读验证当时的冻结修订，不要求它仍是兴趣的当前 head。

隔离、质量事件及通知在原采纳锁和事务内发布，不自行 commit、联网或进入采纳分支。只在新 origin 首次插入时评估当前最新 enabled、未归档且时间合格的兴趣；既有 origin 重放不重评、不补投。暂停或事后开启不补历史，preview 仍只扫描原九域。新域显式跳过 Webhook outbox，包括已登录且有启用订阅的情形；原域正向 outbox 行为另有回归。早先独立提交的 QueryRun／RawCapture 不承诺随本事务回滚删除。

当前 service.py 另补 QueryRun 终态阻断：已存在该 run 的 SourceQuarantine 时，record_success 在新原文／采纳写入前拒绝重入。原隔离候选或恢复为合法内容、ok 或 not_modified 两种核验状态，都不能复活同一 run；即使调用者捕获异常后 commit，也不新增隔离、audit、事件或通知，不改变采纳事实及核验时间。后续审批须由新的在线 QueryRun 消费。

**读取与界面。** 列表只核元数据和封存绑定，不读两份正文。本人通知详情核双正文 SHA，已读写入前核图；越权继续404。前端先读本人通知详情，再按 exact quarantine ID／baseline snapshot ID 读取原文，并核现有DTO中的ID、来源、各自时间／解析器／哈希及隔离基线指针，分别计算正文 SHA。旧隔离DTO没有 query_key／query，查询图由服务端核验，本轮未给它添加虚构字段。

新质量通知在列表下方打开并聚焦独立冻结区域，明确“未采纳／本地历史”、相关性来自当时采纳基线；旧九域仍使用原对话框。每次原文动作重新核本人通知详情，再读准确绑定原文。取消、卸载和 owner epoch／signal 撤销会关闭读取，迟到结果不得恢复旧区域。兴趣保存不创建抓取任务、Worker daemon、模型调用或质量历史补发。

**实际检查与历史失败。** API／Worker 检查使用既有受管 runner 和新私槽。sources_stable、resources_closed=true及unexpected denials=0在此明确指最终 final-b、r135pr 两批，不覆盖此前启动阻断或红批的判定。使用项目 venv Python 3.12.10，不等同 C2 的3.14环境。以下结果保留各自源码版本与失败状态：

| 证据批次 | 实际结果与范围 |
|---|---|
| 初始订阅／迁移合同 red-a | 32执行，12过、20失败；其中2个迁移例先卡旧binary前置，不构成030业务红例，其余按原回执保留 |
| stage1-a 启动阻断 | ChildPolicy精确pin启动前拒绝，pytest未执行；不计业务红例，后续窄修支持pin另有独审 |
| 阶段1 stage1-b／stage1-c | 先30/32，修正历史切片前置后32/32；仅该阶段合同，不代表后续发布链 |
| 阶段2 red-a、revision-red-a | 分别33过22失败、0/1；后续修正冻结修订读取边界，红批不覆盖 |
| 历史 stage2-a／stage2-b | 56/56、57/57，后者绑定旧 service SHA 81870c…7cde7a；不是当前806a源码的新绿 |
| 旧相关 regression-a | 13模块234执行，221过、13失败，原 verdict 保留 |
| Golden diagnostic-a／b | 各0/1，保存定位证据；两个失败探针不是通过测试 |
| 终态重入红／绿 | 新增四参数反例先0/4；补丁后新4项＋旧审批2项，共6/6 |
| 最终短槽 final-b | 15模块294收集／执行，unique=true；294过、0失败／跳过／incomplete |
| 独立短槽 r135pr | test_parser_releases.py 完整模块12/12；与 final-b 无测试模块交集，仍单独记批 |
| 前端／SDK | 新SDK tsc及Node9/9；旧interests tsc和原runtime夹具通过；三端noEmit各exit0 |

最终 final-b 的763项源码输入稳定，24个 managed_parser 子进程全部 exit0、live=0；r135pr 的23个 managed_parser 子进程也全部 exit0、live=0。两批资源门及非预期拒绝门均通过。进程数字分属两次执行，不冒充同一批或完整项目测试总数。

当前 service.py SHA 为 806a81824a1668b016adfd54c2addfa150909f28e96bc0ec99e8d394c683109c，已在 final-b 源记录及最终 UI fixture 的 started.sources_before／stopped.sources_after 中绑定。旧57项回执、旧后端静审与新终态6项回执不拼接替代当前294项批；终态补丁及失败分类另有独审。

新SDK9项中的“破坏绑定”一项含19个向量，不另加为19个独立测试。首SDK红批6项中4过2失败，旧SDK确实接受缺失绑定；原测试版本已另存。类型预检失败和后续中文字典两次修正也分别留账。八文件检查前／后点位pin一致不等于连续监测；原三端通过绑定原UI，最终字典版另有Web noEmit和新UI pin，未追认旧检查或重复SDK／原生两端检查。

**234项红批与 Windows 长路径局限。** 13项失败中，2项涉及审批夹具flush及同一已隔离 run 重复消费，现补终态阻断并以新四参数反例和旧节点回归。其余11项 Golden 失败停在 bundle seal／_plain_path，未到预期的 Golden gate，不按新匹配逻辑失败或成功放行解释。

独审对同一275字符 archive 成员只读 lstat：普通路径 FileNotFoundError／winerror3，Windows扩展路径前缀下同文件实际存在且为7984 B；新诊断b的真实 seal trace 另记录263字符普通路径 lstat 报missing。最终改用全新短私槽，不修改 Golden 指纹／gate、bundle完整性门或产品长路径实现。两次临时诊断均已恢复 test_golden_release_gate.py 原字节 SHA 8bdfc5564835988fcb0ef0ceee203c9ef28166162279ca394ce2db176c19710c。当前短槽回归通过不代表 Windows 长路径兼容问题已修复；该产品局限单独保留。

service 变更继续改变动态 Golden 合同指纹。没有硬编码旧 digest、回填旧报告或将旧回执追认为当前 Parser 发布授权；这里的合成断言也不是代表性真人 Golden。

**生产构建、首 UI 失败与工装修正。** a135 Web生产构建通过，web-icons／web-next／web-pwa 三阶段 supervisor exit0，181源记录、8983依赖记录稳定，生成原件恢复。verification SHA 为 4bee2079f123268833a30a60ff8729a3be4e6cb6e2d3cba07f907e1cc752fa3b。Web freeze 不替代后端源码绑定，也不代表原生宿主、设备、PWA安装或离线验收。

运行前静审曾纠正工装的 reason字符串、品牌规范化预期、隔离查询终态 consent_required、基线两个pre须定位正文四处假设，原件保留。实际首 UI a1351b2c3d4e5f60 随后在57条检查后失败：初开通知详情、焦点及未采纳文案已记录，但没有任何侧原文请求。两个 reader 的 has 内层错误携带外层 frozen region 祖先，无法相对匹配；等待点击时，提前创建且尚未处理拒绝的 waitForResponse 超时，Node exit1，未经过正常 catch/finally，browser result 残留 running。

首批 host 为 failed，API／Web／browser 子进程分别0／0／1，forced为空；截至浏览器残件，page／console／HTTP错误为空，不能据此把业务或收尾标绿。Root之后实际观察35个指定PID均缺席、查询错误空、18986／18987各5秒上限探针10061；这是单独终态观察，不把残件追认为正常浏览器收尾。

最小QA修正仅将双reader的 has 改为相对 page.getByRole，先断言各 count=1；10处提前 waitForResponse、2处 waitForEvent 立即附拒绝处理，但仍返回、await原Promise，失败仍严格传播。Node语法检查及隔离Promise探针通过；生成脚本业务块之外前缀／后缀、console／HTTP／cleanup门、hold helper和预算尾段逐字节不变，没有 console abort 豁免。原suite／generated／metadata已在 before 保存；改后候选经独审后才执行新批。

**最终 b1352c3d4e5f6071 的实际行为。** 新私库真实注册A管理员、UI查询两源基线26／3；UI断言质量订阅默认false及兴趣默认暂停后，手动勾选订阅并启用。另用API建立同条件false兴趣、独立context注册B并建立true兴趣。合成来源A从26行降至1行后，本次查询为 consent_required／source_quality_quarantined，variants与provenance为空；B仍采纳3行、事实不变。A原基线Evidence前后全JSON相同。

A本人恰一条质量通知给true兴趣，false对照无通知；独立B有自己的通知，并实际核双方越权详情404。通知冻结准确前驱、双原文哈希和同一基线成员匹配，不造SKU主体或采纳候选。实际UI已读PUT、未读过滤、冻结区聚焦、详情先行及双原文HTTP／正文SHA均通过。

同批页面业务请求为：兴趣POST1、已读PUT1、通知详情GET5、隔离原文GET3、基线原文GET1、来源查询POST4、登录／退出POST各2。3次隔离读取包含成功重开、手动取消和owner变化两次held读取；初始化、核对及独立context404来自 APIRequestContext，不混成页面请求数。

两次hold均先由真实 route.fetch 取得200正文，浏览器原请求实际 ERR_ABORTED；手动取消及真实账户UI A退出→B登录→B退出→A登录后，A返回时才释放旧owner正文，旧冻结区域／原文未重现。两次记录均 body_obtained、aborted、removed=true。delivered=true只记录route fulfill调用返回，不证明React收到忽略AbortSignal的迟到正文。此批没有执行不退出登录的同ID重验矩阵。ADR-057允许同cookie历史会话资料聚合，本批不要求B在该cookie绝不继承A记录；独立context的404证据与UI owner撤销分别记账，不扩大为永久账户或生产租户隔离。

最终7场景94检查全部通过，实际 input_pins 字典为9308项，inputs_unchanged／prepared_runtimes_unchanged=true。合成来源fetch4；真实来源、Provider、model、embedding均0，fixture守护中的外连／子进程／正常库attempt计数0。page、console、HTTP、外源及cleanup错误全空，console_events也为空。稳定性结论来自同批回执，不新增连续监测或完整安全审计主张。

Root实际观察四图：1365×900表单与通知、390px隔离原文、320px基线原文。表单图是在手工勾选之后，默认false由checkbox实际断言证明；低处解释／保存需滚动。通知明确未采纳与基线相关性，390px可见 quality_revision=1／一行隔离原文，320px可见 quality_revision=0 的基线原文及换行哈希。长正文使用滚动区；390px底部导航覆盖某一长滚动位置的最低部分，不保证任意位置全文无遮挡，也未完成完整WCAG／读屏或设备验收。

最终host三监管进程自然exit0、forced为空；Chromium exit0／signal=null、server-close和browser_close_returned=true，fixture正常shutdown。Web另记录143个Node进程自然关闭、Job2/2全观察且active为空，与三个监管退出码分开记账。Root另实际观察35指定PID均缺席、查询错误0、双端口10061。pytest／host汇总资源关闭不等于逐DBAPI句柄关闭或私库删除；Python guard及Job也不是OS sandbox，执行沿既有require_escalated边界，不改ACL或守护门。

最终源码、文档与资源收尾的绑定以证据入口中的Root收尾JSON为准；静审、实际执行、Root看图和资源观察分别取证。

**仍未验收与回退。** 真实来源长期运行、真实Responses／Provider／embedding、代表性真人Golden、正常部署旧库整体升级、活PostgreSQL、Windows长路径产品修复、原生宿主／物理设备、完整WCAG／读屏、PWA安装／离线及完整V1继续留账。已测两会话重放既有origin，不把它称为并发首次发布竞争验收。保存兴趣不自动启动daemon，生产UI也未运行独立Worker守护进程。

功能回退以追加新兴趣修订关闭质量选项或暂停实现，保留原事件／通知／历史；不drop列、删通知、回写旧修订，代码回退也需保留已迁移schema兼容。当前报告按各批回执分别记账，保留历史失败及各项未验证边界。

**证据入口**

- [计划](../../plans/2026-10-25-source-quality-interest-notifications.md)、[合同修正](../../../.artifacts/r135-source-quality-interest-20261025/scope-amendment-1.md)、[冻结wire](../../../.artifacts/r135-source-quality-interest-20261025/wire-contract.md)、[计划独审](../../../.artifacts/r135-source-quality-interest-20261025/plan-review.json)。
- [旧234项红批](../../../.artifacts/r135-source-quality-regression-a-20261025/result.json)、[失败分类及终态补丁独审](../../../.artifacts/r135-source-quality-interest-20261025/regression-diagnosis-review.json)、[终态4项红例](../../../.artifacts/r135-source-quality-terminal-replay-red-a-20261025/result.json)、[终态6项绿批](../../../.artifacts/r135-source-quality-terminal-replay-a-20261025/result.json)。
- [最终15模块294项](../../../.artifacts/r135-final-b/result.json)：21432 B，SHA b4cedf3cfd89fdd5bb4cece015753ade48f89ccc21abc6d5fc626d1e238dff9c；[独立Parser模块12项](../../../.artifacts/r135pr/result.json)：19580 B，SHA cc6b97d6638d660f0d37a65aae05365c892a0017906336702c623de781bcdb3f。
- [前端实际回执](../../../.artifacts/r135-source-quality-interest-20261025/frontend-checks.json)、[字典差量回执](../../../.artifacts/r135-source-quality-interest-20261025/frontend-checks-capability-labels.json)、[前端独审](../../../.artifacts/r135-source-quality-interest-20261025/product-review-frontend.json)、[生产构建](../../../.artifacts/r118-material-workbench-20261021/web-build-a1350a1b2c3d4e5f/verification.json)。
- [首失败UI残件](../../../.artifacts/r135browser-a1351b2c3d4e5f60/result.json)、[首host终态](../../../.artifacts/r135uihost-a1351b2c3d4e5f60/receipt.json)、[首批资源观察](../../../.artifacts/r135-source-quality-interest-20261025/first-ui-resource-observations.json)、[QA最小修复](../../../.artifacts/r135-source-quality-interest-20261025/qa-fix-notes.json)、[修正工装独审](../../../.artifacts/r135-source-quality-interest-20261025/qa-revision-review.json)。
- [最终UI](../../../.artifacts/r135browser-b1352c3d4e5f6071/result.json)、[最终host](../../../.artifacts/r135uihost-b1352c3d4e5f6071/receipt.json)、[Root四图实际观察](../../../.artifacts/r135-source-quality-interest-20261025/root-visual-review.json)、[最终资源观察](../../../.artifacts/r135-source-quality-interest-20261025/root-resource-observations.json)。四图观察回执SHA为4479a1d12e4960d61c867fadf08ac2be3b4d4d7d8c1a90291f191d44fa67152a。
- [当前后端回归独审](../../../.artifacts/r135-source-quality-interest-20261025/backend-regression-review.json)、[实际运行及看图／资源独审](../../../.artifacts/r135-source-quality-interest-20261025/runtime-review.json)、[Root收尾回执](../../../.artifacts/r135-source-quality-interest-20261025/root-closeout.json)。独审决定、各批执行结果与最终收尾绑定分别读取，不互相替代。
