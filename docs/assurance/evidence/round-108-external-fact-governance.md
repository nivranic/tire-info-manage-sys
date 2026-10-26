# R108：外部结构化事实许可治理 G1b 与 025 合成迁移补验

2026-10-21。**G1b在受审合成私库范围通过：v6实际20主测试/8个subtests；另一次025迁移补验2主测试/0subtests。** Root分别独核，两批合计22个唯一主测试、总8个subtests，不能记成一次22项。R1–R5均在主测试开始前失败，原回执与未知边界保留。正常DB、完整历史库023→024→025升级、真实PG、生产许可、G2与完整V1仍未验收；provider/export=false，完整V1 active。

## 1. 已实施及冻结范围

已实施两张用途专用追加表、受控当前 head、真实本机管理员认证、独立 CLI preview/approve/restrict/withdraw、规范 UUID 幂等、真实业务观察绑定与同事务审计。没有新增 HTTP 路由、外部事实 API、SDK、UI、Provider、fallback 或材料权限通路。

- 条款表保存 1–262144 字节 UTF-8 声明，按 SHA-256 去重；不是任意对象归档。
- 修订台账保存完整 G1a 记录、实际 actor ID/用户名快照、观察回执、预览与提交前件、幂等和审计映射。无可变 head 表；当前 head 从受控库内完整连续链派生。
- 批准前核既有 Snapshot 的 source/body UTF-8 hash/parser，并核 accepted Verification→QueryRun 的 query 与 Parser identity 一致性；不补采集、不创建假观察。现有 body 摘要不等于原始 HTTP 字节证明。
- 管理读显示 G1a applicability/reason；过期 approved 仍保留历史状态，但显示 not_applicable。限制/撤回不依赖许可当前有效或重新核全部业务 body；withdrawn 是同 grant 终态。旧 approve UUID 重放返回历史事件及当前 withdrawn，不复活旧批准。
- 非 withdraw 最多写至 255，修订 256 保留给 withdraw。相同内容与相同原因拒绝 no_changes；不同完整复核原因可形成新 approve 修订。
- 管理 CLI 只使用显式绝对私库文件与 TTY/getpass，调用既有真实密码校验；事务内复查角色及凭证。SQLite BEGIN IMMEDIATE，PG advisory lock 加管理员行 FOR UPDATE；PG 尚无真实执行证据。
- 普通命令不初始化/迁移。显式 init-private 在 offline 确认、024 结构/版本及连接主文件核对后，先写全新备份、显式关闭两 backup 连接并流式核 hash，再只安装 025。测试 fixture 是新的合成 current024 形状，调用未 patch 的 classifier；不是 023→024 完整历史迁移验收。

[实施 freeze-v1](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-contract-20261021/implementation-freeze-v1.json) SHA `892562c101d079109b268be13fbf2d47b03cdc8b8094a3cc5533c39339fcadab`，固定14份关键产品/测试/注册/文档输入，Root `d79939`实核匹配。随后[freeze-v2](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-contract-20261021/implementation-freeze-v2.json) SHA `76d31ad05ea3c7dc2c831f16c270df30f487bbea91af34b92e55ba931236b875`只更新治理产品与对应测试：在初次 `_seal` 验证处补捕获RecursionError，深层parser_version使preview/append均返回request_invalid且行数不变；不提高递归上限。主测试由19增为20，新增项在v6实际通过。v1产品与测试已按CreateNew保全。14项是关键输入快照，不是完整传递依赖闭包；其中plan/usage维持冻结时点，当前状态以本报告和HANDOFF为入口。

Root 授权的既有文件最小修改为 db.py 注册、migrations.py 025、version_registry.py 追加版本、historical_migration_support.py 两表独立字面量触发器合同。G1a 产品 SHA `f473bfc5f83379802a1d6493ec48d6bd778fb038622b4a2c8a46e95b5965721d`、测试 SHA `f6aa417bfea8f14159d3c82dffe01da0fd35a3b98225b4de38c4c9997971933d` 与 HANDOFF 114286B/SHA `3ea90158c012717e6b45e8c7e49e162340a3e89f42e720b0090a23bab50b7e37` 保持。

