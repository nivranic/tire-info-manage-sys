# R101 Native rust-lld 单次受管验证：红灯停点

日期：2026-10-21。状态：**唯一正式 run failed，0 completed phase / 0 exact test pass，不执行第二次**。本轮独立记录 R98 后续 linker 实验；R98 两次历史红灯、R100 材料 robots 403 及其旧证据保持原账，无 R98/R101 seal，不称 close，完整 V1 active。本报告记录本轮未验收的失败停点。

## 已审实现与实际冻结

最小候选独审后原字节 apply 到 `scripts/binary_quarantine_review_native_verify.py`：44,665 B，SHA-256 `1cab0955e857a43edfa54a7d0d9ce1aa3357837879a9e4058b523dd25c417534`。只新增固定 Rust lld 工具身份、Rust 专用 linker/单 flag 环境，以及该精确路径/bytes/hash 的 roster 与 descendant 检查；Java 原环境、Frontend 及既有 Guard/ChildPolicy 保持，其余拒绝规则保持。

- 工具：`E:/DevTools/rustup/toolchains/1.95.0-x86_64-pc-windows-msvc/lib/rustlib/x86_64-pc-windows-msvc/bin/rust-lld.exe`，113,349,120 B，SHA `3cf499fc8a03853722d19e3ae1c5cdd143ac7426f1405b9e6efacd7a94b7328a`。
- Rust 环境：固定 `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER` 为上述单一 program path；`CARGO_ENCODED_RUSTFLAGS=-Clinker-flavor=lld-link`。保留 MSVC/SDK/cc/cl/lib，不声称自足或无 telemetry。
- 原 14 exact Cargo argv、无 `--target`、各 1800s、48 product + 1 legacy console = 49 Job 同时活动上限、离线 vendor、私有 snapshot/输出、环境清洗及完整 legacy 合同保持。累计 total/observed 不能与同时活动上限混用。
- apply 回执：`.artifacts/native-lld-execution-20261021/apply-receipt.json`，7,914 B，SHA `29fca4012599b25dc2eac36f9e6bf6899a7988cc94eb77ad3dcb1a11970a0421`。候选独审：`.artifacts/native-lld-review-20261021/INDEPENDENT-REVIEW.md`，SHA `de0735c019cc14df17b21a2fd5e4a3db8e7cdac2c82287984ba15d39a74578e8`；这是静态审查，不是产品测试。

唯一 run UUID `e809daec-a931-4fdf-8df0-029e640936e2`，输出 `.artifacts/r98nr-e809daeca9314fdf/`。Root freeze session `60013`、终态工具块 `6ea05d` 实际 exit 0；freeze 为 7,318,013 B，SHA `dda9cc9fe674f712aa27a8dfe5330404dae926de827fcec4a9622118f80694b4`。正式 Python 合同保持 `-I -X utf8 -B`，没有 `-S`，不称 no_site。

Root 新 freeze 与终态独核均逐文件实核 **28,063 bindings = 67 sources + 27,917 dependencies + 13 executables + 66 generated inputs**，完整源码/vendor/生成 keysets、27,914 vendor files/5,562 dirs、三 receipt/config pins、14 argv/预算/环境通过。此数字现为新 freeze 实核值；不表示完整 sysroot、原生库与运行期 DLL 闭包。

## 唯一正式 run 的真实红灯

Root run session `39050`，初始工具块 `e39629`、终态 `3443d4`，外层 tool 实际 exit 1；首个 Cargo 的 `exit_code` 与 `final_exit_code` 都是 101。Native Python child 的退出码未单独捕获，不补称 child exit 1。工具观察与 Cargo 回执分账，不使用尾随字段或审计入口退出码追认成功。verification 为 failed，`phases=[]`；另有首阶段 process receipt，不可因未 append 到 phases 而漏记失败阶段。

| 项目 | 实际结果 |
|---|---|
| 完成/精确测试 | 0 completed phase、0 exact stdout pass；其余 13 阶段未执行 |
| 已观察进程 | 102 = 1 Cargo root + 80 rustc + 20 固定 rust-lld + 1 legacy conhost；观察到的 child 无 allowed=false |
| 完整盘点 | Job total 104、observed 102，`all_processes_observed=false`；缺少两个进程的身份，保持 unknown |
| 分类/身份 | 已观察 PID 全部分类，固定工具/legacy 身份通过独核；该结果不覆盖缺失的两个进程 |
| 资源字段 | `active_pids_after_natural_grace=[]`、`natural_resources_closed=true`、`forced_job_close=false`；Cargo 非零退出且盘点不完整，整阶段不算自然成功或验收通过 |
| 链接参数观察 | 20 个已观察 lld 为受审身份，独核到 `-flavor link`；适用的已观察 rustc 编译命令含固定 linker 与 flavor；不能泛化到全部未观察进程或全部 14 阶段 |
| 日志 | stdout 0 B；stderr 80,005 B，多处 `could not exec the linker` 指向该固定 lld，紧随 `拒绝访问。 (os error 5)` |

`os error 5` 的根因未知。没有证据把它定为 ACL、Job、CPU/并发、系统故障或审批拒绝；不能将观察到 20 个 lld 解释成所有 linker 启动成功。也不能因已观察列表没有 vctip，就称 telemetry 消失、无上传或无其他 child；缺失两个身份仍未闭环。Job 是自有树清理机制，不是网络权限隔离证明。

