# R98 二进制审批接线执行卡

更新：2026-10-21。状态：R98 SDK、UI 与 Native 产品接线已实施；专项 checks、Java 纯 policy 与新增 build0092 五阶段已通过。HTTP0161 的 1440/390/320px 真实浏览器各 175 断言及双树自然 cleanup 已由 Root 独核。0131/0141/0151 历史红灯保留。Rust vendor 接线及固定 linker 已应用，但两次正式 run 均在首阶段编译被受管后代门拒绝，0 completed phase、0 exact test pass；本批明确停在两红。NHTSA aging 与 UTQG 各一次正式材料 POST 均业务失败。R98 未封存、无 seal、不称 close，完整 V1 保持 active。

## 已完成的前置条件

R97 只封存 Task0 后端切片。新边界 25 项与兼容 95 项全部通过，正式 parser 子进程 174 个均正常退出；早期失败和不完整诊断仍保留。Root 于 2026-10-21 00:09:56 +08:00 独核 174 项文件绑定、694 个当前源码输入无漂移，旧 HANDOFF 尾文 86568 字节完整保留。

- 后端报告：`docs/assurance/evidence/round-97-binary-review-boundary.md`。
- 唯一 R97 seal：`.artifacts/r97-close-8de9f8b8091148d8949f3aaa49e68706/verification-final.json`，SHA-256 `62a4b392e3d20a6a507b882aa11179e9c0f9a4f5beb9eef28f5aef19d3dd92d4`。
- Root 最终独核：`.artifacts/r97-root-audit-20261021/final-seal-readback.json`。
- R98 变更开始后，不能把以上时点的“对 live 无漂移”泛化为后续新源码状态；本轮分别保存 before 与新验证输入。

## 实施依据与所有权

复用原计划 `2026-10-20-binary-quarantine-review-ui.md` 及其 `-addendum.md`；增补 SHA-256 为 `fb890a66bf1fa144be6048ba94a358dc2156b2d1e9c7bd532982972adcabc78a`。不修改 R97 已封文件、历史报告、seal 或旧受管授权。

| 子任务 | 代理 | 唯一所有权 | 当前状态 |
| --- | --- | --- | --- |
| SDK | `/root/r97_sdk_preflight_ultra` | domain-types/index；api-client/index；新 quarantine-review-v2.ts 与 .mts | v4 顺序 selftest 与专项 TypeScript 通过；HTTP0161 私有 fixture 的真实 SDK/UI 链路通过，范围见下文 |
| UI | `/root/r98_ui_ultra` | source-quality.tsx；新 binary-quarantine-review.tsx、context.ts 与 helper test；globals.css 最小折行补正 | helper/type checks 通过；HTTP0161 的 1440/390/320px 各175断言通过，真实宿主/设备仍待验 |
| Native | `/root/r98_native_ultra`，后续执行由 Root 与受托代理接续 | Rust security.rs/tests；Java NativePolicy/新 review policy test；native-client/index 与 transport.test.mjs；受管验证工具 | JS adapters39/transport2、Java纯policy10通过；Rust两次首编译红、0 exact pass，真实Native host/设备未验 |

SDK before 位于 `.artifacts/r98-sdk-77ccfbb5585d430d/before.json`；Native before 位于 `.artifacts/r98-native-60df4012257e469c9d486f3396979959/before-manifest.json`；UI before 位于 `.artifacts/r98-ui-20261021-before/before-manifest.json`。新文件记录原先不存在，不能虚构旧实现。

## 本轮接口与必须保持的行为