[静态代码审查](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-review-20261021/CODE-REVIEW.md)推动两表改为WITHOUT ROWID，关闭隐藏rowid替换缺口；v6的隐藏rowid与原生SQL不可变向量已在合成SQLite通过。PG管理员复查新增with_for_update，PG模型/DDL编译向量已运行通过，但没有连接真实PG验证锁语义。CLI backup两连接改为显式closing、摘要固定1 MiB chunk；v6实际通过精确preinit备份与失败时两连接关闭/备份保留向量。这些结果不外推至所有系统句柄或正常库。受影响文件git diff --check已通过，仅有既有LF/CRLF提示。

## 2. 运行时来源与早期 stdlib probe

官方 CPython 3.14.8 Windows x64 ZIP 已在独立 artifact 目录静态准备；官方 release manifest 与 ZIP 摘要核对、PE 架构核对不代表代码签名或完整证书链验证。旧 .venv、旧运行时、stdlib 磁盘内容和旧 Guard 保持。

3.14 v1 probe 因静态作用域不匹配而未正式运行，不记为运行失败或成功。v2 是独立修订；runtime worker 唯一运行工具 `1087e5` 实际 exit0，run `probe-v2-run-5c0b5ef6570447fcbec41e2ba75cff77` 自然退出，无 timeout/forced stop。Root 是该运行批准者与后续独核者，不将 worker 执行改记为 Root 执行。

[probe-v2 原始 receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/python-x64-runtime-20261021/probe-v2-run-5c0b5ef6570447fcbec41e2ba75cff77/receipt.json) SHA `b1950b0748e60c48ed57a4e1afc4a3c2de4c70925e946bcabaaecc6ebc807672`：pointer64、version_expected、machine_x64 均 true；允许的 hostname 查询 1，denied child/network/sqlite 均 0；stdout329B/stderr0。Root `3ca0f5` 另实核 42 项关键 pins 全匹配。

这证明固定独立解释器的 stdlib platform.machine 路径在本次受限 probe 内完成，不证明 SQLAlchemy/G1b/应用包/main/TestClient/真实 backend 恢复，更不修复或倒填旧 WMI/C2 run。源码静查中 SQLAlchemy 2.0.55 与 2.0.38 均调用 machine；单纯说“换回 2.0 即规避”没有依据。42 项不是完整运行时闭包，Python hook 不是 OS 隔离；无捕获内存硬上限与全部句柄/瞬时行为的完整证明。

## 3. 匹配依赖：静态来源与限定导入范围

为独立 CPython 3.14.8 win_amd64 准备 12 包、691 个提取文件，共 18764932 字节。Pydantic core/greenlet 使用 cp314 x64 wheel，SQLAlchemy 使用 2.0.55 pure wheel；没有复制 cp312 原生扩展，没有执行 pip、包安装器或 .pth。fastapi、starlette 等依赖在此只是目标模块所需依赖，不是服务启动许可。

[package-manifest.json](E:/Mix/project/tire-info-manage-sys/.artifacts/python-x64-runtime-20261021/static-dependencies-v1/package-manifest.json) SHA `b2fa3afcd9aa2cd757f0b35a7ba0632029902a3a8b6cd2ffe7524d6320b3a3af`；[extracted-files.json](E:/Mix/project/tire-info-manage-sys/.artifacts/python-x64-runtime-20261021/static-dependencies-v1/extracted-files.json) SHA `9713053f94a331b5f11aba9a09a96edf4af89a7f214ac6f75acfbe1571913f8a`。Root `84c6e7` 已逐一实核 12 份 metadata/wheel hash 与全部 691 文件匹配。依赖 v1 准备曾在两份精确静态成员预检处停止；v2 只允许该两成员并完成解包，不抹除 v1 停点，也没有运行自带 cmd/header。

这些manifest证明来源、元数据、文件完整性与静态架构。后续v6及迁移补验另提供受审工装下目标模块的真实导入/功能证据；未导入main、运行pytest或启动完整服务，不能据此接受整个依赖环境。

