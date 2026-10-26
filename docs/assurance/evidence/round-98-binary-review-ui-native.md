# R98 二进制审批 SDK / UI / Native 接线证据（草稿）

日期：2026-10-21。**草稿／本批停点；R98 尚未封存；完整 V1 保持 active。** 本文同步既有实际回执与 Root 独核，不创建 seal、不称 close；同时更新执行卡和HANDOFF。此次文档同步没有另行运行服务、测试、浏览器、Cargo、网络、数据库或Provider。各执行者实际做过的运行和失败按下文分层记账。

## 范围与历史边界

R97 只封存 Task0 后端切片，历史报告为 `docs/assurance/evidence/round-97-binary-review-boundary.md`；其唯一 seal `.artifacts/r97-close-8de9f8b8091148d8949f3aaa49e68706/verification-final.json` 的 SHA-256 为 `62a4b392e3d20a6a507b882aa11179e9c0f9a4f5beb9eef28f5aef19d3dd92d4`。该封存不代表 R98 Task1、真实 UI/Native 或完整 V1 验收。

本轮功能依据是 `docs/plans/2026-10-20-binary-quarantine-review-ui.md`、`docs/plans/2026-10-20-binary-quarantine-review-ui-addendum.md` 与当前执行卡 `docs/plans/2026-10-21-binary-review-r98-execution.md`。原计划及增补保留其历史静态状态；本轮实施进度以执行卡和下列实际回执为准。

| 实施范围 | 已接入的行为；运行时边界见后文 |
| --- | --- |
| SDK / DTO | 新 V2 GET/POST 方法复用 `RawEvidenceContextFence`，严格解码闭合 DTO、归属及 provenance；POST 使用六键 body 与单账户 header，保留旧 text 合同。POST 解码服务端 latest state，不强制 revision 恰加一或 history 第一项等于本次提交。 |
| 共享审批 UI | `source-quality` 接入 binary 表单，支持 row loss、field loss 及组合；冻结完整 detail/review/capture，用 capture 补足 parser identity。关闭、切记录/来源、刷新、auth/transport 变化同步撤销确认；迟到结果不恢复资格。丢响应/abort 只显示结果待核对，不自动补发或宣称服务端回滚。 |
| Native JS / Rust / Java policy | 仅对精确 POST 原始路径 `/v1/quarantines/<id>/reviews?mode=history&format=raw-evidence-v2` 放行安全单账户 header，维持原 inventory/text 行为、重复头/预算与其他安全门。这里是账户 header 允许范围；binary 缺 header 的必填校验仍由后端执行。 |

## 已取得的验证

各项结果仅绑定其冻结输入和当次执行。历史 checks/Java 的 tool manifest 不能冒称与后续 live 工具完全相同；类型、helper、policy、build、HTTP、浏览器和真实宿主/设备分别记账。

