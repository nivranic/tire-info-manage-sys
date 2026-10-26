# 第73轮：设备 AI 容量、多成员闭包及跨端指纹补修

**本轮已取得真实8MiB边界、完整包及双成员闭包的限定验证，并修复Java闭包顺序和TypeScript Unicode排序的指纹分歧。最终状态以本轮新清单及独立审计为准；完整V1仍未完成。**

合同见[冻结计划及验收前勘误](../../plans/2026-10-18-device-ai-capacity-closure.md)。R72的907源码、313展开dirty、24文档、156证据及4配置在本轮开始前逐SHA核对一致，旧回执不改写；正常库、真实Provider或设备不参与本轮。

## 交付及业务含义

- Java `localPreviewFingerprint` 对 `resolved_closure` 增加按member_key排序，保留selected请求顺序。实际反序闭包红例取得与规范不同的摘要；同一独立literal在修补后通过。避免相同选择闭包仅因传入顺序而在不同端得到不同的授权绑定指纹。
- TypeScript `deviceContextFingerprint` 将canonical数组的UTF-16文本比较改为实际UTF-8字节比较。当前函数接受的recall边界对象含U+E000/U+10000时产生真实红例，修复后匹配规范。保留原AST，未做JSON.parse重建或丢失number lexeme。
- 新独立受管理目录 `packages/domain-types/fixtures/device-ai-capacity-v1/`，固定manifest与22份文件；原`device-ai-v1`的127文件、旧expected/pins和两份E1绑定核心源码保持原字节。新loader/测试及SDK测试入口分别接入现有语言工作流。
- 10份容量配方在各端内存实际展开成原始bytes，含8,388,607/8,388,608/8,388,609字节、非BMP、BOM/坏UTF-8优先级及空输入；不是缩小MAX或只检查元数据字段。4份正式包用旧合成producer包派生空白，逐个固定真实raw SHA及完整投影literal。
- 17份完整闭包用例中5个成功、12个拒绝；实际不同tire成员A→B依赖展开，保留原reference、document/index、requested/dependency及未选成员，覆盖缺失/重复/超集/错完整selector/非tire/异variant/restricted等。此组只有2成员实扩张，未新覆盖3级链与6/7成员边界。
- Rust/Java只对其现有生产parser及selection/context/preview纯helper消费共享向量；native完整frozen闭包投影继续unsupported。未扩大prepare12/consent6/submission4键、公开selectors/approved≤6、内部成员≤200、44k投影/48k出站或restricted/test_event/mixed/personal边界。

## 独立预期与容量层级

[独立oracle脚本](../../../scripts/verify_device_ai_capacity_oracle.py)仅使用标准库，不导入产品parser/projector/generator。它按书面规范重建5份指纹preimage，核10份真实raw配方与4份正式包；正式投影继承旧受管理canonical literal，只把其中唯一`archive.sha256`替换为对应新包真实SHA。[最终oracle回执](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/oracle-final.json)记录实际结果。

验收前独立需求审查指出初稿“追加空白仍应有相同完整投影SHA”错误：包AST和业务observations/material可相同，但完整投影包含原包SHA，故总摘要必须改变。计划已纠正，初稿原字节留证；未为错误预期修改核心或旧expected。

层级错误分别保留：原始parser超限是`device_ai_package_capacity`；完整投影的超限binding先报`device_ai_metadata_number_invalid`；归档metadata超限先503且对象读取0，客户端expected不匹配另有409。不得为对拍强行统一不同层级的错误码。

独立闭包spec审查用纯标准库逐字段重组5成功literal及12负例条件，95项静态检查通过；这些不是95个产品测试。见[闭包审查](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/requirements-review/closure-spec-6676f62a5cb243e991ece0b68452f4ce.json)。

## 实际验证（分阶段，不相加）

证据根：`.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93`。