## 4. 历次正式运行与插桩边界

R1–R5目标仅 `test_external_fact_governance`、`test_external_fact_governance_cli` 两个直接unittest：当时19主向量，预期8个subtests单独计数；v2冻结新增深层输入后，v6实际目标为20主向量。覆盖只读预览、真实密码与角色复查、旧 UUID 撤回后重放、绑定失败、双线程同 revision 竞争、context 持锁、过期/截止/未来有效期停止、审计损坏、原子回滚、原生 SQL 及隐藏 rowid 拒绝、容量、PG DDL、CLI 安全输出、025 安装与失败资源关闭。context/withdraw 向量仅检查启动事件、future 当时未完成及后续撤回；不能声称完整多进程/PG 并发盘点。

R1 唯一正式工具 `9e87aa` 实际 exit1，9.56 秒结束且无持续 session；新 run `run-9dd94dc74266479ca8af616a7b02e3f7` 原始 [receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-verification-20261021/run-9dd94dc74266479ca8af616a7b02e3f7/receipt.json) SHA `ade2486e1c41ee2c4a6e3a5e7658ee8af8d9323ea2654f1c3a431a23dd0ccc7c`，status=failed、child_exit=1。

实际 tests_started/tests_completed/succeeded 均 0，subtests.total=0；因此 failures/errors/skips 等为 0 不代表主向量通过。issues 只有 harness_error/AuditDenied，安全帧为 `apps/api/tests/test_external_fact_governance.py:13`，位于 SQLAlchemy 导入。denied.files=1；child/import/network/sqlite 其他 denied 均 0。首次拒绝的实际路径、事件与下游完整栈未记录，不能猜作 NUL、WMI 或回填旧失败原因。

hostname_queries=1，sqlite_connections=0；fresh/remaining_case_directories 均 0，未开始合成私库 case。receipt 记录 761 关键输入首尾一致（manifest SHA `ad8883ba4f098e4a418f5c8b1451c535561009af63424e675ab260755d998e48`），不是完整 import closure；stdout2839B/stderr0，child_natural_exit=true、timed_out=false、forced_stop=false，无捕获内存硬上限。自然 child 退出不证明全部系统句柄关闭。

Root `e2c3ab` 实际 exit0，已独核 R1 receipt 摘要与全部 761 pins 匹配。Root 另在 R1 前以 `ea3a84` 核 auth.py/domain.py/query_filters.py/vehicle_binary_migration.py/__init__.py 五份支持源码，R1 后由 `e2c3ab` 比较均 unchanged；这属于补充首尾观察，不扩称完整依赖闭包或原子加载字节。Root 独核同样未取得实际 file event/path 身份，仍为 unknown，不借独核补造原回执未记录的诊断。

R2 使用增加首次拒绝角色/有界栈的独立 v2 工装，由 verification worker 以工具 `183ff4` 实际运行，exit1；Root `f59b61` 已独核本次失败。新 [receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-verification-20261021/run-e5fd556a37254728a1da379a416a5871/receipt.json) SHA `6f3b2767a550c5446df91016cf7129bd2fbf659a73977040ab9d035ddec62238`。实际主测试 started/completed/succeeded=0、subtests=0，files denied=1，其余 denied=0；hostname1、SQLite连接0、fresh/remaining case目录0。761关键输入首尾一致，stdout3741B/stderr0，child自然exit1、无timeout/force。

R2 首次文件拒绝实录为 open / write / null-device（NUL），有界栈经过 SQLAlchemy compat、platform 的 ver 回退及 subprocess；拒绝发生在该路径，不能写成已经创建子进程。这个具体身份仅属于 R2，不回填 R1 的 unknown，也不推定旧 WMI/C2 根因。其后v3另审并执行局部PermissionError拒绝适配，结果见下，不回写R1/R2。两份原回执、工装与输入历史保持。

