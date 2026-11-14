# Webhook实际HTTPS取消与自然租约恢复

日期为2026-11-14，实施基线为 `285a5f129534fe2b81642b7fbb97d99e95c347be`。本轮接续合成发送协程取消回归，验证独立Worker、真实TLS连接和持久队列之间的恢复行为。[此前取消回归](active-http-ai-shutdown-2026-11-14.md)

## 入口与测试注入

正式PG wrapper建立一次性PG18／TLS、非拥有者运行账户和批准@4合同。私有驱动复用 `postgres_process_acceptance.run()`，在最后阶段运行Webhook专项。实际uvicorn服务经原查询、监控规则、Webhook订阅和取消接口产生通知及outbox，独立进程执行原 `monitor.main()` 的 `--webhooks-once` 模式。

参数材料采用现有合成FixtureRegistry，前后两次正常查询形成变化。发送沿用 `WebhookTransport.send`、生产签名函数、8秒总期限、禁止重定向和环境代理读取关闭配置。接收端为直接绑定loopback的HTTPS服务器，使用本批PG测试证书链，实际客户端校验主机名及CA。

验收进程显式注入三处测试配置。

- Catalog提供本批本机HTTPS目标和临时签名密钥。
- 发送模块的endpoint检查只接受本批精确loopback URL。
- aiohttp connector采用本批测试CA的SSLContext，check_hostname=true、verify_mode=CERT_REQUIRED。

注入前调用原生产endpoint检查，确认该loopback URL被拒绝。此测试连接采用IP字面量，公网域名及PublicResolver的实际DNS链路继续待验。本轮密钥取自临时进程环境。

## 两种实际网络场景

| 阶段 | 普通投递取消Worker | 用户先取消投递，再取消Worker |
| --- | --- | --- |
| 原API入队 | 变化通知与outbox经正常事务产生，唯一delivery进入pending | 第二条变化独立形成新delivery |
| 接收端收到 | 第1次HTTPS POST完成独立HMAC及正文核对，响应保持等待 | 第1次POST同样完成独立核对 |
| 取消 | 本轮隐藏控制台收到CTRL_C_EVENT，接收端观察到TLS连接关闭 | 原取消API先成功，再发CTRL_C_EVENT，接收端观察到TLS连接关闭 |
| 租约到期前 | 新Worker执行结果jobs=0，未追加网络发送，原尝试无完成记录且保留global slot | 状态cancelled，原尝试及slot保留到原期限，jobs=0 |
| 原30秒租约自然到期 | 新Worker追加unknown／webhook_lease_expired，无HTTP状态码，队列进入pending | 同样追加unknown，队列保持cancelled且next_attempt_at为空 |
| 后续 | 自然等待原60秒退避，第二次发送沿用delivery ID及正文，attempt=2，最终204／delivered | 后续Worker仍为jobs=0，接收端累计仅1次请求 |
| 旧token | 到期后的迟到204被拒绝；第二次发送持有新slot时，旧token仍被拒绝且新slot保持有效 | 到期后的迟到204被拒绝，取消状态保留 |

接收端共取得3次TLS 1.3请求，全部独立HMAC核对通过。普通投递的两次正文SHA-256均为 `a099b87f984a733840c45b9ca35cb839a2d791c4fc76c1502003694bf62dafee`。正文严格为9个通知引用字段。

两次中断Worker的实际退出状态均为 `3221225786 / STATUS_CONTROL_C_EXIT`，本轮观察到的控制台退出耗时约0.266及0.250秒。句柄已回收，接收端取得连接关闭证据。既有受管协程取消测试继续覆盖发送finally及事务状态。

## 自然时间及回归

本轮使用实际UTC时钟等待原30秒租约和60秒退避。两次租约等待各保存56个UTC样本，退避等待保存121个样本，共233个样本。原尝试lease_until严格为started_at加30秒，重试next_attempt_at严格为未知完成时间加60秒。

等待阶段在取消和到期前探测之后开始，记录的单调时钟时长分别为27.172、59.547及27.125秒。各UTC样本均跨过原持久期限。

回执核验器首轮将独立的单调时钟时长与UTC剩余时长作严格大小比较，出现约5.8–9.4ms差异。现分别保留两种观察值，并依据原UTC期限及其前后样本核对租约，原差异保存于clock-comparison.json。PG业务回执保持原始结果。

两个Webhook模块 **142／142受管回归通过**，跳过及不完整0，843项公共输入稳定、资源关闭、非自检拒绝0。PG进程 **12项检查通过**，原目标URL、DNS重绑定、TLS设置、权限、签名、幂等、取消和重试反例继续保留。

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_webhooks.py apps/api/tests/test_webhooks_review.py
```

## 收尾与回执

20个服务进程记录均已回收，HTTPS监听线程关闭。独立核对8个端口可绑定、集群postmaster.pid已移除、初始化口令文件及TLS私钥已移除、Parser临时目录已清除。公开源码与142项回归的前后清单逐项一致。

| 本机Git忽略回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-2814de306191447ea5e19af58c704abe/report.json` | `6186a2893a504d12c9578ccaebccbd68ec7aee27fdd91da8cdc9828272c0ca7b` |
| `.artifacts/webhook-network-20261114/regression-r1/result.json` | `89c8e3b279e6c9cc2c5c229d3c1fe2a3e5e184fca9908c10962730b04149c517` |
| `.artifacts/webhook-network-20261114/r1/verification.json` | `a99f194e63c2b6abb8460f0709eaf8fbfa74e55c1513bdc37cb75102ea4915b4` |
| `.artifacts/webhook-network-20261114/r1/runner.py` | `acddce6d0212b491ab83bff60f2d5616f3f08ab738960edaef93964b3b35e5c2` |
| `.artifacts/webhook-network-20261114/r1/network_runtime.py` | `0b928216d5dfa2c12306c72191d4684657b2e9ed6906a3068bd9db8bce606c0b` |
| `.artifacts/webhook-network-20261114/r1/clock-comparison.json` | `44dd119b67d1f243ee74f9837829c402db37935f70ad8ddf0aab8ecfe8a003e6` |

同机接手可核对r1私有驱动、CA注入、接收端及原回执。新clone按正式PG入口及上述测试注入与场景重建隔离环境。

## 接续范围

继续公网受控接收端、真实DNS与TLS部署、远端IAM及吞吐、短断线Web自动恢复、真实OpenAI Responses／Embeddings、其他停机配置、Linux与长期真实监控。生产Webhook的正常lag≤5min仍需代表性运行证据。完整V1各模块、Gate与设备验收继续独立跟踪。
