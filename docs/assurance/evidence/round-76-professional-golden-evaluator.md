# 第76轮：专业测试精确SKU评估器复核与补修

专业 TestEvent→精确 SKU 身份桥及同场候选解释已有独立工程评估器。最终7案按冻结预期通过，其中6案为合成工程案例，1案为真实论文的身份未知绑定复核；**真实精确SKU正例0、外部真人审核0，发布Gate仍为inconclusive，wrong_merge_count=null，完整V1未完成。**本轮没有新增前端功能、生产迁移或模型调用。

## 实现及独立预期

- [冻结合同](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-professional-test-golden-evaluator.md)：SHA `7d042e1581e8900d7a8f12bf5c81b29c831874fa48506fc7b9fcda63a5508fc8`。原规格、旧Golden的tire／vehicle合同及Parser发布门保持原字节。
- [纯比较器](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/professional_golden_checks.py)：最终SHA `de84fa53841360cca56cbf6cd48bcf7b18b8f91bd0ccddc708e0c810522eba44`。closed字段与图引用、精确身份、HTTP请求／响应及修订链、原始成绩与定位、同场候选、排除整组为空、分层决策／配对覆盖均有检查；差异计数不因报告截断而归零。
- [受管理语料](E:/Mix/project/tire-info-manage-sys/packages/domain-types/fixtures/professional-test-bridge-v1/manifest.json)：SHA `d222b70c14dc09584f06590902fd13eac9559ac72e3d1a203adc35c341eb91f2`，7案、8文件、9外部绑定。预期由Root独立手写，不从产品、actual或seed函数生成。合成PDF包含逐字段身份、条件／协议／单位与5条原始成绩短句；完整小数、负零、并列、缺失和来源名次均保留。
- [读取器](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/professional_golden_corpus.py)：每次读取先核全体受管理文件、库存与pin，严格UTF-8 JSON拒重复键／非有限数／深度及字节超限，拒路径逃逸／symlink／junction。外部PDF／JSON只由显式verify_external核摘要，不自动读取内容或敏感文件。
- [实际采集器](E:/Mix/project/tire-info-manage-sys/scripts/run_professional_golden.py)与[HTTP适配器](E:/Mix/project/tire-info-manage-sys/apps/api/tests/professional_golden_support.py)：GUID私库、真实文件对象仓库；从生产路由取得完整事件GET、R71 preview／decision／current及真正R75 POST。原始SKU成员／身份来自实际DB，动态UUID只用于引用一致性。
- [离线CLI](E:/Mix/project/tire-info-manage-sys/scripts/verify_professional_golden.py)：只核冻结快照，固定`offline_bound_snapshot`；输入自报`private_http_observed=true`不认证真实执行。每案最多512000B，读取限量并核文件身份／尾部库存，actual总量32MB；报告不覆盖既有文件。

冻结样本包括双SKU精确正例、manual未知、缺run_flat断言、所选B撤销、同码不同MSPN／EAN命名空间、显式代码冲突、R74论文身份未知。R74未建立测试尺寸，保持`source_review_only`，没有虚构尺寸／事件／SKU／R71／R75或性能值。其原件、捕获回执和既有agent文面复核分别绑定；agent复核不认证真人。表3颗粒分类比例不作整胎磨耗／寿命或性能排名。署名与CC BY4.0见语料README；provider_use／export继续false。

## 最终验证

各行是不同范围与阶段，不能相加为完整API／Worker或产品验收。

| 验证范围 | 实际结果与绑定 |
|---|---|
| 最终生产路由私库采集 | 7案完成；39个被记录的R71／R75 HTTP观察，其中R75 POST为4次；6案为合成输入，真实R74案无产品HTTP。133个输入源码首尾稳定 |
| 禁止操作护栏 | network／child／normal DB均0；26次Windows内部socketpair握手仅放行本次精确临时endpoint，属于允许计数 |
| Root最终相关目标 | 124 passed、3 skipped、exit0。含比较器46、CLI18、读取器沙盒60；3skip为沙盒不能创建真实symlink／junction，不隐去 |
| 读取器真实路径补验 | 独立宿主63 passed、0skip，源码与最终读取器一致；只验证文件读取能力，无应用／DB／外网 |
| 最终独立反例 | 25 passed与10 passed分别执行，0失败／错误／跳过；最终de84源码和新的7案actual首尾稳定，禁应用／DB／网络／子进程尝试全0 |
| 旧Golden最小回归 | 60 passed、exit0。两个用例导入vehicle fixture，先把全局app绑定未打开的GUID私库；所有DB连接被禁止，私库文件未创建。非纯无应用导入测试 |
| 离线及退出策略 | 离线报告与当次采集报告完全一致；默认工程核对exit0；`--require-golden-gate`为exit2，不把工程通过当成真人Golden通过 |