| 层级 | 实际结果与证据 |
| --- | --- |
| SDK / helper / adapters / TypeScript | `.artifacts/r98fc-9800000000000021/verification.json` 通过。1 个顺序 SDK `.mts` selftest 入口 exit 0，不能虚构 node:test 项数；TAP 63 项（12 + 10 + 39 + 2）及 5 项 TypeScript 检查通过。Root `.artifacts/r98-root-audit-20261021/checks-v4-result-readback.json` 独核；不含 HTTP、React 浏览器或 Native 真实宿主。 |
| Java 纯 policy | `.artifacts/r98nj-9800000000000013/verification.json` 的 javac/JUnit 两阶段通过，实际 JUnit 10 项。Root `.artifacts/r98-root-audit-20261021/java-v3-result-readback.json` 独核；已知工具版本差异另记于 `.artifacts/r98-root-audit-20261021/java-v3-known-tool-version-delta.json`。不代表 Android 构建或设备验收。 |
| 历史build0082三端生产构建 | `.artifacts/r98fb-9800000000000082/verification.json` passed，SHA `a3f68aac5fce997b8a675d07323de516e29bbaed55f983af8fd46baa57dfb42e`；freeze SHA `003ee57c0bb66de8df6fbbd4ed41780604da26e562afc66cae0e02b065abed49`。Root `build-v10-result-readback.json` 独核5 phases、33 observed=33 total（19 Node+14 console）自然关闭，33精确PID缺席；220 sources/17 tools/9 generated稳定、7 before还原及三端产物核过。10 own0/5父实观SIGINT/4请求true且Job空分账，不称9 worker own0。后续CSS及0092不回填本次历史输入；此处仅证明构建。 |
| Rust vendor V4 离线准备 | `.artifacts/r98rv-4c71a0e9b382d68f/prepared.json` SHA `da9a4d837dcd8c5c049a74ba9f6ea8a175605ce56ba86e457cf591db0d67ada7`；Root `vendor-v4-prepare-readback.json` 核27,914 files/5,562 dirs/874,666,266 bytes/513 package checksums，本次network0。513归档106,407,759 bytes、历史2 GET的5,974,524 bytes另账。该准备不是Cargo验收；后续两次正式run均红，见后文。 |
| HTTP launcher r7 freeze | r7 源码 SHA-256 `c16a503fa3fd49a86222811dabbf89b55b898b59bb722bf8ca764d50e588e092`（41,951 bytes），改固定 physical Node `E:/DevTools/nvm/v22.22.1/node.exe` 及 build 同一 pin，未放宽 reparse 门。Root `.artifacts/r98-root-audit-20261021/launcher-v7-static-readback.json` 核最小 diff 与实际路径。`.artifacts/r98wl-9800000000000101/freeze.json` SHA-256 `04c968e160b3668e72bed7d2b518b129e1e90a1d0eb22483d9c2ba26156da542`；Root `.artifacts/r98-root-audit-20261021/launcher-v7-freeze-readback.json` 实核 21,580 个 hash bindings 与 keysets。freeze 不代表服务、HTTP 或浏览器成功。 |

## 失败保留与生命周期证据

v8 `.artifacts/r98fb-9800000000000062/verification.json` 整轮 failed：Next root 虽真实 exit 0，但 Job total=25、seen=24，未观察到的 1 个身份未知，web-pwa 未运行；9 个 Next worker 没有各自 own exit0。独审 `.artifacts/r98-lifecycle-review-20261021/v9-independent-review.md` 确认框架正常清理使用 SIGINT，且旧统一 own exit0 门存在后续误拒绝条件；该门不是 v8 当次 Job 计数失败的直接原因。Native v9 补 root 退出后的 5 秒 grace 观察盲区，也不能据此追认该缺项的发生时段或身份。

v10 的新限定终态证据为：19 份 guard 中，10 份 own exit0；5 份由精确父进程实际观察到 SIGINT；4 份有精确实际 SIGINT 请求返回 true，并结合 Native Job 自然空。后两类共 9 个 worker 不称为 own exit0，也不把请求信号等同于观察到 worker exit code=0。新证据不能回填旧 v8 日志；0022/0032/0042/0052/0062 失败保留。

HTTP r6 的 exact freeze exit 1 来自 lexical Node 祖先 `C:/Program Files/nodejs` 为符号链接而被 regular 门拒绝，不是服务失败。`.artifacts/r98-http-execution-20261021/exact-freeze-failure-readback.json` 留存完整失败；partial `.artifacts/r98wl-9800000000000091` 保留，无 freeze/services，fixture 0092 未创建。r7 使用精确 physical Node 修订后另取 fresh freeze，不覆写该失败。

r7 首次 run 已终止失败：`.artifacts/r98wl-9800000000000101/services.json` 为 failed/ended，`trees={}`，guard_counts 为 child_denied=1、network_denied=0、database_denied=0，frozen_inputs_stable=true。主错误是 `unreviewed child forbidden`；finally 读取不存在的 `node-guard.jsonl` 形成次级 verification_error，不能替代主错误。fixture 0102 不存在、API stdout/stderr 均空，没有 API/Web 成功启动证据。作者侧原 session 62273 已取得真实 exit 1；Root 较早调用返回 `Unknown process id` 仅代表该次轮询结果，运行终态依据为实际 exit 1 与 failed/ended 回执，不能说仍运行。

