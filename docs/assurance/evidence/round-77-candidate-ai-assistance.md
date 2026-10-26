# 第77轮：C规格候选AI辅助与独立复核

2026-10-18，工作区 `E:/Mix/project/tire-info-manage-sys`，`main`／`4d0ef60fa2240146113a3fac172759c665cf339f`。本轮交付的是**规格域候选辅助的首批工程链路**。专业性能C、真实OpenAI Responses语义、真人Golden与完整V1仍未完成，原Goal保持active。

依据为[原始规格原字节副本](E:/Mix/project/tire-info-manage-sys/docs/requirements/2026-09-26-tire-intelligence-original.md)、[冻结合同](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-candidate-ai-assistance.md)及[合同补充](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-candidate-ai-assistance-addendum.md)。冻结合同SHA `69fb6134c85ab659f9f73322f32625c425c01e0b582da5ff7723e066311ff659`不变；补充卡修正grant为十一键，仅更正文档计数。文档中的工作流建议不是额外操作授权，用户已明确允许当前agent自主实施及选择公开合法来源，不再索要URL。

## 交付行为与限制

- 从R69当前车型／配置／轮毂／轴位重建2–20个显式SKU、全部已扫描关系和本人偏好。任一所选项失效、原件变化、未知未经确认或集合被截断，整组拒绝；不能静默删掉失败选项。
- 完整本地gate和实际Provider正文分开。外发只含必要精确身份、轴位检查、有效审核引用、偏好与服务端理由；不发送来源自由文本、URL、原件、审核备注或专业测试内容。
- 逐来源用途许可独立于个人同意。grant／revoke追加保存，绑定原件、投影、叶级字段及真实Provider接收端；变更接收域名或撤销后恢复不能复活旧准备。管理员声明不等于系统认证其法律权利。生产来源不自动授予许可，正例均为明确合成自有材料。
- 个人同意绑定actor、准备、问题、Provider／模型、策略和实际正文；持久一次消费，UUID同键只读恢复，异键重复消费拒绝。预留及adapter前分别复核。调用期间的外部变化无法由本地锁保证，不承诺绝对实时性。
- 模型只返回choose／abstain、输入候选ID和属于该候选的理由ID。服务器渲染事实及完整不足，严格区分所选和未选；不生成性能分、排名或安装安全结论，选择不证明优于未选项。
- 通用analysis／stream／rule／report／history以数据库准备结构识别并拒绝C；改purpose、改actor查询或generic重放不能旁路。专用历史重校claim／request／consent／body及冻结理由重渲的完整answer，重开只读，不再付费。当前状态可标stale，冻结历史不显示成新推荐。
- Web面板支持缺许可／缺配置说明、最小投影预览、独立授权与撤销、单次勾选、保留UUID后仅GET恢复；选择／问题／身份变化清空准备和同意，迟到HTTP不复活旧身份结果。

实现主要在 [candidate_ai.py](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/candidate_ai.py)、[输出合同](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/candidate_ai_contract.py)、[追加账本](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/candidate_ai_models.py)、[SDK](E:/Mix/project/tire-info-manage-sys/packages/api-client/src/candidate-ai.ts)与[React面板](E:/Mix/project/tire-info-manage-sys/apps/web/components/candidate-ai.tsx)，并修改021迁移和必要的通用入口。正常库未启动／应用021；PostgreSQL运行时仍待独立验收。

R70测试事实摘录门及R71／R74专业材料`provider_use=false/export=false`保持；本轮不读取TestEvent或专业材料外发。C规格投影经独立逐来源许可与个人同意可发送，不应把上述专业材料限制泛化为所有用途禁止。沿用同cookie会话聚合语义，额外actor核验和浏览器owner失效不构成全站服务器账户隔离。

## 最终验证与阶段身份

以下各阶段独立计数，不能相加为完整套件、真实模型或发布验收。