受审 SQLite 工装仅允许局部包装 sqlite3.connect 与 sqlite3.dbapi2.connect：调用原始真实 connect、保留 factory 与原 args，在原 connect 成功完成后装 set_authorizer；安装失败须关闭刚创建连接。它不模拟 SQL/产品结果，不替换 platform.machine，不修改 stdlib 磁盘，不扩旧 WMI Guard，也不把局部插桩说成原生无插桩验收。最终通过与否须以经 Root 核定的工装源码、固定输入和实际 receipt 判定。

## 4.1 R3–R5 仍在启动测试前停止

三轮分别保留自己的真实失败，均 started/completed/succeeded=0、subtests=0，hostname=1、SQLite连接事件=0、fresh/remaining目录=0，761关键输入首尾一致；child均自然exit1，未超时或强停，stderr均0。

| 尝试 | 原始回执与SHA-256 | 本轮实际观察 | Root独核 |
| --- | --- | --- | --- |
| R3 | [run-665fc6c251554dd1a7c8e0fab7354061](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-verification-20261021/run-665fc6c251554dd1a7c8e0fab7354061/receipt.json)，ba7d8c08c92a773c80a624babc3e303c6a70220bc23580bb2238fb4eb547f542 | 三次精确NUL请求均被拒并适配为PermissionError，files3=expected3；随后OSError，未记录更深身份，stdout3810B。 | 137058 |
| R4 | [run-59916e8f7ccc4a51a544904f5fb4afd5](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-verification-20261021/run-59916e8f7ccc4a51a544904f5fb4afd5/receipt.json)，97c7d266ed736b62d76ba56334ff76221d9126174d0c92746c9704db3dc8a43f | files3=expected3；新增有界诊断到SQLAlchemy concurrency→asyncio/windows_events，OSError errno/winerror均10106，stdout4383B。 | 7757d2 |
| R5 | [run-81fcdd928e78430aa53b88947c8cca68](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-verification-20261021/run-81fcdd928e78430aa53b88947c8cca68/receipt.json)，e0d57039022997833ceb517d362fa572461dbc1f9449098fc4a82d10af940067 | 受控加入SYSTEMROOT后越过前一观察点；Pydantic自动插件发现→importlib.metadata/pathlib路径被Guard拒绝，files4而expected3，stdout5427B。 | c25cb4 |

三轮child/import/network/sqlite其他拒绝均0。R5的后续观察不证明R4或旧WMI/C2的完整根因；R3未记录的深栈、R1未知文件身份也不补填。三次平台拒绝适配始终保留实际拒绝，没有成功打开NUL或创建该请求的子进程证据。

## 4.2 v6：20主测试、8个subtests在合成私库范围通过

verification worker唯一启动工具 f88cb7，session34598，单次终态poll 2b050f，实际exit0。[v6原始receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-verification-20261021/run-a2b95b747de14f27915131c6a6915a30/receipt.json) SHA-256为9373667042750a9a80978a4e928f95daf2126ed4ff6e52314dd59bc1b8a9dbc7。Root独核工具04153b复算期望、started、completed三组ID均为同一20个唯一值，包含新增深层输入测试；succeeded=20，subtests.total=8，fail/error/skip/expected failure/unexpected success均0，issues=[]。独立终态审阅接受的范围也仅为合成G1b。CLI的TTY/getpass输入由测试注入，使用合成账户执行既有真实密码hash校验；未做真人终端登录。

实际files3=expected_platform_denials3，其他child/import/network/sqlite审计拒绝均0，平台导入窗口已关闭。hostname查询1次，SQLite审计捕获连接事件44次，fresh目录20、remaining0。44是事件次数，不额外宣称每次都完成成功初始化。child自然exit0、无timeout/forced stop，stdout8346B/stderr0。761关键输入在运行首尾一致，Root应用文档前又逐项实hash匹配，并比较额外五份支持源before/current一致；这仍不是完整传递依赖闭包、原子加载字节或所有系统句柄的证明。