安装 CPython `subprocess.py` 的静态判词是：Windows 会将 list 参数先经 `list2cmdline` 转为 string，再发 audit；r7 按 list 比较会误拒。此处不是现场 observed args，不将静态转换路径填成实际子进程 argv。该精确合同随后在 r8 修订；后续实际 run 分别记账。模型 capacity/代理调度状态单列，与进程失败分别记账。

| 后续 HTTP 尝试 | 实际结果与边界 |
| --- | --- |
| r8 / 0111 | launcher SHA-256 `8ab96dbd6f0a595efb14f726a904613571ec4cf9e236ad5d5a26ba0fd6dd78e5`；freeze SHA-256 `88066c55e214236cb54e652d8274e29d514c1997afb9746b863af4d48275e8cc` 由 Root 全核 21,580 bindings。run 30793 实际 exit 1，主错误 `AttributeError: 'function' object has no attribute 'client'`，http 模块被同名函数覆盖。API root 29372 未 ready，被 forced own cleanup/Popen fallback 清理；fixture 0112 不存在，server-return 缺失为次级错误。Root `.artifacts/r98-root-audit-20261021/launcher-v8-failed-run-readback.json` 核精确 root NoProcessFound、两口 netstat 行 0、R38/S2 保持；强停后的关闭不是自然 pass，也没有完整 Job 后代清单。 |
| r9 / 0121 | launcher SHA-256 `423a0d778492743b6da763a46788b24eaa9d8f6adfd1938124d5d818cf5b9bdb`、fixture SHA-256 `fcce1f41bb92bd2dea760dfb0a258c3ccf818ae135fa7db703626fa0bf12b7c8`：修 http alias、改固定 base Python `-S`，tools=6。freeze SHA-256 `2a8c790645bad4237b610166df41ebdcdfdd64649b9b32c70175ae08236441a3` 经 Root 全核 21,581 bindings；run 62419 exit 1。实际 base root 60612、conhost 53712 的 exe/hash 匹配，但完整 modern `0x4` raw commandline 不符 legacy 字面量，故 unknown own descendant 拒绝，不是 product 超额或已观察到 redirector 动态原因。Root `.artifacts/r98-root-audit-20261021/launcher-v9-failed-run-readback.json` 记录 source stable=true、强停与 server-return 缺失次级错误；根/console 精确 PID 无进程、两口 netstat 行 0、R38/S2 保持。未 ready、无 Web/UI，不算自然 cleanup 通过。 |
| r10 / 0131 失败 | 两条完整conhost字面量的r10修订已审/apply/AST；launcher SHA `2cd49da3496d195eb22e41a7ff78d3bf11fa3d180de62c3d5193e3ae3cc28032`。0131 freeze 5,100,889B，SHA `49fe2a55d1427cfacd6477e8fa58f45cf034a4fb61aee6037e1a43a7b5ec4005`，Root核21,581 bindings。实际TTY40591 exit1：fixture seed→FileObjectStore.put→object_write_failed、API exit3，未ready/无Web/UI。底层OSError被吞，根因未知；不写ACL/Guard/系统/I/O原因或修复。Job total2=observed2、无forced/fallback，但lifespan未完成，不算自然cleanup pass；两精确PID缺席、两口0及R38/S2保持。Root `launcher-v10-failed-run-readback.json`。 |

各版完整源码快照、literal 和实际回执保留在 `.artifacts/r98-http-execution-20261021/launch-revision8`、`.artifacts/r98-http-execution-20261021/launch-revision9`、`.artifacts/r98-http-execution-20261021/launch-revision10`；其中候选文档保留编写当时的历史状态，后续应用/freeze/run 以 Root 的实际回执及本节为准。

## HTTP、真实浏览器与新生产构建

