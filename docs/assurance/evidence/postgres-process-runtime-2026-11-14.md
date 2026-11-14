# PostgreSQL 独立 HTTP 与 Worker 进程验收

日期为2026-11-14，基线为 `eb2db74`。本轮接续Windows缺省架构修正，补充正常uvicorn与独立Worker进程的部署、环境传播和恢复证据。完整V1持续实施。

## 实施内容

新增 `scripts/postgres_process_acceptance.py`，并将 `runtime-process` 接入既有 `scripts/verify-postgres.ps1`。正式入口要求TLS，在全新私有集群内创建独立空参考库、目标库及非拥有者运行账户。空参考库生成源码绑定的 `postgres-runtime-schema@4`，独立目标库完成迁移后应用现有运行角色策略。

API通过 `python -m uvicorn tire_api.main:app` 监听空闲loopback端口，Worker通过 `python apps/worker/monitor.py --once` 启动。服务子进程仅接收运行凭据、显式合同和资产目录，架构环境变量缺省。实际PostgreSQL会话核对了运行账户及TLS。

原件通过既有RecordedRegistry与QueryService装入隔离库，采用仓库已有Hankook录制片段。HTTP评估重放封存Parser包，核对候选和对照的子进程回收、退出码、bundle身份及零字段差异。Worker显式配置禁用来源，检查持久队列中的 `source_unavailable` 结果和终态。

## 最终结果

| 验证范围 | 实际结果 |
| --- | --- |
| 独立进程PG／TLS专项 | 9项通过，843个受测输入稳定 |
| 正常HTTP | 注册、会话、原件读取、Parser评估、重启后事件及cursor恢复通过 |
| 实际进程 | 9个API／Worker进程均已回收，3个HTTP端口关闭 |
| 中断恢复 | 在实际query_runs INSERT锁等待和running任务阶段终止Worker，租约到期后旧尝试记为interrupted，新尝试正常形成终态 |
| 合同反例 | 实际API和Worker进程均拒绝错误合同摘要 |
| 独立备份恢复 | 166张模型表逐行摘要一致，1个原件文件和197个Parser资产文件逐文件摘要一致 |
| 恢复后消费 | 原资产目录移到本轮离线槽，API从备份目录读取原件和执行封存Parser，Worker继续消费同一规则并形成第4次尝试 |
| 相关受管回归 | schema启动、任务状态和Worker三个模块55／55通过，跳过与不完整均为0，资源关闭、非自检拒绝0 |

最终PG回执为 `.artifacts/postgres/pgverify-bd279d124a2444adbb3c3c1ce15c37f1/report.json`，SHA-256为 `217bc6d0dc0f4e9ef95542f14408c9cc9808593a9dbf7fc15410d1cb89b4e983`。

最终受管回归为 `.artifacts/postgres-process-runtime-20261114/regression-r2/result.json`，SHA-256为 `ef6d477ad145ee84f8055b6c5f0426c6531e44f3255ba624f7ddb9c0951b7c70`。843个受测输入稳定，真实Provider及接收端调用为0。包内API源码摘要仍为 `e467c68763b69fdc5c12f5c8bd10432ae35676be47962fb5a35edb34f41dfda3`。

## 原始失败与定位

1. `pgverify-3c0283badcb24db0a8953e9d4765149a` 在中断装配处失败。后续 `pgverify-c2fa8985b33a40e3985a5b5bebf3f8b0` 补取等待语句，观察到启动schema游标的FETCH被ACCESS EXCLUSIVE锁阻塞，任务仍只有此前1次尝试。将装配锁改为SHARE后，启动读取通过，实际阻塞位置成为query_runs INSERT，任务第2次尝试处于running。
2. `pgverify-201705e2517d4a3db735e8c5db2e07a1` 已完成恢复后消费，在立即断言PostgreSQL后端数量为0时失败。最终入口在实际进程退出后，限时10秒观察同一运行角色的后端连接关闭。最终批恢复阶段先观察到1个后端，随后确认关闭。
3. `regression-r1` 为54／55通过。独立诊断取得CaptureWriteError、ObjectStoreError及os.link处PermissionError的异常链。原源码和相同测试清单在正常执行权限下复跑为55／55通过。原件原子发布逻辑沿用既有实现。

原始失败、诊断和最终回执均保留在Git忽略目录。各批隔离集群、临时口令及TLS私钥的收尾核对见 `.artifacts/postgres-process-runtime-20261114/closure.json`。

## 复跑

准备已有PostgreSQL运行时和已安装API开发依赖，选择空闲loopback端口，使用PowerShell 7执行。

```text
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-process -CliTls
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_monitor_tasks.py apps/worker/test_monitor.py
```

本轮通过进程级 `UV_OFFLINE=1`、`UV_NO_SYNC=1` 和Git忽略目录中的 `UV_CACHE_DIR` 复用已安装依赖。wrapper设置每批私有TEMP／TMP／TMPDIR，并在退出时恢复自身进程环境。

## 待验范围

本轮材料为录制片段，Worker结果为显式禁用来源后的不可用终态。中断采用进程终止，租约到期由本轮拥有者调整隔离任务时间戳，API服务收尾也采用进程终止。真实来源成功采集、自然600秒租约到期、服务管理器优雅停机、远端部署及生产SLO继续验收。

备份范围为本轮完整模型数据、文件系统原件与封存Parser包。pgvector、S3、报告导出等能力继续参考此前各自验收，本轮未重新覆盖。生产IAM／RLS、全平台设备、真实Responses／Embeddings及其余发布Gate继续按完整需求推进。