| 阶段 | 实际结果与范围 |
|---|---|
| Root最终相关回归 | 275 passed，exit0，274输入首尾稳定；13模块覆盖C、通用AI／rule／stream、device提交／读取、reports、R70、R69、R75及迁移。正常DB／外网／child禁止尝试均0，Windows内部socketpair437次单列 |
| 最终独立反例 | 61 passed，0 fail／error／skip，源码首尾一致；实际私库ASGI＋受控adapter，禁止三类尝试均0、内部socketpair104次；不是无应用／无数据库执行 |
| SDK与构建 | SDK59项、workspace typecheck、Web／desktop／mobile三端前端build均exit0；后两者仅Vite资产，保留大chunk警告，不代表Rust／Android／设备验收。B／R69 SDK旧回归另有日志 |
| 实际wire | 最终后端私库HTTP生成blocked／prepare／authorization／detail公开样本，id与key GET一致；controlled调用1次，源码首尾稳定，禁止三类尝试均0、内部socketpair2次 |
| 桌面React | 15项通过，实际viewport1447×904；缺许可零调用、grant后需重新准备、同意前禁提交、问题变化清空、受控一次调用、分区／不足、GET恢复和撤销后stale |
| 手机React | 390×844与320×740各10项，实际emulation视口；主要验证布局、授权预览与已有历史读取，不声称两个独立完整提交流程 |
| 身份失效与迟到HTTP | 5项通过，真实私库GET响应在浏览器内延迟；owner失效清空、迟到结果不复活、重新验证无旧准备，未再调模型 |
| 浏览器运行终态 | stopped.json确认shutdown_complete、251输入首尾稳定；controlled调用1、real调用0，外网／child／正常DB禁止尝试0，loopback监听1、内部socketpair13 |

Root最终回执：[result.json](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/targets-8a84ea782d8f43ec9108db4e11970ffb/result.json)，同目录`pytest.log`。独立[审查报告](E:/Mix/project/tire-info-manage-sys/.artifacts/review-r77-17ae00dcc9e142c7977124358586f4ae/REVIEW.md)与[result.json](E:/Mix/project/tire-info-manage-sys/.artifacts/review-r77-17ae00dcc9e142c7977124358586f4ae/result.json)；后者SHA `e415a3ef9b3cfe7e900d7459dedfd710ae824837c3dbb1420c3b3c1e95480cfc`。

前端[最终回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-frontend-8f2534ad4d814951b28055c4c3898838/verification-frontend-final.json)、[10项源码绑定](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-frontend-8f2534ad4d814951b28055c4c3898838/source-hashes-final.json)及[wire接收检查](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-frontend-8f2534ad4d814951b28055c4c3898838/wire-samples-validation.json)。wire接收检查绑定早阶段实际HTTP样本，不能称其绑定最终后端字节；早阶段样本及回执保留。最终生产源码另生成[wire回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/wire-60d14e02afb841c49967ba2c6a4335b5/receipt.json)，最终浏览器使用最终后端。该wire的274输入在执行首尾一致，生产文件均与最终字节相同，但之后迁移测试夹具和`run_targets.py`有修改；索引明确这两项阶段差异，不将wire列为当前全部输入稳定组。前端旧回执中的pending是封存当时状态，后补检查另立回执，不覆盖旧文件。

浏览器：[桌面](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-browser-final-70cadbc0f62044e1844bd8869cea881f/desktop-01.json)、[390px](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-browser-final-70cadbc0f62044e1844bd8869cea881f/mobile-390-final.json)、[320px](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-browser-final-70cadbc0f62044e1844bd8869cea881f/mobile-320-final.json)、[身份失效](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-browser-final-70cadbc0f62044e1844bd8869cea881f/owner-final-02.json)、[关闭回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-browser-final-70cadbc0f62044e1844bd8869cea881f/stopped.json)。桌面与手机截图亦留在该目录，私库／cookie／认证响应／凭据不列公开证据。

## 独立发现、修补与失败保留

独立审查实测两条历史漏洞：篡改completion理由文本、无claim克隆请求后，专用id GET原先仍返回200。已补claim／request／consent／body关联及从冻结理由重渲的完整answer核验；最终六类损坏覆盖id GET、key GET和同键POST。原红回执保留于`.artifacts/review-r77-a3a71e6e42f34750878343ee9ffbe361/result.json`，原红仅实测id GET，不能冒称三入口当时都执行过红例。

两项隔离回归前置已修正，未改产品对象仓库或Parser预算：

1. 旧迁移测试pre016夹具不应包含后续新表。`test_interest_migration.NEW_TABLES`从6表扩至016–021全部13表；旧schema、旧业务行及幂等保全断言保持。相关16项通过，最终275亦覆盖。该测试SHA `ceb8ef1624dd19f93df714c3ddb3d1f8106b647e7c289bc9bd9d9166abdaab2c`。
2. 初始Root私根过长导致真实对象写入失败。[定向Windows探针](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/windows-object-path-probe.json)观察目标216字符成功、268字符WinError3；目标runner改用短GUID私根后最终275通过。只修验证路径，不声称已修复产品普遍长路径能力；Parser仍8秒墙钟／5秒CPU／384MiB／并发2。

