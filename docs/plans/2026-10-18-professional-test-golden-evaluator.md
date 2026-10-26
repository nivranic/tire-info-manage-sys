# Professional Test Golden Evaluator Implementation Plan（R76）

**Goal:** 为专业 TestEvent→精确 SKU 身份桥及同场候选解释建立独立预期、受管理样本、实际产品输出和可审覆盖统计，避免用合成通过或未知样本的零错链数关闭人工 Golden Gate。

**Architecture:** 新纯 checker 与私有 HTTP 适配器组合，旧 Golden 的 tire／vehicle 及 Parser 发布门保持现行合同。受管理 corpus 保存独立手写输入／预期与许可引用，CLI 提供明确的离线快照核对；真正集成必须从生产 R71／R75 HTTP 当场组装 actual，禁止把两份手造 JSON 比对称为产品验收。

**Tech Stack:** Python、Pydantic、现有私库 FastAPI／SQLite／对象仓库；JSON corpus／CLI。无新表、正常库迁移、模型或前端功能。

状态：设计已冻结，实施与验收尚待完成。沿用 brainstorming 与 writing-plans 收敛设计，依用户持续实施授权在当前 dirty 工作树执行；不再询问是否开工、不另建缺失 dirty 的 checkout，不提交／推送／reset／clean／stash。独立设计审查指出的离线自报、图引用、嵌套类型、错误合并观察优先及分层决策覆盖要求均纳入下方冻结裁决。

## 基线与完整目标

R75最终清单SHA `de94dc725312682f11681deb54041f3bcac6b93213746020041b2461fd212480`；本轮基线 `.artifacts/r76-professional-golden-d7a59579390042afae811c01858321c2/baseline.json` 已核954源码、29文档、80证据、4配置和365展开dirty一致。R74至更早封存保留原字节。

原需求1194行要求人工审核SKU／车型／测试真值，1138／1300行要求Golden错误合并0；本轮工程评估器不代替真人审核或代表性数据。R75 B工程已交付；完整V1、专业真实精确SKU／真人Golden、C专用AI推荐等仍保留目标。

## 选择与边界

采用纯比较器＋实际HTTP适配器，便于让独立预期跨产品版本复核；暂不在旧 Golden 增加 kind，不把实验测试等同 Parser 输入，也不新增持久审核流程／迁移。只保存产品输出快照而无独立期望，无法衡量误关联；只写静态JSON互比也不能证明生产实现。因此工程比较、实际执行证据和人工真值资格分开报告。

样本三档：`synthetic_contract`、`real_source_unknown_or_inadmissible`、`real_source_human_reviewed`。样本自报tier、签名文本、agent审核或两个合成账户不能证明是真人；本轮 `human_truth_qualification` 固定 `pending_external_review`，不实现可自授的人类认证／数字签名系统。即使工程比较通过，缺真实正例／外部人工复核／有效distinct pairs时，release gate仍inconclusive，`wrong_merge_count=null`；已观察错误单列并失败，不能由覆盖不足隐藏。

R74真实原件缺测试尺寸与完整SKU，不能为满足EventPayload填写一个猜测尺寸。其case为`source_review_only`：验证原件／捕获凭据与既有agent文面复核的绑定，结论仅unknown／未进入精确身份产品流程；不伪造R71／R75调用，不计真实正例／真人／distinct覆盖。不得把表3颗粒分类比例改成磨耗率或性能排名。真实来源继续自主查许可／robots，不能以“open”字样等同复制许可或把研究内部T编号当制造商代码。

## 合同必须满足的规则

- case／actual／report外层closed，字符串／整数／布尔严格，UTF-8 JSON入口拒绝重复键、NaN／Infinity、过大／过深输入。完整字段的missing、null、false、0和`"false"`区分；未知不能默认补为false。
- 输入独立完整事件、逐SKU逻辑标签与完整身份、材料定位／许可及少量明确桥操作，不引入可执行脚本／通用动作DSL。预期不得从产品函数、actual、种子helper或错误码推导；动态UUID只作产品引用一致性，不当人类身份真值。
- 对actual逐项核case ID、input SHA、逻辑label→实际variant／快照／事实版本及完整literal身份、事件修订／participant、原件／元数据、完整桥与HTTP请求／响应SHA。不能信任actual自报passed、错误计数或private_http=true来认证真实执行。
- R71成功actual取当前GET完整view；R75必须真正POST。私库运行器在调用过程中直接记录HTTP观察，绑定源码与护栏后调用checker；纯离线比较固定`offline_bound_snapshot`，不声称当前latest、资格或授权。实时输出仍只证明捕获时状态。
- 原始成绩按同一event／revision／participant／metric逐字段核raw_value、单位、协议、方向、条件、来源rank、短证据与定位；保留`-0`／`0`、`38.00`／`38`差异。R75任一排除整次personal=null，映射与coverage明确，禁止跨场重排名或补0。
- actual的case ID集合须精确等于冻结corpus集合，拒绝缺失／重复／额外／替换；不能只核数量。预期正例被全拒绝必须报告错误，未知安全排除不计正确负例或真实正例。
- known distinct-pair必须有两个独立逻辑SKU标签及独立完整身份依据。绑定到同一实际variant或identity时观察为错合并，即使其余字段也失败。无pair／pair未完整检查时总体wrong_merge_count=null，合成已检pair另报，不充人工真值零错误。
- 报告分别显示schema integrity、case coverage、decision/distinct coverage、human truth qualification；按三档列total／completed／passed／failed、正例与未知覆盖、观察到错链／无依据准入／错合并。默认CLI可以成功完成工程核对，但显式要求Golden Gate的模式必须在inconclusive时非零退出，不能把exit0解释成发布通过。

