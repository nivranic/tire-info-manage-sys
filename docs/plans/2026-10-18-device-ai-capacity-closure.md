# 设备 AI 容量边界与多成员闭包 Implementation Plan

**Goal:** 补齐 R-005 的真实8MiB字节边界、完整包与多成员闭包跨语言权威向量，修复验证中证实的排序分歧，保持既有协议和权限。

**Architecture:** 新增独立合成向量集，通过有长度/SHA约束的紧凑配方在各端内存展开实际边界字节；以明确规范、人工可查canonical literal及独立标准库SHA计算建立预期。Python/TS验证已实现的完整投影/闭包；Rust/Java验证当前实际支持的parser及selection/context/preview指纹，不声明原生完整闭包投影。

**Tech Stack:** Python pytest、Node/TypeScript现有测试入口、Rust cargo test、Java JVM/JUnit；不启动数据库服务、Provider或设备。

状态：实施合同已冻结，尚未验收。沿用用户持续实施与ultra协作要求；本会话直接实施，保留现有dirty，不提交、推送或创建仅含HEAD的替代树。使用brainstorming/writing-plans技能。新证据根：`.artifacts/r73-e1-coverage-1448d1d36249471eaba4d16092b65a93`。

验收前勘误：独立需求审查和native审查指出，完整投影包含原包`archive.sha256`，因此包空白变化会连带改变完整投影摘要。第4.4项已按该既有合同纠正，未修改产品或旧expected；初稿原字节保存在本轮证据根`plan-before-archive-hash-correction.md`。

## 1. 依据与范围

- 原需求的设备离线证据、精确证据重开、安全体积门、跨平台一致性与合同回归要求；ADR-2026-063明确保留的R-005欠项。
- R72封存已现场核对907源码、313展开dirty、24文档、156证据、4配置；HEAD保持`4d0ef60fa2240146113a3fac172759c665cf339f`。旧回执不可改写。
- 8MiB指完整未加密package的原始UTF-8 JSON body，包含envelope与空白；不是AST大小、canonical投影、DeviceAIValue大小、HTTP帧或密文。上限为8,388,608 bytes。先检查原始字节限额，再处理BOM/UTF-8/JSON。
- 原`packages/domain-types/fixtures/device-ai-v1/`的127文件、provenance、所有旧pins/expected与两份E1绑定源码保持原字节。新增独立fixture版本，不把旧输入换成新生成输入。
- 不修改prepare12键、consent6键、submission4键，不放开mixed/personal/test_event，不提升restricted材料权限。保留selector/approved各1..6、pack成员200/文档4000、44k投影和48k出站限制以及既有Parser预算。

## 2. 设计选择

选用“紧凑受管理配方→各端真实展开”的方式：每次执行都构造实际N-1/N/N+1字节，校验展开长度与SHA后调用生产decoder。相较提交多份8MiB空白blob，它能清楚展示边界来源并减少仓库冗余。仅缩小测试上限或检查`expected_byte_count`字段不能覆盖本次要求；原生parser通过也不能冒称原生完整投影通过。

独立oracle不得调用待测parser、canonicalizer、projector或fingerprint函数计算expected。配方的canonical literal、结构和顺序逐项解释，SHA由标准库及独立语言实现复核。完整包派生必须明确是人工追加JSON空白的合成输入，不能声称producer原本产生过该8MiB包。

## 3. 所有权与文件

所有worker均不独占整个代码库，不得撤销他人修改；需要跨所有权变动先协调。

| Owner | 负责文件/责任 |
|---|---|
| corpus ultra | 新`packages/domain-types/fixtures/device-ai-capacity-v1/`及其中README、属性、manifest、容量配方、完整包和闭包样本；Python新fixture loader及`apps/api/tests/test_device_ai_capacity.py`；TS新loader及`packages/api-client/tests/device-ai/capacity-fixtures.mts`；必要的现有TS helper最小修复与测试入口注册 |
| wire ultra | `apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile/DeviceAiHost.java`中已证实闭包排序的最小修复；新Java容量/闭包fixture测试和loader；新Rust`apps/desktop/src-tauri/tests/device_ai_capacity_parity.rs`及独立support；native目标运行与回执 |
| Root | 独立oracle脚本` scripts/verify_device_ai_capacity_oracle.py`、本计划、集成/反例审查、最终报告/交接/风险状态及新版本清单；所有现有文档在验证终态后才更新 |

具体新辅助文件命名可按语言现有布局调整并在报告列明，不得借机重构旧loader或更新旧pins。fixture结构先在协作消息精确对齐，生产源码变化必须有红例。

