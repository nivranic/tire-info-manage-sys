# 运行中 Worker 取消、终态与重启验收

日期为2026-11-14，代码基线为 `c8b1aac`。本轮接续[控制台停机验收](windows-service-shutdown-2026-11-14.md)，覆盖已领取任务的取消收尾与重启消费。

## 原始失败与修正

正式PG／TLS进程入口在Worker已写入running后，以本轮 `query_runs` SHARE表锁阻塞业务INSERT，再向本轮隐藏控制台发送Ctrl+C。修改前进程退出后，尝试仍为running，租约仍占用。原始回执为 `.artifacts/postgres/pgverify-ffcc7b278c2f433abe63a9fedcbd5a21/report.json`。

轮胎、召回和召回发现周期现捕获 `asyncio.CancelledError`，调用各自已有的完成事务并重新抛出取消。Safety Gate复用已有取消入口。轮胎的lease_lost结果改用已有中断事件，记录 `interrupted`、`lease_lost` 与 `worker_cancelled`。

四类队列在该取消组合下保留原 `next_due_at`，释放自己持有的租约。原先完成入口会把任务推到下一监控周期。若租约已被后来接手者替换，既有fencing保护后来的租约与到期时间。

新增参数化回归经正常规则API创建任务，覆盖四类队列及自身／替换租约两种状态，共8例。断言终态、单条中断Run、自身租约释放、原到期时间和后来接手者租约。

| 专项阶段 | 实际结果 |
| --- | --- |
| 原取消反例 | 2通过、6失败，Safety Gate两例原已通过 |
| 加入取消收尾后 | 8通过 |
| 加入到期时间断言 | 4通过、4失败，自身取消被错误重新排期 |
| 当前修正 | 8通过，跳过与不完整均为0 |

## 最终验证

| 范围 | 实际结果 |
| --- | --- |
| 八模块受管回归 | 159／159通过，跳过与不完整0，843输入稳定，资源关闭，非自检拒绝0 |
| 真实来源PG／TLS进程 | 12项通过，含运行中Worker取消及重启成功消费 |
| 录制模式PG／TLS进程 | 串行复跑11项通过 |
| 真实业务结果 | 5次Hankook业务查询均为live，5份Parser完成回执均回收且退出0 |
| 活动取消 | 第5次尝试由running转为interrupted，原因worker_cancelled，租约清空，原到期时间保持 |
| 重启消费 | 遵守既有来源间隔后，第6次尝试成功，全部尝试为终态 |
| 独立资产恢复 | 两模式均核对166张模型表、197个Parser资产；真实模式3个原件、录制模式1个原件 |
| 资源收尾 | 成功两批25个受管服务记录回收，10个实际控制台进程句柄核对；四个本轮集群、20个端口及临时口令／TLS私钥核对关闭 |

实际活动Worker的控制台退出值为Windows的 `0xC000013A`，本机取消退出样本约2.125秒。API正常停机仍退出0。

活动PG检查显式安排隔离测试规则到期，并持有本轮表锁。Verifier的解锁线程在Ctrl+C期间释放该锁，且结束时已join。重启前直接采用取消后保存的到期时间。该场景的活动边界为数据库INSERT等待，活动网络／AI流与Webhook取消继续独立验收。

### 回执摘要

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-6549f2c26fdd4be6bd6ebf3685bc92c7/report.json` | `ef40810a5af68dbb7c29c0d9ae6797d7dd6da86924bbcb43413895214cb8054f` |
| `.artifacts/postgres/pgverify-0194183e644b43d0912e741ccbed7d00/report.json` | `000721ffd49cf54be8e00739774512dae565a29aa616ef731db3b4d7058bbea8` |
| `.artifacts/active-worker-stop-20261114/regression-final-elevated/result.json` | `6d750de1db809e327b587844d7b1f4fea7f764d853c79211264e559badf5b2bc` |
| `.artifacts/active-worker-stop-20261114/before/result.json` | `a0b3f9678bd1e19d863516f45b04ec56eb9be24f0ca07cd7e68e9e3370a32932` |
| `.artifacts/active-worker-stop-20261114/before-retry/result.json` | `eedd93c256cc3f93ae7f94eb149406fdebb7498206ea152a4018523e3b294723` |
| `.artifacts/active-worker-stop-20261114/after-retry/result.json` | `fc70dd1087e0cc82107f1d56b58dd98734478590f9ac7ffc96e49b32ac07947b` |

`.artifacts/active-worker-stop-20261114/closure.json` 保存回执摘要、输入清单比较、合同、集群、端口及资源收尾结果。159项回归的前后清单与交付源码逐项一致。两份PG回执的843输入稳定，包内源码摘要与交付代码一致。

## 新源码与部署合同

本轮API源码变化，正式PG入口已分别从新空参考库生成 `postgres-runtime-schema@4` 合同。两模式取得相同结果。

- API源码SHA-256为 `cbbbb5de20e1a5bec37a8a6843da0f5fdf6e727a906ee62912b7c9640a85a061`。
- 本轮PG18参考合同SHA-256为 `24edf9519b28945cf934353eb8d52dce500c430335228af9ede731f6aa200b30`。
- 参考合同包含167个普通关系，模型表恢复计数为166。

上述摘要标识本轮隔离环境。实际部署继续依据目标major、locale、扩展和可信源码生成并批准合同，操作见[运行启动说明](../../POSTGRES-RUNTIME-SCHEMA.md)。

## 本轮其他失败与待查项

1. 首轮综合受管回归为122通过、37失败。合成数据库记录了原件采集失败；最小 `os.link` 探针在受限执行下返回PermissionError／WinError 5，正常权限下成功。相同843输入在正常权限下159项全部通过。原始回归和两份探针回执继续保存。
2. 录制PG首批在种子查询断言失败，回执为 `.artifacts/postgres/pgverify-04d64f2d98824b96a7a5628d5f22dc90/report.json`。对已关闭的本轮合成库进行单用户只读诊断，取得QueryRun的 `source_unavailable/source_fetch_failed`、Parser的 `not_started/source_fetch_failed` 和1条RawCapture。业务层已将原异常归一化，具体原始异常根因待查。随后沿相同源码和正式入口串行复跑11项通过。
3. 原始取消PG失败、两次参数化反例、受限权限回归、录制PG失败和单用户诊断的列名装配错误均保存在私槽。收尾已核对这四个集群的进程标记、服务端关闭日志、端口及临时秘密。

此前600秒自然租约的61次观察沿[原记录](postgres-live-process-2026-11-14.md)保留。本轮采用隔离到期装配。服务管理器、Linux信号、远端部署、自然长周期真实变化、生产SLO、实际Native／设备与完整V1 Gate继续待验。

## 复跑入口

使用PowerShell7及全新Git忽略输出槽。

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_monitoring.py apps/api/tests/test_monitor_tasks.py apps/api/tests/test_recall_monitoring.py apps/api/tests/test_recall_discovery_monitor_execution.py apps/api/tests/test_safety_gate_monitoring.py apps/worker/test_monitor.py apps/worker/test_telemetry_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-process -CliTls -LiveSource
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-process -CliTls
```