- 新方法为 `quarantineReviewV2(id, fence, signal?)`、`reviewQuarantineV2(id, payload, expectedAccountId, fence, signal?)`；复用 `RawEvidenceContextFence`、原 request/error 管线。旧 text 方法与 evidence decoder 保持原合同。
- 新 DTO/decoder 独立检查 16/10/3/6 键、真实车辆 payload、精确归属与 provenance；GET 200、POST 201、六键 body、单账户 header，不自动重试。POST 返回最新状态，不强制版本恰好加一或 history 第一项为本人提交。
- UI 冻结完整 `{detail, review, capture}`；detail 缺少完整 parser identity，使用现有 capture reader 补足。capture 的未解析 null 与解析后 detail 的 mapping 分别按真实合同验证。
- row loss、field loss 及其组合都支持；缺整行与缺字段分别展示。关闭、切记录、选源、刷新、auth/transport 变化同步撤销确认；迟到返回与 finally 不恢复旧资格。
- Native JS/Rust/Java 仅对精确 POST 原始路径及有序 query `mode=history&format=raw-evidence-v2` 允许安全账户 header，保留原库存行为、重复头/头预算与其他安全门。缺 header 的 binary 必填校验仍由后端执行。
- UI 新输入可 trim；SDK history 保留后端合法 CR/LF/TAB。丢响应/abort 只显示待核对，不宣称服务器回滚或自动补发。

## 已验证结果与当前准备状态

以下结果分别绑定各自冻结输入和执行时点。后续验证工具修订不能追认历史 checks/Java 的完整 tool manifest 与当前 live 相同，也不能回写历史结果。