精确模型字段、限制与规范JSON/SHA在冻结前由新`apps/api/tire_api/professional_golden_checks.py`设计模型和本节补充定义，完成独立设计审后冻结；实施终态另写报告，不改冻结字节。

## 文件与所有权

- Backend owner：新`apps/api/tire_api/professional_golden_checks.py`、新`apps/api/tests/test_professional_golden_checks.py`及必要新`professional_golden_support.py`。先写closed模型／红例，冻结后实现纯checker、严格读取与私库产品actual辅助；不得改旧Golden／R71／R75或共享helper。
- Root：新`packages/domain-types/fixtures/professional-test-bridge-v1/`的manifest／cases／README，新`scripts/verify_professional_golden.py`及必要受限运行器、计划／基线／执行验证／报告／交接／最终清单。Manifest固定每文件SHA／size，reader每次先核全体绑定，拒绝路径逃逸和未登记文件；旧corpus/pins不变。
- Independent owner：合同冻结后的新独立review测试与独占GUID证据；不复用生产比较helper生成expected。反例优先伪造人工标签、unknown→false、全拒绝、缺pair、缺／重复／替换case、类型／字段遗漏、旧绑定／ABA、离线冒充实时、跨场和负零改写。
- Research owner：公开来源／许可／robots及实际身份字段只读研究，未取得许可与完整SKU时不登记正例；不镜像全文或误标真人。

所有agent不是唯一工作者，不覆盖他人dirty。暂不做前端UI／模型／正常库，验证范围不因此提升R70／R71等级、Provider或导出用途。材料`provider_use/export`继续false。

## 验证与回退

先在GUID私库和真实对象存储完成生产HTTP两SKU完整正例／排除／身份不足及namespace区分，然后用同一actual调用独立期望checker；独立故意改坏actual检查错误可见，不能只测通过。执行目标pure／集成及旧Golden最小相关回归，公开CLI严格JSON／manifest全体SHA／路径／离线边界验证；没有前端改动不重跑三端构建。

导入main全局app之前清配置／代理／Provider，显式同时设TIRE_DATABASE_URL和DATABASE_URL私库、短GUID object／bundles；禁公网／子进程／正常DB护栏。测试硬链接sandbox拒绝时保留失败，用相同护栏宿主验证，不mock仓库或放宽Parser预算。无真实模型、正常库或原生设备验收。

回退仅按本轮新增文件／差异人工处理，不删除私库／未知数据、不reset整树。失败／修正阶段保留，新终态只绑定真实执行对应源码；证据清单不代替文件与原件备份。完整Goal保持active。

## Closed合同冻结裁决

模型阶段文件SHA `1a3f4de98eb1e52b3f258c0ec40194964bcdf5dbee857fc764b3dbbb02e91a5a`，Root现场复核；该SHA仅绑定补行为前模型，不冒充最终实现。最终实现可增加图校验、计数及报告四门字段；case输入／预期不从实际响应改写。Case schema为`professional-golden-case@1`，actual为`professional-golden-actual@1`。输入6键`mode,event,skus,bridge_attempts,candidate,source_review`；完整EventLiteral实际15字段、VariantLiteral14字段，全部显式。case／actual单文件最多512000B、JSON深度24、最多300案，actual总32MB，失败差异最多100但计数不截断。

固定7案：精确双SKU正例、无材料manual未知、缺run_flat断言、B撤销、同码不同MSPN/EAN命名空间、显式代码冲突、R74原件身份未知。前6案为合成工程输入，末案仅source_review_only；无真实正例或真人合格例。合成PDF含手写身份、事件条件、协议／单位及5条原始成绩短句；小数、负零、缺失、并列和来源名次独立手写，不调用产品推导预期。manifest SHA `d222b70c14dc09584f06590902fd13eac9559ac72e3d1a203adc35c341eb91f2`，8个受管理文件及9个外部绑定（6份受管理合成PDF＋R74原件／捕获JSON／agent复核JSON）。原草案PDF未含成绩短句，独立审阅后在冻结前补充并重绑；旧草案pin不再使用。

actual保存实际DB的完整snapshot_member和identity、完整事件GET、R71 preview／decision／current以及真正R75 POST的完整JSON。case图先校验标签唯一、引用闭合、测量配对唯一、预期attempt集合、合法非自配对和证据引用；HTTP容器角色、method／path／request字段与关键嵌套schema、类型及SHA必须逐项核。错误合并需在其他错误早退之前安全观察，不能被其他schema损坏掩盖。动态UUID只作引用一致性，完整SKU原值另以独立case逐字段比较。

纯比较器统一`evaluation_mode=offline_bound_snapshot`且case result的`private_http_observed=false`，无参数可把存档JSON升级为已认证实测。实际runner独立在当次私库HTTP调用过程中构造actual并另存执行回执；两者一起证明限定调用时点，不永久证明latest／授权或真人。所有tier分别报告case、known／checked link、positive／unknown和known／checked distinct覆盖。外部真人资格固定pending、release gate=inconclusive、wrong_merge_count=null；已观察错链／无依据准入／错合并令工程state failed。CLI默认以工程核对结果退出，`--require-golden-gate`遇inconclusive非零。