## 4. 容量及完整包验收

1. 默认生产上限实跑ASCII JSON的N-1、N、N+1；前两者完整成功，后者容量错误。解析通过的样本canonical literal相同、raw SHA不同。
2. 含非BMP Unicode的有效JSON在N、N+1实跑，按UTF-8字节而非UTF-16字符数计数；canonical literal和展开SHA固定。
3. N以内BOM与N+1 BOM、无效UTF-8形成错误优先级对照：超限必须先报容量错误，不因语法或编码问题绕过体积门。
4. 一份合法、合成的完整package加空白展开到边界；包AST与Python/TS投影的业务observations/material保持等价，原始包SHA及byte_count如实不同。完整投影包含`archive.sha256`，故canonical/projection摘要应随真实原包绑定改变，逐个边界包固定独立预期；除该原包SHA绑定外的投影内容保持相同。超限完整包拒绝。私有archive/体积核验若属于该路径，直接测当前入口，不启动main或正常库。
5. 每端均实核配方/文件及展开bytes的长度和SHA；缺失、损坏、配方/manifest不一致失败。不能只输出四语言对拍结果而不证明消费了同一输入。

## 5. 多成员闭包与排序验收

1. 至少两个可区分的tire成员，真实requested→依赖闭包扩展；覆盖完整selector身份字段（包含document/index/reference）。Python/TS的resolved精确集合与投影由同一组权威预期对拍。
2. selected保留请求序；resolved_closure按member_key升序。固定selected的情况下反转approved/closure输入不应改变规范要求无序集合的指纹；反转selected应按规范改变对应指纹。
3. 缺失/重复/超集、错误document/index/reference、跨variant、非tire及restricted等适用反例明确拒绝；不跳过真实闭包依赖计算或把superset接受为成功。
4. Java当前`localPreviewFingerprint`未排序closure的疑点先取得真实红例；再修最小排序逻辑。不得改expected使Java旧行为通过。
5. TS context helper的canonical UTF-8排序疑点，仅在规范适用且当前函数实际接受该输入时建立U+E000/U+10000红例并修复；若只能依赖未实现的未来协议形状，保留未证实风险，不扩大DTO/权限以制造可测输入。
6. Rust/Java目前native preview仅支持single_observation+单tire；保留unsupported门禁。其多成员指纹纯helper对拍必须与Python/TS完整闭包投影验证分别报告。

## 6. 执行与验证顺序

1. 冻结共同fixture schema及独立oracle来源，写入新fixture版本；以manifest完整性门保护跨语言输入，旧127输入逐SHA保全。
2. 针对Java及适用TS疑点运行最小真实红例，保存未修产品源码SHA、命令、exit与原始失败。其余目标验证可独立并行，不混算。
3. 仅修已证实的生产排序问题；Python/TS与Rust/Java各自实跑新向量和直接受影响旧回归，记录前后源码SHA。
4. Root用独立oracle核canonical literal、顺序、raw展开与摘要；检查文件完整性反例。工作区typecheck仅在TS产品改变时执行。没有UI改动不重跑浏览器、前端构建或原生设备流程。
5. Windows沙盒若阻止既有安全对象硬链接，先查实际副作用，再以相同私库/无外联/无子进程护栏申请宿主执行，不削弱存储或预算门。Java/Rust依赖仅用已安装/缓存；若确需新外部下载，先确认本轮实际需求与授权。
6. 所有运行结束后再写终态报告、风险及交接，保存失败阶段。新最终清单绑定当前源码/dirty/文档/证据，旧R72及更早封存原字节保留。独立最终审计置于根外。

目标命令由各owner按新增入口列出并实测；Python使用`apps/api/.venv/Scripts/python.exe -X utf8 -B -m pytest ...`及私有环境护栏；Node使用现有`--experimental-transform-types`及禁止`.artifacts`读取hook；Rust使用`cargo test --offline --test device_ai_capacity_parity`；Java使用项目既有JDK/JUnit工具链的限定类。不得把此处计划命令当作已执行结果。

## 7. 终态与保留义务

R-005仅在真实边界向量、完整包、适用多成员闭包及四端摘要消费均有权威预期与实际结果时按精确范围关闭；未覆盖层级保留明确欠项。任何产品红例必须修复或如实开放。

本轮不替代真实专业材料/许可、代表性人工Golden、同场条件化解释B、专用AI推荐C、Responses真实端点、正常库迁移、macOS/iOS/物理设备、生产IAM或完整V1的10项Gate。缺少当前素材不取消这些需求。原Goal保持active。