## 固定证据入口

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| 输出根 `verification.json` | 7,284,164 | `c7de2d4e122d94c547e9104cad645dfdcc4d5b2082ddecd2827c8e8c01082011` |
| 输出根 `rust-launch_config_accepts_only_a_port_and_isolated_slug.process.json` | 244,786 | `57c6a96094bfd225ebfd4bd9d663fb6cf51f5fb38692569b11640d4040b2a75a` |
| 同阶段 `stderr.log` | 80,005 | `8736e1eff9376461fbcc1977d58df34df71e55dd33ff395ba3fd40e65dd1964c` |
| `.artifacts/native-lld-root-audit-20261021/freeze-readback.json` | 848 | `bc40f4486a368914022277f599a734cf4b54cafd1ad63ab153d4471e7660a2e8` |
| `.artifacts/native-lld-root-audit-20261021/terminal-readback.json` | 31,833 | `8f630b1969b0c63f488e62934b5adf71d60620e0eaa03fcd55255b563e8f6d08` |
| `.artifacts/native-lld-root-audit-20261021/tool-terminal-observation.json` | 2,389 | `f4a276c1517bca1eab0c18748bb7e37ecac5c5369f2fbc9fdc532babb73760c3` |
| `.artifacts/native-lld-review-20261021/terminal-pid-readback.json` | 41,193 | `9f4bab875cdcc75c404086a2273970d452527df5fb5b465950714b237f08a541` |

终态独核由 `.artifacts/native-lld-execution-review-20261021/readback.py` v2（SHA `c086219301d5c9bf7d3a323b9cddc9e9cd9937bab676053ccb67e8f11f54e070`）读取实际文件，session `55909` / 末 `e7dc2a` 实际 exit 1，JSON 为 `audit_ok=true / accepted=false`、输入完整 keysets/hash 稳定：这是成功读取并确认红灯，不是产品通过。v1 原字节与精确两处 Windows 路径大小写/斜杠比对补正另存；这是独核工具合同对齐，不修改运行结果、不重启正式 run。

独立 PID 回读仅对这 102 个精确 PID 使用 `Get-Process -Id`，当时全部 `NoProcessFound`，present=0、query_failed=0；不能找回缺失两个身份、倒推运行中完整观察/自然成功，或宣称全系统无进程。

有限独审 `.artifacts/native-lld-review-20261021/terminal-review.md`（SHA `4e3b9d0a3b10d7ed0feb9e40896bda0821b516d25a9fa4e5f01f7784fe1dcef9`）另核回执/102 PID，未全重哈 28,063 项。它确认冻结环境无 `NUMBER_OF_PROCESSORS` / `CARGO_BUILD_JOBS`、14 argv 无 jobs、私 Cargo config 无 `build.jobs`；不反推有效 CPU/jobs 或本次根因。受托代理限定查询 CodeIntegrity/AppLocker/Defender 三个指定频道各一次，均 `UnauthorizedAccessException`、无事件内容，未升级/重试；实际时间窗口丢亚秒，不称精确完整覆盖，也没有 block 佐证，根因仍 unknown。[限定 Windows 事件回读](E:/Mix/project/tire-info-manage-sys/.artifacts/native-lld-failure-diagnostic-20261021/limited-windows-event-readback.json)，SHA `d5bfbfea827214f913e65381ce65f55ae8cd52168b881e5098b8c3a071bceda4`。

Root 辅助 `apply_patch` cell `657` 长等后只终止该辅助 cell，没有第二次正式 run。`run-initial-observation.json` 当次且安全汇总时实际不存在，不虚构该文件。上述 `tool-terminal-observation.json` 是 Root 实际工具观察的安全汇总，**不是 raw tool 日志**，与固定文件独核分账。

## 保护与下一步

当前 HANDOFF 完整 before 已保全至 `.artifacts/native-lld-progress-20261021/HANDOFF.before.md`：102,243 B，SHA `e6109b7131dca8aba63877c5693fe2103b326cb75cf3d4453d5c2eef719f4923`；拟追加最小前缀，以下旧全文保留。R98 d69f/d6af 的四份 freeze/verification 只读重哈希与旧记录相同，不回写旧结果。Root `protected-before-run.json` / `protected-after-run.json` 对 R38/S2 原文件 bytes/hash 首尾一致；after 为 670B，SHA `fb905a854313565b4e0b23a83f5a275b5eee20f07f35d7aebe3b99da3fca6185`。这是 Root 纯文件 hash、无数据库连接；本文仅读取该 JSON，不声称正常库启动或数据库句柄验收。

停在本次 failed，不重试此 UUID、不删旧目录、不现场加工具/放宽门。下一步按官方 Cargo 依据另立**构建并发固定值候选与完整进程观察方案**，保持原 14 argv/1800s/48+1 与完整观察门，分别处理 `os error 5` 精确条件与两个缺失身份；并发只是待审方向，不是已证根因或修复。后续由 Root 按既有用户授权，在完成独审和新输入审定后另行决策 apply/freeze/run，使用新身份/新私目录。本次没有新增真实材料、Provider、正常库/PG、Native UI/host/picker/设备验收；EPREL 无 Key 不再问，R100 403 不变、Provider/export=false、完整 V1 active，未 commit/push。

[本轮文档应用回读](E:/Mix/project/tire-info-manage-sys/.artifacts/native-lld-progress-20261021/docs-apply-readback.json)。