| 范围 | 实际结果与证据边界 |
| --- | --- |
| v4 checks | `.artifacts/r98fc-9800000000000021/verification.json` 为 passed：1 个 sequential `.mts` selftest 入口 exit 0（不是可据此计数的 node:test 项）；TAP 共 63 项通过（12 + 10 + 39 + 2）；5 项 TypeScript 检查通过。220 个源码输入当次稳定。Root 回读：`.artifacts/r98-root-audit-20261021/checks-v4-result-readback.json`。范围仅 SDK/helper/adapters/transport 与类型检查，不含 HTTP、React 浏览器或真实宿主。 |
| Java v3 | `.artifacts/r98nj-9800000000000013/verification.json` 的 javac/JUnit policy 两阶段通过，实际 JUnit 10 项。Root 回读：`.artifacts/r98-root-audit-20261021/java-v3-result-readback.json`。工具版本差异已登记于 `.artifacts/r98-root-audit-20261021/java-v3-known-tool-version-delta.json`；旧结果只绑定其历史输入，不能声称完整 tool manifest 与当前 live 相同。此处不代表 Android 构建或设备验收。 |
| v8 build0062 | `.artifacts/r98fb-9800000000000062/verification.json` 总体 failed。desktop-vite、mobile-vite、web-icons 通过；Next root 真实 exit 0，但 Next Job total=25、seen=24，缺项身份未知，整阶段仍 failed，web-pwa 未运行。7 个 before 文件及图标目录已还原；220 个 sources、17 个 tools、9 个 generated inputs 当次稳定。保留 0022、0032、0042、0052、0062 各次失败与关闭/还原证据，不以新尝试覆盖。 |
| Native v9 / lifecycle 修订 | 该历史阶段 Native supervisor 为 SHA-256 `bd3c84099d3d65d7b79805129858afa7f96c1733010ad0d6d5bb5d7bf5615bde`；v9 仅补 root 退出后固定 5 秒 grace 的观察盲区，不能据此追认 v8 缺项根因。独立静审 `.artifacts/r98-lifecycle-review-20261021/v9-independent-review.md` 核实 Next 正常清理使用 SIGINT，旧统一 own exit0 门存在后续误拒绝条件；该门不是 v8 当次失败的直接原因。v10 已据精确 worker 证据修订终态门，动态结果如下。 |
| v10 build0082 | `.artifacts/r98fb-9800000000000082/verification.json` 为 passed，SHA-256 `a3f68aac5fce997b8a675d07323de516e29bbaed55f983af8fd46baa57dfb42e`；freeze SHA-256 `003ee57c0bb66de8df6fbbd4ed41780604da26e562afc66cae0e02b065abed49`。Root `.artifacts/r98-root-audit-20261021/build-v10-result-readback.json` 完整独核：5 phases 通过，33 observed=33 total（19 Node + 14 console），全自然关闭；33 个精确 PID 均获 `Get-Process` 的 `NoProcessFound` 结果。19 份 guard 分为 10 份 own exit0、5 份父实际观察 SIGINT、4 份实际 SIGINT 请求返回 true 且 Job 自然空；9 个 worker 不称为 own exit0。220 sources、17 tools、9 generated inputs 当次稳定，7 个 before 已还原；desktop 3、mobile 4、web 110 份产物的 hash/keyset/宿主指纹核过，optional probe 阻止 2 次、unexpected denied=0。范围仅生产前端构建，不代表 HTTP、React 浏览器、Native host 或设备验收。 |
| HTTP launcher r6 → r7 freeze | r6 exact freeze exit 1：`C:/Program Files/nodejs` 祖先符号链接被 regular 门拒绝，属于 freeze 失败，未到服务启动；见 `.artifacts/r98-http-execution-20261021/exact-freeze-failure-readback.json`。partial `.artifacts/r98wl-9800000000000091` 保留，无 freeze/services，fixture 0092 未创建。r7 源码 SHA-256 `c16a503fa3fd49a86222811dabbf89b55b898b59bb722bf8ca764d50e588e092`（41,951 bytes），仅改固定 physical Node `E:/DevTools/nvm/v22.22.1/node.exe` 及与 build 相同的 pin，不放宽 reparse 门；Root `.artifacts/r98-root-audit-20261021/launcher-v7-static-readback.json` 已独核。fresh `.artifacts/r98wl-9800000000000101/freeze.json` SHA-256 `04c968e160b3668e72bed7d2b518b129e1e90a1d0eb22483d9c2ba26156da542`；Root `.artifacts/r98-root-audit-20261021/launcher-v7-freeze-readback.json` 核过 21,580 个 hash bindings 及 keyset。该 freeze 通过不代表随后 run 通过。 |
| r7 首 run | `.artifacts/r98wl-9800000000000101/services.json` failed/ended，作者侧 session 62273 实际 exit 1：`trees={}`、child_denied=1、network_denied=0、database_denied=0、frozen_inputs_stable=true；主错误 `unreviewed child forbidden`，缺 `node-guard.jsonl` 是次级 verification_error。Root 较早 `Unknown process id` 仅是该次调用结果。fixture 0102 不存在、API 日志空，没有 API/Web 成功启动证据。安装 CPython 的 list→list2cmdline→audit string 静态合同解释 r7 按 list 比较会误拒，不是现场 observed args；后续 r8 已精确修订。模型 capacity/代理调度状态与进程失败分开记账。 |
| r8 run 失败 | launcher SHA-256 `8ab96dbd6f0a595efb14f726a904613571ec4cf9e236ad5d5a26ba0fd6dd78e5`；0111 freeze SHA-256 `88066c55e214236cb54e652d8274e29d514c1997afb9746b863af4d48275e8cc` 经 Root 核 21,580 bindings。run 30793 实际 exit 1，主错误 `AttributeError: 'function' object has no attribute 'client'`：http 模块被同名函数覆盖。API root 29372 被 forced own cleanup/Popen fallback 清理，不是自然 pass；fixture 0112 不存在，缺 server-return 是次级错误。Root `.artifacts/r98-root-audit-20261021/launcher-v8-failed-run-readback.json` 核精确 PID NoProcessFound、两口 netstat 行 0、R38/S2 pin 保持；这些观测不等于完整 Job 后代清单或全系统零进程。 |
| r9 run 失败 | launcher SHA-256 `423a0d778492743b6da763a46788b24eaa9d8f6adfd1938124d5d818cf5b9bdb`、fixture SHA-256 `fcce1f41bb92bd2dea760dfb0a258c3ccf818ae135fa7db703626fa0bf12b7c8`，修 http alias 并固定 base Python `-S`，tools=6。0121 freeze SHA-256 `2a8c790645bad4237b610166df41ebdcdfdd64649b9b32c70175ae08236441a3` 经 Root 核 21,581 bindings。run 62419 exit 1，实际 base root 60612 与 conhost 53712 的 exe/hash 匹配；conhost raw commandline 的 modern `0x4` 完整串不符原 legacy 字面量，故按 unknown own descendant 拒绝；不是 product 超额或已观察到 redirector 动态原因。Root `.artifacts/r98-root-audit-20261021/launcher-v9-failed-run-readback.json` 记录强停、source stable=true、缺 server-return 次级错误，根/console 精确 PID 无进程、两口 netstat 行 0、R38/S2 保持；未 ready、无 Web/UI，不记自然 cleanup pass。 |
| r10 / 0131 失败 | launcher `2cd49da3496d195eb22e41a7ff78d3bf11fa3d180de62c3d5193e3ae3cc28032` 的两条完整 conhost 字面量修订与0131 freeze均已实核，freeze SHA `49fe2a55d1427cfacd6477e8fa58f45cf034a4fb61aee6037e1a43a7b5ec4005`。TTY40591 实际 exit1：fixture seed 经 FileObjectStore.put 报 `object_write_failed`，API exit3、未ready/无Web。底层 OSError 被吞，根因未知，不写ACL/Guard/系统/I/O已修复。Job total2=observed2、无forced/fallback，但 lifespan不完整、不是自然cleanup pass；精确两PID缺席、两口0、R38/S2保持。Root：`.artifacts/r98-root-audit-20261021/launcher-v10-failed-run-readback.json`。 |
| Rust vendor v4 | 513 原归档共106,407,759 bytes；历史2 GET的5,974,524 bytes另账。V2 leading dot、V3 `~`误拒保留；V4有限例外及freeze已审。离线prepared SHA `da9a4d837dcd8c5c049a74ba9f6ea8a175605ce56ba86e457cf591db0d67ada7`；Root `vendor-v4-prepare-readback.json` 全核27,914 files、5,562 dirs、874,666,266 bytes及513 package checksums，本次network0。此处只证明依赖准备；后续两次Cargo实际失败见下行。 |
| Rust 私有 vendor 接线 | 已审v2 `daa3b7d352d4067f59a1b6ae7c7d3dcd8a371899dd53f0060da91c01cd06cc86` 在HTTP0161自然cleanup后应用、AST parse。fresh d69f freeze SHA `ab323de3a4a493c9974c4a0c19208533dc25711b388cafbbca7613d68fb49a6c`，Root `rust-freeze-readback.json` 独核28,062 bindings（67 sources/27,917 deps/12 exec/66 generated）、完整keysets、14 exact argv/1800s与原48product+1console=49Job、完整legacy不变。该freeze不是Cargo通过。 |
| live 工具边界 | Native现为固定linker后 `446648cd3dd39a6826dce1fbfbca6b7f005d75f159b96d93c39c0e1da7635896`；Frontend保持 `0ed37177b58ce6537f1301db15ef935f3a1224c875ac0b6fc6004d09a3b6c5b0`。原Native `bd3c84099d3d65d7b79805129858afa7f96c1733010ad0d6d5bb5d7bf5615bde` 与vendor v2 `daa3...06cc86` 分属历史输入；不回写checks/Java/build0082/0092或旧freeze的source_after。 |
| 真实材料研究 / 两次实际失败 | NHTSA aging（18页方法材料，无SKU成绩）与ROSA P UTQG 2024（评级指南，不是专业独立试验原始数据）各单次正式POST均HTTP201/body failed、`replayed=false`，原各自UUID GET200确认 `source_material_robots_unavailable`。无document/receipt/original/hash，objects0，child2/outer1分账、无强停、上下文关闭、输入稳定。具体robots HTTP状态未知，不推403。实际结果见两目录的 `EXECUTION-RESULT.md`；Root `material-v4-actual-readback.json`、`utqg-actual-readback.json`。Provider/export仍false。 |