v6仅在该独立工装内使用三项精确环境：PROCESSOR_ARCHITECTURE=AMD64、SYSTEMROOT=C:\WINDOWS、PYDANTIC_DISABLE_PLUGINS=__all__。第三项关闭Pydantic自动插件发现，不修改Pydantic或stdlib文件，不恢复正常服务环境。原先局部NUL拒绝适配只在SQLAlchemy导入窗口内、至多三次、精确open参数和固定函数代码对象/模块全局/文件/行号栈均匹配时，抛PermissionError供官方platform路径按OSError处理；不匹配仍硬拒绝，窗口随后关闭。没有替换platform.machine、放宽网络/child或旧Guard。该结果证明受审条件下的目标产品行为，不证明未插桩应用、旧WMI/C2、main/TestClient或正常DB已恢复。

## 4.3 025迁移补验：另一次2主测试、0subtests通过

[迁移补充freeze-v1](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-progress-20261021/migration-supplement-freeze-v1.json) SHA-256为ec9ac16e6443084044fd53da4c7ee90ee2adbb193ade4c7e494c01d09ce36171，固定新迁移模块、最小interest fixture与未改的vehicle文件；创建前已复核G1b freeze-v2全部14份输入保持。freeze里的not_run是冻结时点，不改写为事后结果。

独立verification worker唯一启动工具8709de直接exit0，无session或终态poll；后续e7ae4c只读取回执。新[迁移补验receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-verification-20261021/run-b93d79ac7611401fb84c9c1b34ff71d9/receipt.json)为4364B，SHA-256 ff776d3bf6f68d95cf7fdd4748452cd82ee7bd4b9eb47e726c9c13f125c4e7f4。Root独核aa0f6e确认期望/started/completed均为同一2个唯一ID，succeeded=2、subtests=0，所有fail/error/skip等0、issues=[]；没有重跑前20个G1b测试；独立静态及终态审阅也仅接受本次合成迁移补验范围。

fixture为每项新建的合成current024结构与独立字面量001–024版本账，尚无025表；通过真实migrations.upgrade和显式BEGIN IMMEDIATE检查仅加两表/025版本、旧schema和行保持、两表WITHOUT ROWID、六原生guards、三命名索引、三UNIQUE索引共14个schema对象、FK/integrity与第二次upgrade幂等。另一项在真实025版本INSERT前确认原生schema已存在且driver事务仍活跃，再注入失败；退出事务后完整schema/行/版本快照回到before。它不是历史024备份、023→024迁移或Database.initialize验收。

本次files3=expected3、其他审计拒绝0、平台窗口关闭；hostname1、SQLite审计连接事件2、fresh2/remain0，child自然exit0、无timeout/forced stop，stdout2232B/stderr0。770关键输入运行首尾一致，Root应用文档前实hash全部匹配。它沿用上述三项受控环境、精确平台拒绝适配与SQLite连接插桩，局限也相同。

最终计数是v6的20主/8sub，加本次2主/0sub，分两批覆盖22个唯一主测试、总8个subtests；没有一次执行22项，也没有运行旧20份回归文件。

## 5. 真实权利与未完成边界

[权利研究卡](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-rights-research-20261021/RESEARCH.md)仍只是候选。NHTSA UTQG 已有来源级目录许可标记研究，但实际结构化行/schema、对象/Parser 绑定、地域与排除项未验收。C2 的 Springer CC BY 4.0 与 KIT 出版社版本关系获得 HTML 研究依据，原 PDF/素材 credit line、取件成功、原件摘要和商品 SKU 仍未核。本轮没有 PDF 下载、capture、真实 approval 或事实/成绩创建。

登录、声明字节、SHA 自洽与 applicable 都不能替代法律真实性审核。G1b 本机治理不等于生产 IAM；数据库所有者、直接 DDL/文件替换、可信全库恢复不在该边界内。G2 的具体字段投影、owner/账户作用域、HTTP/DTO/SDK、事实值/精确 SKU、正常 DB、真实 PG、Provider/export、Native/设备及完整 V1 仍分别未验收。原九 facts 与后续路由合同未因本切片自动冻结。