最终执行：[execution-receipt.json](E:/Mix/project/tire-info-manage-sys/.artifacts/r76-http-final-f7c5608292d04e93a521c113a280738d/execution-receipt.json)、[report.json](E:/Mix/project/tire-info-manage-sys/.artifacts/r76-http-final-f7c5608292d04e93a521c113a280738d/report.json)、[offline-verification.json](E:/Mix/project/tire-info-manage-sys/.artifacts/r76-http-final-f7c5608292d04e93a521c113a280738d/offline-verification.json)。这是进程内TestClient／ASGI生产路由调用，无监听服务、浏览器、正常部署或原生设备验收。

最终覆盖：synthetic六案中已知决策8／已查8，预期正向准入5／观察5，未知断言4，已知不同SKU配对3／已查3，观察错链／无依据准入／错合并各0。真实身份未知一案不计负例、正例、配对或真人覆盖。schema、case集合、决策／配对三门通过；human门inconclusive。此处3对及0观察错误仅适用于冻结合成集合，不能换成人工Golden错误合并率0。

独立终态：[25项反例报告](E:/Mix/project/tire-info-manage-sys/.artifacts/r76-independent-review-70e690508ba343e0a0d794fffc83ab91/ADVERSARIAL-FINAL.md)、[10项作用域／链反例报告](E:/Mix/project/tire-info-manage-sys/.artifacts/r76-bindings-final-f0bca6cc4cf94c4c9ac119da17e9fa87/REVIEW.md)。包含原值／来源名次／跨场定位、bool与int／字符串、unknown准入、全拒绝、错误合并、人类tier自报、case缺失／额外／重复、撤销后整组解释泄漏、preview当前绑定、决策link／revision链和完整checks等必要变异。

## 发现与修补记录

独立审查发现的确定问题均已修补并保留原阶段回执：合成PDF未含成绩短句；CLI stat后无界读取；Windows内部socketpair被全拒；platform诊断在护栏前可能启动子进程；JSON文本换行导致预算与写出字节不一致；actual／外部证据尾绑定不全；嵌套投影／维度／证据引用及Literal布尔类型漏核；preview作用域、checks、完整决策修订链漏核。类型差异同时影响schema门与语义差异，避免错误schema显示通过。

两项真实逃逸反例曾取得“应失败却passed”的红例：改写create decision.link.id或decision.event.revision_id后重绑响应SHA。红例精确绑定`67c4de96…04ef0`，不是执行后单独读取的`08612283…0f706`；后者10绿及最终de84新actual的10绿分别保留，不混用源码身份。

首轮沙盒上传阶段失败，独立os.link探针确认WinError5；相同护栏宿主真实对象仓库后成功，未Mock仓库或放宽Parser预算。初期pytest默认临时根失败、长参数导致Windows环境变量长度错误也保留。Root误把旧Golden两个vehicle fixture导入放入禁main的pure harness，得到76通过／2护栏拒绝；改用预绑定未打开私库的legacy harness后60项通过，产品及旧测试未改。PowerShell默认外壳将Python非零码映射为1，显式`exit $LASTEXITCODE`后确认require-gate实际exit2；两回执都留存。

ELANORE及NHTSA新材料仅有[来源研究观察](E:/Mix/project/tire-info-manage-sys/.artifacts/r76-source-research-18a383d16846484ea067057b414945d3/REPORT.md)：缺完整精确身份，且未形成新生产捕获与确认存储许可，不纳入正例、不补造source SHA或许可。未扩大抓取、绕过挑战页或新增模型用途。

## 保全、交接与后续

R75基线954源码、365展开dirty、29文档、80证据、4配置已先核；本轮仅新增评估源码／测试／受管理样本，并更新README／两份交接页／风险登记四份既有文档。最终机器清单：[verification-final.json](E:/Mix/project/tire-info-manage-sys/.artifacts/r76-professional-golden-d7a59579390042afae811c01858321c2/verification-final.json)，以实际封存及独立终审为准。清单不是文件归档，交接仍须带完整工作区、列明证据和本机私有保全；私库／凭据不列公开证据。

未提交／推送，未启动正常API／DB、调用Provider、运行原生设备、修改R70门或重跑完整API／Worker／三端构建。R75 B工程交付、现有会话聚合语义和其余风险边界不变。本轮无前端变化，无新增UI验收主张。

接续优先级：为有合法原件且能建立完整精确身份的真实专业样本补独立预期与外部人工审核；保留unknown，不能从研究编号或同名同尺寸猜SKU。随后为C专用AI推荐冻结许可／同意／证据与模型语义合同，真实Responses及V1各发布Gate独立验收。完整Goal继续active。

复核命令（PowerShell7，仓库根执行；现有报告路径另选新文件避免覆盖）：

```powershell
& apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/verify_professional_golden.py --actual-dir .artifacts/r76-http-final-f7c5608292d04e93a521c113a280738d/actuals --verify-external-root .
& apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/verify_professional_golden.py --actual-dir .artifacts/r76-http-final-f7c5608292d04e93a521c113a280738d/actuals --verify-external-root . --require-golden-gate
# 第二条的 $LASTEXITCODE 应为2；外壳需透传时使用 exit $LASTEXITCODE。
& apps/api/.venv/Scripts/python.exe -X utf8 -B .artifacts/r76-professional-golden-d7a59579390042afae811c01858321c2/seal_current.py --audit
```