| 输入/执行 | 实际结果与边界 |
| --- | --- |
| HTTP0141，同源码/不同执行上下文 | API/Web实际ready、session24561 exit0、自然cleanup通过；Root `http0141-terminal-readback.json` 核4精确PID缺席、两口0、输入/R38/S2保持。此上下文差异不证明0131的ACL/系统/I/O根因或修复。UI 1440为75记录、2红：drop实际指定delivery观察失败，随后total13为次级红；真实新增8review，390/320未跑。服务通过和UI失败分开，不补绿。 |
| fixture截断响应200→201 | Root/独审确认SDK正确在JSON前要求生产POST201；错误在fixture截断响应改成200。完整两文件diff `.artifacts/r98-http-drop-fix-20261021/full.patch` 仅保留生产201、同步QA literal/注释，fixture SHA `f0c74bd18a52331cf91db19566c34edf6f698ff6a681b595858ac7edbce211ac`、QA SHA `7bf64600b74db9e1e8bb96ac83792730408c50287f4772e713a40ccc5f7e9296`。没有产品修改；真实fetch/body失败断言、13条写入/审计与201前置门保留。 |
| HTTP0151，build0082 | fresh freeze SHA `656f539d8dcc24d70d7c345a5caa976ebee5fbd9381acb166e92a2ed4027281f`。1440为175全过；390为171记录，仅document横向overflow红（581>390），320未跑。每已跑宽各13新增review/13audit、14 browser POST、held/armed=false；390时总review28/audit26。session11707 exit0、双树自然cleanup/guards0/输入及R38/S2稳定。Root `http0151-terminal-readback.json`；不能用新CSS追认此UI已过。 |
| CSS最小补正 / build0092 | 只加globals.css `.quarantine-review > .raw-evidence > article { overflow-wrap: anywhere; }`，完整diff `.artifacts/r98-review-wrap-fix-20261021/full.patch`；没有截断或隐藏JSON。`.artifacts/r98fb-9800000000000092/verification.json` passed，SHA `ef24add74b54c0d8600d6059b3f8ae1eb8dad6fde5282429a57ce1c0fcd3e0ed`，freeze SHA `9ae706ff05ab335efc3224ae43e39acad27e2182d3195e9604c861f757bfa31b`。Root `build0092-result-readback.json` 核220 sources/17 exec/9 generated与三产物完整keyset/hash/宿主指纹/新CSS，7生成原件及备份/icon目录还原。五阶段33=19product+14console自然退出，无forced；Next25。10 own0、7父实观SIGINT、2请求SIGINT/自然Job空，后9不称own0。首PIDprobe曾见60540占用但未记身份；随后精确缺席、再核33均缺席，见 `build0092-process-followup.json`；不推PID复用或倒填首测全0。 |
| HTTP0161 freeze | `.artifacts/r98wl-9800000000000161/freeze.json` SHA `1ce37325ed6f68fa772350b29218d85ca3813941550317f477749550738f9604`。Root `http0161-freeze-readback.json` 全核21,581 bindings/keysets，仅已审CSS/新0092报告与产物/时间输出变化。 |
| HTTP0161 三宽实际UI | 1440/390/320px各175断言全过，各13新review/13实际audit、14 browser POST，无held/armed；最终review41=seed2+39、audit39，approval_use1不增。layout scrollWidth分别1425/375/305，均不超viewport。drop保持201且fetch或JSON body实际拒绝；没有自动补发。Root `http0161-terminal-readback.json` 逐宽匹配fixture回执。320另由 `wrap-0161-320-computed.json` 核3条article各完整640字JSON段落、继承anywhere、clientWidth=scrollWidth214。 |
| HTTP0161 自然关闭 | session97489实际exit0，services SHA `e3b3ad89fc9c1017c7d9aa220750f314d47fee45d4c4e5d5f255e8a97fcdf513`。API/Web各自然0/143、每Job2=observed2，forced/fallback均false；4精确PID缺席、两口netstat0；Root重哈希368 live sources、R38/S2保持，guards0。主证据 `http0161-terminal-readback.json`、`http0161-process-port-readback.json`。 |

上述真实HTTP/浏览器使用私有合成session、许可、receipt和历史S2离线重放；不等于新真实材料捕获、生产来源许可、Provider、Native宿主、设备或OS保存验收。0131/0141/0151与旧build红账全部保留。

## Rust两次正式运行：均首编译红，0 exact pass