G1b 通过后的最小 G2 建议为“单来源、单受控 grant、精确 variant 的显式 history 观察投影”，目前仅建议，不注册路由或 scope。实施前冻结六项：

1. owner：现有 session 联接会因 logout/清扫失去归属；选择明确的当前可归属范围，或先建立可信持久归属，不猜补旧 owner。
2. grant：服务器选择一个受控 grant，不接受客户端 head，也不跨 grant 拼接许可。
3. 身份：首版建议仅 current/active/complete 精确身份，不作家族或等价扩展。
4. 字段：九 facts 仍是候选；逐项冻结类型、范围、精度、单位、null/缺失与冲突，不照搬内部通用数值范围。
5. HTTP：冻结历史路径、scope、封闭 DTO、错误与公共 citation；旧 key 不增权，无真实获准观察不开放永久空路由。
6. 分页：先裁剪许可/owner/证据再分页，cursor绑定治理窗口，每页复查撤回，不泄漏隐藏计数。

该投影需与许可/身份/owner核验处于同一数据库事务；G1b 当前上下文只 yield policy，后续须最小扩展内部读取上下文。field_evidence 默认核验选择不带 owner，不能当账户授权器。上述仅只读差距复核，未改产品或新增迁移，不依赖 EPREL Key。

025影响的下列20份旧回归文件尚未执行；20是文件数，不是测试数，本轮没有收集pytest case数。新增2项补验不能替代这些回归或证明全套迁移已绿：

```text
test_ai_stream_migration.py; test_candidate_ai.py; test_core.py;
test_device_ai_migration012.py; test_device_ai_migration013.py;
test_external_api.py; test_external_api_review.py; test_identity_migration.py;
test_interest_applicability_review.py; test_interest_migration.py;
test_interest_governance_review.py; test_monitor_conditions.py;
test_offline_migration.py; test_query_fallback_migration49.py;
test_recall_discovery_migration.py; test_schema_startup.py;
test_source_materials.py; test_test_sku_links.py;
test_vehicle_binary_migration.py; test_webhooks.py.
```

## 6. 文档保全与第一后续

[HANDOFF.before.md](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-governance-progress-20261021/HANDOFF.before.md)按 CreateNew 原字节保存 114286B/SHA `3ea90158c012717e6b45e8c7e49e162340a3e89f42e720b0090a23bab50b7e37`；该保全时点主HANDOFF未改。测试前及R1草稿分别以 CreateNew 保全为同目录 round-108.before-r1.md、round-108.before-r2.md，未覆盖历史。draft-source-snapshot-v1.json 与 HANDOFF.prefix.draft.md 保留测试前时点，短前缀仍未应用，不作为当前 R1/R2 状态入口。

第一后续是联合审查旧024迁移的全局metadata路径和vehicle fixture，先收敛回归入口，再推进G2合同。旧024的migrate_sqlite通过全局Base.metadata.create_all只排除其四张目标表；若G1b模型已在收集时注册，可能提前创建无025版本记录的025表/guards。test_vehicle_binary_migration.py约387/405行的两处正常启动断言与严格assert_024_delta须联动评审，不能只放宽为subset断言。本轮未修改该文件或旧024产品/辅助函数，旧20文件仍未跑。

interest fixture仅在NEW_TABLES增加两张025表的独立字面量，已静态核对；test_interest_migration.py未执行。新025补验入口和断言仅覆盖上述合成current024→025增量/幂等/回滚。正常库、历史迁移、完整应用、真实PG与G2仍分别开放；不为补验准备整套服务依赖。

本次运行首尾及Root应用文档前，freeze-v2全部14项与补验770项均实核匹配。文档收口只为HANDOFF新增当前前缀，原114286B必须保留为完整原字节尾文；应用后HANDOFF头部是有意变化，不再声称全部运行pins仍与live相同，其余13份冻结文件保持。plan/usage等冻结快照不改写，所有旧receipt、pins、工装、before与草稿保留。CreateNew新增本次报告before、终稿candidate、前缀candidate与原子替换的非空backup，最终以apply回读核对。未新增运行、连接DB、commit或push。
