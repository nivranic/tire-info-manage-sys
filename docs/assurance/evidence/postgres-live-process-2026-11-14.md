# PostgreSQL 真实来源进程与自然租约验收

日期为2026-11-14，基线为 `5f39c47`。本轮接续独立HTTP／Worker进程验收，补充真实来源成功路径和正常600秒租约的到期观察。

## 正式入口

`runtime-process` 增加显式 `-LiveSource` 与 `-NaturalLease`。LiveSource通过正常HTTP和独立Worker入口调用已登记的Hankook Adapter。NaturalLease在实际Worker终止后观察持久租约和HTTP任务状态，每10秒记录一次时间、状态及相同租约期限。

```text
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-process -CliTls -LiveSource -NaturalLease
```

原录制材料模式仍通过同一入口执行。其选项、结果状态与复跑命令见[此前进程验收](postgres-process-runtime-2026-11-14.md)。本轮沿用已有依赖与每批私有临时目录，服务使用非拥有者运行角色、TLS及受控空参考库生成的@4合同。

## 已取得的真实来源证据

首批真实模式 `pgverify-f6e7461d79fb40d1bf9882dc47d4dc96` 的9项检查通过。正常HTTP查询、Worker首次消费、中断恢复后消费及独立资产恢复后消费均返回live。该批使用隔离任务时间戳装配到期，后续自然期限批单独留证。

HTTP读取Ventus S1 evo3、205/45R17官方页面，得到产品代码 `1022631` 与 `1022632`。原件914627字节，SHA-256为 `7a232d444dec10491c85abe3f28724c1dd159d834127900f2112657bd9e5c18e`。完整原件保存在Git忽略的对象存储，公开记录保留身份与摘要。[Hankook官方页面](https://www.hankooktire.com/us/en/tire/ventus/s1evo3-k127.html)

在线请求使用既有固定来源Adapter、robots检查和直连传输。HTTP初始请求显式采用never回退策略，Worker沿用既有never策略。实际执行通过历史查询接口读取Parser选择和完成回执，核对子进程回收、退出码及bundle身份。入口保留LIVE_VERIFIED_304的协议检查分支，本轮4次在线业务结果均为live。

## 自然期限批

最终批 `pgverify-3bc29bcbd64c4f4980d30a87dbb4a290` 的9项检查通过，843个受测输入稳定。实际query_runs INSERT被测试锁阻塞且尝试进入running后，终止本轮Worker进程，随后每10秒读取原任务状态。

持久租约期限始终为 `2026-11-14T03:53:55.525800+00:00`。最初剩余599.786秒，实际观察601.859秒，共61次记录。末次状态由running转为result_unknown；重新启动正常Worker后，旧尝试形成interrupted，新尝试在线采集成功。

| 范围 | 最终结果 |
| --- | --- |
| 真实业务请求 | HTTP、Worker首次、中断恢复及独立恢复后共4次业务结果均为live，4份Parser完成回执均回收、退出码0 |
| 原件与SKU | 最终初始原件914625字节，产品代码1022631、1022632 |
| 数据库与资产恢复 | 166张模型表逐行摘要相同，3个原件文件及197个Parser资产文件逐文件摘要相同 |
| 服务收尾 | 9个API／Worker进程回收，3个HTTP端口关闭，运行角色后端连接关闭 |
| 旧模式兼容 | 录制材料及禁用来源模式9项通过，843输入稳定 |
| 相关受管回归 | 三模块55／55通过，跳过与不完整0，资源关闭、非自检拒绝0 |

最终初始原件SHA-256为 `c04e0ea097fbf8e7dc5617a3fd847aa301eed4ce179b1dfa0c6fb6cd04034523`。包内API源码摘要继续为 `e467c68763b69fdc5c12f5c8bd10432ae35676be47962fb5a35edb34f41dfda3`。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-3bc29bcbd64c4f4980d30a87dbb4a290/report.json` | `442edd31bc108f8f17aec7dbdf33d603bd217a45a7646ad6f421afe2688b575b` |
| 同批 `lease-observations.jsonl` | `30fa4f265f79616f16cde3be05d5df8071e483902af76ff855d50b43939fbad0` |
| `.artifacts/postgres/pgverify-65bbaae2a6654369ac61a880b2c6d644/report.json` | `850ec0706f80825494cc7973cf1962d68a793cb299a6cdc8557e788eff57db0a` |
| `.artifacts/postgres-live-process-20261114/regression-r1/result.json` | `6849d0ea26b12042d61f4ed41a6f7392f287e26e5a2faaa274bf70992b6a8faa` |

三个自建集群、临时口令、TLS私钥、端口及最终输入的收尾检查见 `.artifacts/postgres-live-process-20261114/closure.json`。本轮全部批次通过，原始回执分别保留。此前进程验收中的失败继续沿原记录追踪。

## 验收边界

当前来源范围为已登记的Hankook型号与尺寸。更多地区、来源、真实SKU和人工Golden继续按原规格实施。NaturalLease保留了原600秒期限，测试仍显式安排隔离规则到期以触发消费；自然长周期监控、真实变化提醒和通知lag继续验收。

服务中断与API收尾采用进程终止，服务管理器优雅停机、远端部署、生产IAM／RLS、灾备SLO、真实Responses／Embeddings、Native及其余发布Gate继续待验。