vendor v2候选 `daa3b7d352d4067f59a1b6ae7c7d3dcd8a371899dd53f0060da91c01cd06cc86` 在HTTP0161自然cleanup后应用并AST parse。fresh d69f freeze SHA `ab323de3a4a493c9974c4a0c19208533dc25711b388cafbbca7613d68fb49a6c`；Root `rust-freeze-readback.json` 全核28,062 bindings（67 source、27,917 dependency、12 executable、66 generated）、完整keysets、14 exact argv/1800s、48product+1console=49Job及完整legacy门。

| 正式run | 实际结果 |
| --- | --- |
| d69f / session94615 | tool exit1，`.artifacts/r98nr-4c71a0e9b382d69f/verification.json` SHA `d28e2c6019c589fd4a9d13d5e96cfcd8c2f3d5a967d1a8c727182ec4eb89048b`；首编译被未冻结的F盘VS2022 link.exe PID66692拒绝，legacy console实际allowed。0 completed phase/0 exact pass，不是测试断言失败。observed21=20product+1console，forced_job_close/owned termination=true、natural=false、Job total未知，final_exit0不是pass。Root `rust-first-failed-result-readback.json` 重核28,062 bindings及完整keysets稳定，`rust-first-process-readback.json` 核21精确PID当时均NoProcessFound；R38/S2保持。 |
| 已审固定linker / fresh d6af | 仅新增固定已冻结VS2019 linker单一程序路径环境键 `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER`。完整diff/本地Cargo官方依据与独审见 `.artifacts/r98-rust-linker-fix-20261021/independent-review.md`；未扩allowlist，14argv/1800s/48+1=49/legacy均不变。完整before独立保全后逐字节apply成 `446648cd3dd39a6826dce1fbfbca6b7f005d75f159b96d93c39c0e1da7635896`；实际AST argv为-I -X utf8 -B，无-S，不称no_site。单次fresh freeze SHA `8b79dc2768d748407b51bf937bb84547d318653086796b35fb4174900990ecd8`，Root `rust-linker-freeze-readback.json` 全核28,062 bindings/keysets及唯一env新增。apply/精确argv/stdout/stderr/child与tool终态保全在 `.artifacts/r98-linker-execution-20261021/`。 |
| d6af / session90860，第二红 | tool与正式child均exit1，`.artifacts/r98nr-4c71a0e9b382d6af/verification.json` SHA `049c076553143e5663ff8ac26ead5588ed012c3ae81c84e55f406af2a150b4c7`；首编译唯一拒绝为VS2019 vctip.exe PID59752、256032B、SHA `452ed9e110714d0892dc55c3d7e6dc8222e8fe49a153d92740ada905c75e9a0e`，完整命令仅程序路径，legacy allowed。仍0 completed/0 exact pass；observed35=34product+1console，forced/owned termination=true、natural=false、Job total未知，final_exit0不作pass。Root `rust-linker-failed-result-readback.json` 重核28,062 bindings/完整keysets稳定；`rust-linker-process-readback.json` 核35精确PID当时全NoProcessFound，R38/S2保持。 |

Root `rust-vctip-static-file.json` 仅核当前文件与observed hash相同，FileDescription为VC compiler/tools experience improvement data uploader；未验证签名、实际上传或内部发现机制。不得仅凭名字加allowlist，也不得猜 `VSCMD_SKIP_SENDTELEMETRY` 已生效。两次强制关闭不改称自然通过；本批以两红明确停点收口，不再apply/freeze/run。14 exact Rust policy、真实Native host/UI/picker/设备均未通过验收。

当前Native工具SHA为446648...35896，Frontend为 `0ed37177b58ce6537f1301db15ef935f3a1224c875ac0b6fc6004d09a3b6c5b0` 不变。checks/Java/旧build及旧freeze/report保持各自历史绑定，不补称当前tool manifest相同。

## 两次真实材料尝试：正式终态失败