## 本批后续实际回执

| 范围 | 实际结果与边界 |
| --- | --- |
| HTTP0141：服务通过/UI红 | 同一r10源码在escalated上下文启动API/Web ready，session24561 exit0、自然cleanup通过；不能据上下文差异推导0131的ACL/系统/I/O根因或修复。1440px只有75记录，2红：drop实际delivery观察断言，以及后续total13的次级失败；实际新增8条review。390/320均未跑。Root `http0141-terminal-readback.json` 核4精确PID缺席、两口0、R38/S2保持。服务和UI分别记账，不补绿。 |
| 截断fixture最小补正 | 独审/Root核后仅改fixture截断响应200→201及QA literal/注释；SDK本来就应在读JSON前要求生产POST201，不是产品错误。fixture新SHA `f0c74bd18a52331cf91db19566c34edf6f698ff6a681b595858ac7edbce211ac`，QA新SHA `7bf64600b74db9e1e8bb96ac83792730408c50287f4772e713a40ccc5f7e9296`；完整diff `.artifacts/r98-http-drop-fix-20261021/full.patch`。真实fetch/body失败、13条写入/审计门与生产201前置条件保留。 |
| HTTP0151：旧build0082窄屏红 | freeze SHA `656f539d8dcc24d70d7c345a5caa976ebee5fbd9381acb166e92a2ed4027281f`；1440为175全过，390为171记录、唯一横向overflow红（scrollWidth581>390）；320未跑。每已跑宽各新增13review/13audit、14 browser POST，held/armed=false；390时总review28/audit26。session11707 exit0、双树自然cleanup与guards0、输入/R38/S2保持；Root `http0151-terminal-readback.json`。旧UI失败不由新构建回填。 |
| 最小CSS / build0092 | 仅globals.css新增 `.quarantine-review > .raw-evidence > article { overflow-wrap: anywhere; }`，全文保留，不截断JSON。完整diff `.artifacts/r98-review-wrap-fix-20261021/full.patch`。新`.artifacts/r98fb-9800000000000092/verification.json` passed，SHA `ef24add74b54c0d8600d6059b3f8ae1eb8dad6fde5282429a57ce1c0fcd3e0ed`；freeze SHA `9ae706ff05ab335efc3224ae43e39acad27e2182d3195e9604c861f757bfa31b`。Root `build0092-result-readback.json` 核220 sources/17 executables/9 generated、三产物完整keyset/hash/宿主指纹和新CSS，7生成原件/备份/icon目录还原。5阶段33=19product+14console自然退出、无强停，Next25；worker终态为10 own0、7父实观SIGINT、2请求SIGINT/Job自然空，后9不称own0。首PIDprobe有60540占用但身份未记，随后精确缺席、再核33全缺席；见 `build0092-process-followup.json`，不推PID复用或倒填初测全0。 |
| HTTP0161 / 三宽 / cleanup通过 | fresh freeze SHA `1ce37325ed6f68fa772350b29218d85ca3813941550317f477749550738f9604`；Root全核21,581 bindings。1440/390/320各175断言全过，各13新review/13audit/14 browser POST，无held/armed；最终review41（seed2+39）/audit39、approval_use1不增。layout scroll1425/375/305分别不超1440/390/320。320另核3条article各完整640字JSON段落、继承anywhere、client=scroll214。session97489 exit0，API/Web各自然0/143、每Job2=observed2、无forced/fallback，4精确PID缺席/两口0、368 live sources及R38/S2保持。Root `http0161-terminal-readback.json`、`wrap-0161-320-computed.json`；范围为私有合成session/license/receipt和历史S2离线重放，不是新真实材料/Provider/设备验收。 |
| Rust首run / d69f 红 | session94615 exit1，verification SHA `d28e2c6019c589fd4a9d13d5e96cfcd8c2f3d5a967d1a8c727182ec4eb89048b`。首编译被未冻结F盘VS2022 link.exe拒绝；legacy console实际allowed，不是测试断言失败。0 completed/0 exact pass；observed21=20product+1console、forced Job close/owned termination=true、natural=false、Job total未知，final_exit0不作pass。Root `rust-first-failed-result-readback.json` 重核28,062 bindings/keysets稳定；`rust-first-process-readback.json` 核21精确PID当时全缺席，R38/S2保持。 |
| 固定linker / d6af freeze | 独审 `.artifacts/r98-rust-linker-fix-20261021/independent-review.md` 与Root核最小1行：只新增固定已冻结VS2019程序路径环境键 `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER`，不扩大允许list。官方本地Cargo文档支持无--target时host build-script同用linker、含空格值为单一program path。完整before保全后逐字节apply为446648...35896、AST exit0；实际AST为-I -X utf8 -B，无-S，不称no_site。单次fresh freeze d6af SHA `8b79dc2768d748407b51bf937bb84547d318653086796b35fb4174900990ecd8`，Root `rust-linker-freeze-readback.json` 全核28,062 bindings/keysets；14 argv/1800s/48+1=49/legacy原门不变，仅一env新增与fresh输出路径变化。apply/精确argv/stdout/stderr/tool终态见 `.artifacts/r98-linker-execution-20261021/`。 |
| Rust第二run / d6af 红，明确停点 | session90860 tool/child均exit1，verification SHA `049c076553143e5663ff8ac26ead5588ed012c3ae81c84e55f406af2a150b4c7`。首编译唯一拒绝为VS2019 vctip.exe PID59752、256032B、SHA `452ed9e110714d0892dc55c3d7e6dc8222e8fe49a153d92740ada905c75e9a0e`，完整命令只有程序路径；legacy实际allowed。仍0 completed/0 exact pass；observed35=34product+1console、forced/owned termination=true、natural=false、Job total未知，final_exit0不是通过。Root `rust-linker-failed-result-readback.json` 全核28,062 bindings/keysets稳定，`rust-linker-process-readback.json` 核35精确PID当时全缺席，R38/S2保持。`rust-vctip-static-file.json`只证文件描述为experience improvement data uploader，不证签名/上传/内部发现；不据名字宽放门，不猜VSCMD_SKIP_SENDTELEMETRY已生效。 |