早期目标阶段全部保留，不能合并、删除或一律写成产品已确认回归；准确回执绑定见本轮`validation-index.json`：

| 本轮根下阶段目录 | 当时实际结果与限制 |
|---|---|
| `targets-ee818db23c454983a4e7104e0478d5b8` | 8F，读取不存在的revision fingerprint；不是最终结果 |
| `targets-c75c197eb4594d2688b77837fa6e5910` | collection失败，独立反例要求专用harness；后由独立runner执行 |
| `targets-19ae2a1f5a4c49c3afb9ac9d9322865c` | 37F／182P／124E，源码不稳，WinError5、对象写入与私根护栏问题；normal_database_attempts有14次被拒绝，不称该阶段守卫全0或正常库已使用 |
| `targets-35b9e4f6b6e64badb48de0d9e76ec078` | 273P／2F：长路径导出503与伪pre016 schema；补修后最终275覆盖两项 |

首次沙盒浏览器虽ready，宿主／Chrome访问超时，未取得验收，按精确PID关闭并保留[UNVERIFIED说明](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-browser-stage-359f88a8942d4ccc834846214df2c94b/UNVERIFIED.md)。另建宿主GUID私根才得到上表结果。

首次`mobile-390-01.json`实际宽501，不算390验收，后改真实emulation；`owner-final.json`因performance buffer缺原key而0项，不算通过。最终owner检查只从本轮私库读幂等key，不读取或公开cookie／密码。MCP文件路径工具拒绝项目root后改inline执行并保存返回JSON；截图超单次64KB传输限制后分段保存原始图像字节，不改图片内容。

Next隔离dev把`apps/web/next-env.d.ts`生成引用改到临时目录。先核原始HEAD blob，因LF／CRLF不符而拒绝写入；随后核当前`core.autocrlf=true`过滤后的HEAD字节与R77基线完全相同、且当前差异仅临时引用，才原字节恢复。[恢复回执](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/generated-restoration.json)记录首拒与最终恢复；未reset／checkout他人dirty。

## 来源、保全与接续

本轮另有[三条Zenodo研究观察](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/source-research.md)，没有新增原件捕获、存储／Provider许可或Golden。不能从Open标记、研究编号、同名或尺寸猜完整SKU。R74真实公开论文仍是精确身份未知，R76真人0／真实精确SKU正例0／`release_gate=inconclusive`／`wrong_merge_count=null`保持。

修改前已核R76清单1506项：979源码、392展开dirty、31文档、100证据、4配置。R76清单SHA `012ace3ba222adba598d62a1670cad83eee5546459cd1e9c1ec71658600a703f`固定。新[机器清单](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/verification-final.json)及[验证索引](E:/Mix/project/tire-info-manage-sys/.artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/validation-index.json)绑定本轮最终源码、文档、配置和显式公开证据；以实际封存与根外独立终审为准。旧dirty、历史证据及原始需求字节保全，清单不代替完整文件归档。交接须带工作树和列明证据，私有数据另行本机保全。

静态封存检查额外核最终计数、before／after、禁止尝试、SDK样本与真实视口，不能仅信索引的passed声明。首次预检把浏览器controlled调用记录列表误当整数，断言拒绝且未创建FINAL；校验器改为严格列表长度及body hash／purpose校验，原回执不改。

已关闭本轮自有API／Next与验证页面；正常API／DB、真实Provider、原生设备未运行，未重跑完整API／Worker套件，未提交／推送。风险R-017仍open-roadmap；旧平台、部署密钥、全站账户与V1发布门风险不随本轮关闭。

接续顺序：自主核合法真实专业原件及完整身份→补独立真人审核与代表性Golden→准备真实Responses的逐源许可、最小正文、模型／预算与明确验收标准→继续完整专业性能C及V1发布Gate。无需重做R72／R74捕获工程、R75 B或R76评估器；缺证据继续unknown，不为关闭Goal推断事实。

静态封存复核命令（仓库根、PowerShell7，不导入应用、不连接数据库）：

```powershell
& apps/api/.venv/Scripts/python.exe -X utf8 -B .artifacts/r77-candidate-ai-2c226677e1eb429b87ac9f3e526b6167/seal_current.py --audit
```