| 材料/独立身份 | 实际结果与证据 |
| --- | --- |
| NHTSA aging v4 | UUID `14f5ddc6-6cd9-4905-ae39-4f3fb7a71c60`，request `5d8b2a7d-4df6-40ad-957d-e7078ce45983`。Root执行前核12,705 records/12,496互异文件；v4仅把product_python_files右侧排序以保持完整列表/重数检查。实际恰一POST201、body failed/replayed=false，原UUID GET200确认同 `source_material_robots_unavailable`。主结果 `.artifacts/material-capture-execution-20261021/EXECUTION-RESULT.md`；Root `material-v4-input-readback.json`、`material-v4-actual-readback.json`。18页研究方法材料不提供可直接当SKU成绩的数据。 |
| ROSA P UTQG 2024 | 新独立UUID `369c54c6-1e28-4b63-bb69-9a096537725b`，request `f8afc3f0-ba41-42d9-b301-26c8ddf9c059`。Root执行前核12,704 records/12,495互异文件；恰一POST201、body failed/replayed=false，原UUID GET200确认同失败码。主结果 `.artifacts/utqg-capture-execution-20261021/EXECUTION-RESULT.md`；Root `utqg-input-readback.json`、`utqg-actual-readback.json`。它是评级指南，不是专业独立试验原始数据、成绩排名或精确SKU桥。 |

两次document/receipt均null、原件不存在、objects普通文件0；没有原件hash、成功下载/重开或人工页码/许可后验。child exit2与outer tool exit1分别记账；exact child句柄已退出、TestClient上下文关闭、无强停、输入首尾稳定，候选child/nonprivate-SQLite denied0。数字PID未持久化；aging的CIM不可用与名称/可读路径fallback不构成全机进程普查。stderr均只保存抑制计数276而非原文，同计数不证明共同原因。HTTP201是路由状态，不是业务成功。

两次具体robots HTTP状态和正文均未知，不推403。只读诊断 `.artifacts/material-robots-review-20261021/ROBOT-DIAGNOSTIC-REVIEW.md` SHA `fd87f57d41b6042984ac2b1e6aeab4c36e7c004921f756937094075691a22dbf` 按冻结源码把该粗码映射为已取得非200/404/410状态后的拒绝分支，按调用图未到目标PDF GET；这是静态阶段判断，无新增网络抓包。robots GET继承PDF Accept与随后要求text/plain存在配置不一致，但对两次真实失败的致因未证。

Provider/export保持false。公开许可条款、目录页或preview can_capture=true不能替代实际原件的署名/版本/第三方权利核验，更不能转成专业SKU/Golden或Provider许可。

## 当前下一入口与保留边界

本报告以Rust第二红独核为R98本批停点快照。之后材料修正另立任务：Root已静审16 bindings/5 AST/163 roster并授权五文件apply和仅一次受管双模块检查，当前尚无run结果；执行位置 `.artifacts/material-robots-fix-execution-20261021/`，不纳入R98验收。

1. 优先独立完善材料robots诊断/Accept最小修正，候选位置 `.artifacts/material-robots-fix-candidate-20261021/`；在R98停点时仍artifact、未apply/test。早期runner缺新boundary登记的静态发现保留；后续163 roster候选已审，执行授权不是测试通过。保持原robots、redirect、重试、清洗与许可门。未来真实尝试另立fresh输入/私目录/UUID，单POST及原新UUID查询；两个旧失败身份及回执不得编辑或重试。后续实际结果另立新文档/新前缀，不回写本R98历史。
2. Rust另立有官方依据的确定性方案，使编译不启动未审telemetry后代；保持原14 exact/时间/进程/legacy/allowlist边界，不以未验证env开关或宽放新进程解决。
3. 用户明确无EPREL Key且要求继续独立工作；自主选择公开合法来源并核发布关系与许可，不再询问Key或第一条URL。

R98仍为草稿/未seal/不称close；正常库保全升级、活PG、正式生产来源许可、首代online与Responses用途闭包、真实Provider、Native host/设备/picker/SAF/OS保存、专业原始试验/精确SKU/人工Golden与完整V1仍开放。V1 active，未commit/push。

本次三文档before/after与HANDOFF完整尾文验核位于 `.artifacts/r98-progress-card-20261021/handoff-sync-http0161-rust-two-red-20261021/`；本次文档同步仅做静态读写与链接/字节检查，不重跑上述任何验收。
