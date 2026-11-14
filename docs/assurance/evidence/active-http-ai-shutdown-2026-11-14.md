# 活动HTTP／AI流停机与Webhook取消恢复验收

日期为2026-11-14，基线为 `6f866a3`。本轮接续[活动Worker验收](active-worker-shutdown-2026-11-14.md)，验证活动HTTP订阅、AI生产任务与持久化结果之间的停机顺序。

## 实际入口与范围

正式 `runtime-process` 入口新增一项检查。服务由uvicorn CLI启动，验收专用ASGI factory调用已有 `create_app`，使用原API路由、lifespan、非拥有者PG账户、TLS及批准@4合同。factory在模型适配器注入点安装合成的Responses生产任务，生成一条绑定事实的草稿后持续等待。

本轮测试明确设置 `--timeout-graceful-shutdown 2`。独立HTTP客户端保持真实SSE订阅，收到accepted、started及claim_draft后确认连接仍活动，再向本轮隐藏控制台发送Ctrl+C。宽限到期后uvicorn取消活动ASGI请求，lifespan关闭AI生产任务并写入终态。

另一个独立API进程从同一PG库读取结果，经原cursor恢复事件，并以原UUID重放POST。接入配置形状为 `openai_responses`，模型端采用验收factory中的合成实现。

## 验证结果

| 检查 | 实际结果 |
| --- | --- |
| 七模块受管回归 | 220／220通过，跳过与不完整0，843输入稳定，资源关闭，非自检拒绝0 |
| 录制模式PG／TLS | 12项通过，包含活动HTTP／AI流停机及重启读取 |
| 真实来源PG／TLS | 正式复跑13项通过，包含运行中Worker取消、活动HTTP／AI流与恢复 |
| 停机前 | 1条草稿，执行状态running，SSE订阅活动，合成Provider调用1次且尚未关闭 |
| 停机后 | SSE连接关闭，生产任务finally执行，Provider关闭1次；API与启动器正常退出0 |
| 持久结果 | outcome_unknown／ai_stream_interrupted，projection_only=false，answer与usage为空，展示草稿清空 |
| 重启及预算 | 原cursor取得单条outcome_unknown事件，原UUID重放200且replayed=true，重启Provider调用0次，保留原预算占用且pending=false |

录制／真实来源两批活动API停机样本约2.750／2.609秒。SSE客户端记录RemoteProtocolError，服务日志记录停机宽限到期取消请求及Application shutdown complete。上述行为对应本轮2秒宽限配置。

成功两批29个受管服务记录回收，18个实际控制台进程句柄核对。三个本轮集群、18个端口、临时口令／TLS私钥和Parser临时目录均已核对收尾。两批分别恢复166张模型表、197个Parser资产及1／3个原件。

### Webhook取消恢复

新增两例经过正常订阅与通知入口的受管回归，分别覆盖Worker取消，以及用户先取消投递后Worker取消。

- 发送协程收到取消后执行finally，单次调用与关闭计数均为1。
- 已开始的HTTP尝试在原租约内保持未确认状态，global slot继续由原token持有。
- 租约恢复后追加unknown／webhook_lease_expired，无HTTP状态码，旧token的迟到204无法覆盖该结果。
- 正常投递按既有退避恢复，delivery ID保持一致，attempt编号为2。用户已取消的投递保持cancelled。

这些用例采用合成发送适配器及显式时钟装配，验证真实SQLite事务、API动作和队列逻辑。Webhook的实际网络取消、自然30秒租约、独立Worker及公网接收端仍待验。

## 原始失败与定位

首批受管回归为218／220通过，两个旧022迁移断言失败。独立私库探针取得额外12个关系，分别为source_text_fts、document_text_fts及各自五个SQLite内部表。

原夹具采用当前模型结构及pre-022版本账本，仅创建了知识检索FTS。现显式调用两种正文检索初始化函数，并在夹具说明中标明当前形状。旧行、旧结构、幂等、回滚及精确新增表断言继续参与最终220项回归。

此前录制来源首批source_fetch_failed的原始异常继续待查。正式进程验收现使用RecordedRegistry的诊断子类，保存原异常类型及安全栈位置，并记录种子查询状态。诊断通过已有safe_exception实现，省略异常消息、局部变量与参数。当前录制批种子查询为live。

本轮真实来源首批回执为 `.artifacts/postgres/pgverify-4be61b5aafc4498bbc7cbc3841375993/report.json`。首次HTTP查询及Parser评估通过，随后Worker收到upstream_timeout并正常写入失败终态。原始日志及回执保留，按原入口等待30秒后直连复跑。

随后同源码复跑13项通过，5次真实Hankook业务结果为live，Parser回执均完成回收。来源长期可用性及生产SLO继续独立验收。

## 回执与源码

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-184154458b8f4aceb054fe6028953231/report.json` | `20f164fd71e0cdd1288e98a40037a9a847bc47abfd14a14445be4bb5d907557d` |
| `.artifacts/postgres/pgverify-0890c1a44b5a4785bf741d0f7a2371e2/report.json` | `39713fc50e100f9aec2626b4491d80882e5df59d93ec41998cdd7de67be311f0` |
| `.artifacts/postgres/pgverify-4be61b5aafc4498bbc7cbc3841375993/report.json` | `1a4f9a1fea23e14b891b14c16ce3a8056d3534862a4d53bea17d4101a2997489` |
| `.artifacts/active-ai-shutdown-20261114/regression-r2/result.json` | `50d7946915a4363bf3f6337d4a7b607c78b7386b8dce47c6cc7bbbe4f4b1df5b` |
| `.artifacts/active-ai-shutdown-20261114/regression-r1/result.json` | `a3056f7308c84266d0e17bdbbda1a2cbb71c153c90401ef2e9e87931554aa858` |

私槽保存FTS差异探针、完整输入清单、`closure.json`及 `failed-live-closure.json`。220项回归的前后清单及交付源码逐项一致，两份成功PG回执各843输入稳定。API源码摘要为 `cbbbb5de20e1a5bec37a8a6843da0f5fdf6e727a906ee62912b7c9640a85a061`，两模式PG18空参考@4合同摘要均为 `24edf9519b28945cf934353eb8d52dce500c430335228af9ede731f6aa200b30`。

## 复跑与接续

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_webhooks.py apps/api/tests/test_webhooks_review.py apps/api/tests/test_ai_stream_execution.py apps/api/tests/test_ai_stream_api.py apps/api/tests/test_schema_startup.py apps/worker/test_monitor.py apps/worker/test_telemetry_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-process -CliTls
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-process -CliTls -LiveSource
```

接续实际Web界面的断线恢复、真实OpenAI Responses网络／语义与费用、活动Webhook网络、默认及其他宽限配置、服务管理器、Linux信号、远端部署和长期真实变化。完整V1的12模块、10 Gate、13 SLO及15项决策继续分别跟踪。
