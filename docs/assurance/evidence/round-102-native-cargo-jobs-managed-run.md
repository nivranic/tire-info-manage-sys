# R102 Native Cargo jobs=1：单次受管验证失败停点

2026-10-21。**唯一正式 run failed，0 completed phase / 0 exact test pass。** 本次 Job 6/6 观察完整，编译仍未成功；不回填 R101 的两个未知身份、不称 jobs 修复编译或证明无 telemetry/上传。[R101](E:/Mix/project/tire-info-manage-sys/docs/assurance/evidence/round-101-native-lld-managed-run.md)及更早红灯原账保留，无 seal/close，完整 V1 active。

## 实施与冻结

独审后 exact apply 的 verifier 为 44,687 B，SHA `8ed1793a6961cf421d66b8bdc82f8e0b6305aa87263d89c593f8fb898787d523`；相对 R101 只在既有 Rust 受控环境追加字符串 `CARGO_BUILD_JOBS="1"`，新增22 B。原14 exact Cargo argv/1800s/48 product+1 legacy console 同时活动上限、固定 lld/环境、完整观察与自然退出门保持。apply 回执 SHA `c8ebb0501fd2a9a60ac9e43c4943725b40e682ce897eab373456502cb786dc82`，位于 `.artifacts/native-cargo-jobs-execution-20261021/apply-receipt.json`。

唯一 UUID `22afa37b-aee3-482a-bb97-b13ee3e26130`，输出 `.artifacts/r98nr-22afa37baee3482a/`。Root freeze session65662/末836e44，outer与单独记录的 Native Python 均exit0；正式Python保持 `-I -X utf8 -B`，无 `-S`。freeze为7,318,043 B，SHA `b4ad4b5b285e8e5336302a7bba308c28191bf8a8c89f5b2cb2509bb6e84d5dcb`。

Root freeze独核session95972/末201d56实际exit0；终态独核session86215/末8a685b实际exit1、`audit_ok=true/accepted=false`，是成功独核红灯，非产品pass。两次均完整实核 **28,063 bindings=67 sources/27,917 dependencies/13 executables/66 generated inputs** 与完整keysets、vendor27,914 files/5,562 dirs；新freeze相对R101恰verifier一项source改变、其余source/deps/tools绑定相同，完整环境仅私路径重定位+jobs字符串1。该数字不表示完整sysroot/原生库/DLL闭包。

## 唯一 run 的实际结果

Root session16396/初44d614/末d67f52，outer实际exit1；`run-invocation-terminal.json` 单独捕获 Native Python exit1；首Cargo exit/final均101，三层退出分账。verification failed且phases=[]，另有首阶段failed process receipt；其余13阶段未执行。

| 检查 | 当次结果与边界 |
|---|---|
| Job盘点 | total6=observed6=1 Cargo root+4 rustc+1 legacy；all_processes_observed/classified=true，独核inventory/identities/console/caps均true；无observed child denied，0个lld进程身份记录 |
| 收口 | active_after=[]、natural_resources_closed=true、forced_job_close=false；Cargo非零，整体仍failed，`natural_exit_verified=false`，不算阶段自然成功 |
| 实际日志/测试 | stdout实际0 B/0 exact；stderr3,931 B，L2固定rust-lld `could not exec`、L4 `拒绝访问。 (os error 5)`、L7 proc-macro2 build script编译失败，非测试断言失败 |
| PID回读 | 有限独审对6个精确已观察PID逐项Get-Process：当时6 NoProcessFound/present0/query_failed0；不推全系统无进程，也不补R101旧104/102的两个未知身份 |

`os error 5` 根因仍unknown，不定为ACL、sandbox、Job、CPU/并发、审批或系统策略；没有lld身份不能补造成功启动/PID。Job及offline不是网络权限隔离证明。本次完整6/6只绑定本次失败run，不能追认旧盘点或telemetry结论。

## 核心证据

以下输出文件均位于本次唯一输出根；Root安全汇总是实际工具观察的派生记录，**不是raw tool日志**。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `verification.json` | 7,284,164 | `00585359e7d9cf58075c3169c4e237ef22f9846186eddb2c5f5629e35a980fe0` |
| 首阶段 `process.json` | 6,141 | `2c490c9838357e2f0a7a6edaf3feab2c2ae306b32816aae2087a55b5dd1d421c` |
| 首阶段 `stderr.log` | 3,931 | `74e15639a3f4e05588f3202d5200570a04fd4e421d844795e1197fa1aeb85a90` |
| [Root终态独核](E:/Mix/project/tire-info-manage-sys/.artifacts/native-cargo-jobs-root-audit-20261021/terminal-readback.json) | 3,250 | `2cca2790c01d96f72cbbc4d6e696a5ee929258acd98e11a8e97933d6b2f30b76` |
| [Root安全工具汇总](E:/Mix/project/tire-info-manage-sys/.artifacts/native-cargo-jobs-root-audit-20261021/tool-terminal-observation.json) | 6,315 | `93b2fc5d2d6210899c3e7ee0f431136ccfab97fc7ee833d90904ae99c2321390` |

[有限独审](E:/Mix/project/tire-info-manage-sys/.artifacts/native-cargo-jobs-review-20261021/terminal-review.md) SHA `aaff576b5d5dd786c4e4cca62fc81da57efb1de6bc1e88e067b7eef339a3814c` 只核回执/日志/6PID，未重跑全28,063项；[6PID回读](E:/Mix/project/tire-info-manage-sys/.artifacts/native-cargo-jobs-review-20261021/terminal-review.pids.json) SHA `9476c6d21c3ecf5b47dfd2e034d1673ce6feb48af530ca3eb9b1415bb90652d3`。Root辅助AST位置索引误报保留于 `reader-static-readback.json`，一次误用session号查进程保留于安全汇总；均非产品测试红，后者不作进程/cleanup证据。

## 保护与下一步

R102全量输入首尾保持与R101历史文件保持分别核验：Root重哈apply保护9项相同；本报告写前另重哈R101同一五份核心文件，均与R101末批绑定相同，不改旧结果。Root本次R38/S2原文件bytes/hash首尾相同，[保护回读](E:/Mix/project/tire-info-manage-sys/.artifacts/native-cargo-jobs-root-audit-20261021/protected-after-run.json) SHA `eacf61b4eed86503a48436544541041f4e4d22f98f4652906382e708d58928b9`，纯文件hash、无DB连接。更新前HANDOFF完整before为105,226 B/SHA `fe3c18280ec81cb588d8e31f10429df87d813abdacf99883a130670c4840d2ac`，原初稿/before不重写。

停在本次failed，不重跑本UUID、不改ACL/策略或放宽原门。下一由Root依既有用户授权独审/审定最小受管诊断，区分固定lld启动与Cargo/build-script/真实链接；任何诊断仅收窄观察条件，不能预称根因或修复。未新增真实材料/Provider/正常库/PG/Native设备验收；EPREL无Key不再问，Provider/export=false、V1 active，未commit/push。

[本轮文档应用回读](E:/Mix/project/tire-info-manage-sys/.artifacts/native-cargo-jobs-progress-20261021/docs-apply-readback.json)。
