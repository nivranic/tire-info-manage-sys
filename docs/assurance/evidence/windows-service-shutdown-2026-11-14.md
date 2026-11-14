# Windows API与空闲Worker控制台停机验收

日期为2026-11-14，基线为 `26747b9`。本轮接续真实来源与自然租约验收，补充Windows正常服务入口的Ctrl+C停机证据。

## 实施与范围

`scripts/postgres_process_acceptance.py` 在既有9项检查后增加API和空闲Worker两项控制台停机检查。API沿用 `python -m uvicorn tire_api.main:app`，Worker沿用 `python apps/worker/monitor.py --interval 10 --metrics-port <private-port>`。

服务由本轮创建的隐藏控制台承载。验收进程先分离自身的宿主控制台，再附加本轮服务控制台，核对控制台成员并持有启动器与实际服务进程的句柄。Ctrl+C送达后逐一等待进程句柄，记录退出码，并核对API lifespan完成、Worker取消路径、指标端口和PostgreSQL后端关闭。

服务继续使用非拥有者运行账户、TLS、受控空参考@4合同及本轮私有资产目录。新增Worker停机检查在一次空队列周期完成后发出Ctrl+C。

## 最终结果

| 范围 | 实际结果 |
| --- | --- |
| 真实来源PG／TLS | 11项通过，包含4次Hankook在线业务采集、恢复及两项控制台停机 |
| 录制材料PG／TLS | 11项通过，包含既有禁用来源终态及两项控制台停机 |
| API退出 | 两批均记录Application shutdown complete，启动器和实际服务进程退出码均为0 |
| 空闲Worker退出 | 两批均进入asyncio取消及KeyboardInterrupt路径，启动器和实际服务退出值为Windows的0xC000013A |
| 资源收尾 | 两批各11个受管服务记录已回收，控制台两项额外核对了4个实际进程句柄；HTTP／指标端口及运行账户PG后端关闭 |
| 相关受管回归 | schema、任务、Worker和遥测四模块75／75通过，跳过与不完整0，资源关闭、非自检拒绝0 |

真实批API／Worker停机分别约0.657／0.375秒，录制批约0.703／0.469秒。计时为本轮本机样本。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-4985c824fadc44e9973a0e3e20a346d6/report.json` | `bcc018bbdbbe04e143e739d42f3b93ead40b4d625186a855a2674d1fefa27033` |
| `.artifacts/postgres/pgverify-6c9175b4fdda49b5af6b53ae5019244f/report.json` | `ec3b307ed6da81429d8aa30dd657b1e638054d70492cb6948def23fcdc5553fc` |
| `.artifacts/graceful-process-20261114/regression-r2/result.json` | `ee805c94bd7c07b1dcdca75b4f87cdae9a3bd372868787fc419f9252cf4fd5c9` |

PG批次执行期间843输入稳定。随后仅调整旧遥测测试的数量断言，最终75项回归的843输入稳定。API源码与进程验收脚本在PG批次和最终交付间一致；两份清单逐项比较及资源关闭结果保存在 `.artifacts/graceful-process-20261114/closure.json`。包内API源码摘要为 `e467c68763b69fdc5c12f5c8bd10432ae35676be47962fb5a35edb34f41dfda3`。

## 原始失败与定位

1. `probe-r1` 的Worker指标就绪路径写错；API就绪读取遇到连接超时。该批在发送信号前中止，原始结果和日志保留。
2. `probe-r2` 在AttachConsole处返回Windows错误5。只读GetConsoleProcessList证实宿主有3个控制台成员，同时GetConsoleWindow返回空。后续先分离验收进程自身，`probe-r3` 成功对两个新建的隐藏控制台发送Ctrl+C并核对全部服务进程句柄。
3. `regression-r1` 为74／75通过。独立空队列诊断取得4个idle周期span，旧断言仍为3，遗漏已接入的Safety Gate周期。仅修正数量和说明，原无任务、无外部调用、父子trace及空指标检查继续参与最终回归。

上述原始失败、诊断和最终回执均保留在Git忽略目录。三个探针批次的端口及两个PG集群、临时口令、TLS私钥均已核对收尾。

## 复跑与待验

```text
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-process -CliTls -LiveSource
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_monitor_tasks.py apps/worker/test_monitor.py apps/worker/test_telemetry_monitor.py
```

本轮覆盖Windows控制台、正常API收尾及空闲Worker的Ctrl+C退出。运行中任务、活动HTTP／AI流、SCM／systemd等服务管理器、Linux信号与远端部署继续验收。此前600秒自然租约证据沿[原记录](postgres-live-process-2026-11-14.md)保留；自然长周期真实变化、多规则提醒、生产SLO、Native及其余Gate继续按完整需求推进。