| 阶段 | 实际证据及边界 |
|---|---|
| Python新目标 | 最新45项通过，含N-1/N的真实FileObjectStore写入、读回、私有归档与投影；N+1 metadata拒绝/对象读取0；3个GUID私有SQLite。157输入首尾及当前匹配，main未加载，外联/正常库/child护栏0。[最新回执](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/corpus/p-e17fdfc8516343c7b0b940d81ccee7a2/verification.json) |
| Python相关旧回归 | 最新133项通过，157输入稳定；非全量API/Worker。[回执](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/corpus/p-451e315d6a0b45839db1b5906f79969b/verification.json) |
| TypeScript新目标 | 45项通过，159输入稳定；真实生产模块与默认限额，网络/child护栏0。[回执](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/corpus/node-all-87e1600f906745428ab526b5ce7a5bf1/verification.json) |
| TypeScript旧目标 | Host192与decoder34分别通过；package注册后重新执行这两个原目标，最终159输入均匹配。[最终回执](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/corpus/node-regression-53717e7d30e6491981670bcb1ed64f68/verification.json) |
| JVM当前源 | JDK21/javac/JUnitCore新旧110项通过；不等于Android Gradle/设备验收。[native报告](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/native/REPORT.md) |
| Rust目标 | 新capacity6项、旧E1 integration10项（内部含68vectors）及纯Host3项分别通过；新测试rustfmt后另跑通过。不是完整Tauri或系统凭据运行验收。[native阶段清单](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/native/SUMMARY.json) |
| Native完整性补修 | 每次read先核全部22 binding，再核返回文件；两端各增加“未读取projection缺失／同长度损坏”副本反例。补修后的新Java类8/8、Rust target8/8分别通过，124/31份阶段输入当前匹配，rustfmt检查exit0。旧110/6是补修前历史阶段，未作为当前新loader的全量结果。[补修报告与freeze](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/native/integrity-followup-df61cd2678e14decba3a22e0ee723ac9/REPORT.md) |
| 生成器可移植性补修 | 仅7份受管理输入的空checkout，无.artifacts及产品源码，逐字节重生23文件；缺失／损坏人工权威输入在写派生文件前拒绝，护栏0。生成器另由32项source freeze和重生回执绑定，不扩大157项Python运行绑定的含义。[补修报告](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/corpus/generator-portable-9eae30ba2d134b3186154d30f09c75c5/REPORT.md) |
| 工作区类型检查 | `npm run typecheck` exit0，294份相关输入首尾一致；原Web tsbuildinfo按原字节恢复，另两端原不存在的tsbuildinfo终态仍不存在。[回执](../../../.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93/typecheck-664c68c3bfc34677a6279e33dbfb75bd/verification.json) |

独立代码审查提出的native全语料完整性与generator可移植性两项问题均已补修。新阶段回执及当前source freeze在最终清单中分别绑定，原始失败、补修前通过及SUMMARY均保留原字节。各阶段有重叠，不累加为一个未发生的全量结果。

## 失败与修正保留

- Java首次缺Capacitor classpath尚未进入有效产品红例；补齐既有依赖后取得真实反序闭包失败，同literal修复通过。
- Android Gradle在pretest阶段因已有两份embedded Web assets stale被拦截，本轮不改UI/同步资产；改用当前源直接JVM目标验证，不宣称Gradle通过。
- Python runner首次Windows平台元数据探测尝试`cmd /c ver`，被child护栏阻止；只修runner平台数据准备。沙盒真实硬链接WinError5有独立探针；同宿主长261字符路径又出现WinError3，短202字符探针成功。仅缩短私有测试目录，再用相同真实存储与护栏执行通过，未mock对象仓库或放宽预算。
- TypeScript旧回归首阶段与当前仅有package测试入口注册差异；原记录保留，最终用注册后的字节重跑两个原目标，未重跑无关全链。

本轮不启动服务、正常数据库、Provider或设备；原生/Node runner、私库保留取证。R74公开来源研究独立进行，不记为本轮真实专业捕获或浏览器验收。SHA清单标识字节，不是备份归档；未提交、推送或发布。

## 后续完整目标

R-005按已覆盖容量与双成员范围收敛，未覆盖的更广闭包矩阵继续列明；响应/value/citation后续协议及native完整投影不是本轮新增权限。

用户已明确授权agent自行选择真实专业材料及核对许可，不再等待用户指定URL。继续自主寻找满足固定来源许可及robots合同的真实专业报告，完成真实捕获、材料人工核对与代表性精确SKU Golden，然后推进B同场条件化解释/C专用AI推荐。当前有界候选研究尚未成功准入，不把公开可下载、姓名/尺寸或匿名参测对象当作精确SKU证据。

真实Responses/Embeddings质量、正常库020、PG运行、新原生设备、生产IAM/分发、其余来源与全部V1 Gate继续开放，原Goal保持active。最新入口为[交接卡](../../HANDOFF-2026-10-18.md)。