## 尚待完成的验证

本卡以Rust第二红独核为R98本批停点快照；其后材料修正属于独立任务，不纳入本轮验收。Root后续已静审16 bindings/5 AST/163 roster并授权五文件apply及仅一次受管双材料模块检查，当前尚无该run结果；实际入口为 `.artifacts/material-robots-fix-execution-20261021/`，后续结果另立文档。

1. R98以本批实际结果保持草稿：HTTP0161三宽与自然cleanup通过；Rust两次首编译红、14 exact未完成。保留0131/0141/0151、旧build及两次Rust全部原账；后续结果另立新文档/前缀，不回写本批历史，不生成R98 seal或称close。
2. 优先独立推进材料robots诊断/Accept最小修正。只读诊断 `.artifacts/material-robots-review-20261021/ROBOT-DIAGNOSTIC-REVIEW.md` SHA `fd87f57d41b6042984ac2b1e6aeab4c36e7c004921f756937094075691a22dbf` 将既有粗码按冻结实现定位到非200/404/410的robots HTTP状态拒绝分支；具体状态仍未知，不是新抓包。robots继承PDF Accept是已证配置不一致，其实际致因未证。候选位置 `.artifacts/material-robots-fix-candidate-20261021/` 在R98停点时仍artifact、未apply/test；早期runner缺新boundary登记的静态发现保留，后续163 roster候选已审但不把执行授权写成通过。保持robots、跳转、重试或诊断清洗；未来真实尝试必须新冻结、新私目录、新UUID、单POST和原新UUID回读，不能编辑/重试两个旧失败身份。
3. Rust另立确定性方案，使受管编译不启动未审telemetry后代；先有官方依据、精确候选与独审，再决定新freeze/run。保持14 exact/1800s/48product+1console=49Job、完整legacy与原allowlist；不得仅凭文件名扩门、猜环境开关已生效或临场追加新可执行文件。本批不再apply/freeze/run。
4. 本次三文档before/after及HANDOFF尾文验核位于 `.artifacts/r98-progress-card-20261021/handoff-sync-http0161-rust-two-red-20261021/`。HANDOFF更新前全文件独立保全，新前缀后保留其完整原字节；旧R98 pending段落仅为历史快照。

用户已明确没有EPREL Key，并要求继续独立工作：自主选择公开合法材料、核具体发布关系与许可，不再索要Key或第一条URL。正常库保全升级、活PG、正式生产许可、首代online与Responses用途闭包、真实Provider、Native host/设备/picker/SAF/OS保存、专业原始试验/精确SKU/人工Golden及完整V1仍未验收。Provider/export保持false，V1 active；未commit/push，不reset/stash/clean他人dirty。
