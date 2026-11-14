# 生产Web短时中断自动恢复验收

日期为2026-11-14，实施基线为 `13c4c0ef31544b13a110dccada76cba1fad04b4c`。本轮补齐原页面在短时API中断后自动读回持久终态的证据。此前较长停机、手动读取、刷新及三种视口的结果见[已有Web恢复记录](web-ai-stream-recovery-2026-11-14.md)。

## 实际入口与材料

使用隔离PostgreSQL／TLS、非拥有者账户、批准的 `postgres-runtime-schema@4`、实际uvicorn及Next生产构建。私有驱动复用正式 `postgres_process_acceptance.run()`，以浏览器阶段替换原活动AI停机检查。基础进程检查沿用已有录制模式，参数来源为保存的Hankook资料，模型端为可等待及取消的合成Responses。

Chrome DevTools在隔离context内通过正常登录、历史检索、证据选择、外发同意及分析提交进入活动SSE。页面显示OpenAI Responses API及合成模型名称。默认配置与接入顺序继续依据用户选择采用OpenAI Responses。

复用BUILD_ID为 `fV1VrESoZp5ne3hWUeKqF` 的生产构建，422项构建输入逐项匹配。API源码摘要仍为 `cbbbb5de20e1a5bec37a8a6843da0f5fdf6e727a906ee62912b7c9640a85a061`，843项公共输入与此前已通过回归的输入清单一致。

## 自动恢复结果

| 检查项 | 实际结果 |
| --- | --- |
| 首次提交 | 页面勾选本次外发同意，分析POST共1次，HTTP202 |
| 活动连接 | SSE请求200，页面显示1条未完成校验的证据字段草稿 |
| 停机 | 隐藏控制台Ctrl+C，uvicorn采用2秒宽限，活动合成Provider关闭 |
| 重启 | 原API退出后自然等待2秒，同库同端口自动启动，退出至health就绪4.922秒 |
| 断线反馈 | 原页面显示连接中断，草稿降为0 |
| 自动读取 | 观察器记录原请求GET依次500、500、200，手动读取按钮点击0次 |
| 自动终态 | 断线至页面显示终态7.107秒，标题为“调用结果尚未确认，草稿已作废” |
| 持久核对 | 自动终态取得后追加只读GET，确认outcome_unknown／ai_stream_interrupted、terminal=true、projection_only=false |
| 结果与预算 | answer及usage为空，保留47,444 tokens预留、请求数1、has_pending_request=false |
| 防重复 | 原请求ID和幂等键一致，恢复期间新增分析POST为0，重启Provider调用0次 |

请求ID为 `3fa46ab7-0097-456b-8a6c-b1e72aaac366`。观察器每100ms读取一次DOM并仅保存状态变化，全部保存样本的visibilityState均为visible、手动读取次数均为0。先保存自动终态及网络时间线，再进行只读API核对，顺序已由本机断言脚本校验。

两次500来自API关闭期间的Next rewrite请求。保留原网络时间线后，页面按已有恢复逻辑继续读取同一记录。合成Provider停机前调用1次并关闭，重启后的Provider标记为calls=0、closed=0。

## 验证与收尾

PG进程12项检查通过，私有驱动退出0，843项输入稳定。另执行 `npm run test --workspace @tire/web`，59项全部通过。

14个服务记录均已回收，独立检查18个实际进程ID及8个端口。PG已停止，postmaster.pid、初始化口令、TLS私钥、临时登录脚本及Parser临时目录已清除，浏览器页面与隔离context已关闭。

采集时一次Node写入超过64,000字节限制，随后分段写入同一批已捕获内容。首次独立句柄检查中，沙箱对两个本轮进程ID返回WinError5，普通权限同脚本核对18个ID均已退出。原受限结果和采集修正留在本机私槽。

## 回执绑定

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-6cd55bfb45404aefbbf4af942402ed9a/report.json` | `a24a8220f96e33bb1af379a3ea909fa9f9fff269267735503840bb080b0c1c01` |
| `.artifacts/web-stream-recovery-20261114/r4/assertions.json` | `02df1665c18f8b9874451f6f9a21a7d41d40f6cf57fcea82a0222126236b9f61` |
| `r4/runner.py` | `ee0fd7211158c494adfe7aae4aa801d57afcab1b54f1dc8f36646b666e8b550f` |
| `r4/ui/terminal-before-get.json` | `39be4c269c8251b4edf1bef9641ea65a97e026774e2e1e45a4786ed63aee7306` |
| `r4/ui/readonly-verification.json` | `2548cdeda21493a011ec13396c1e214a87a673efcf65eb9ca31fae7cb810af35` |

表中 `r4/` 相对于 `.artifacts/web-stream-recovery-20261114/`。本机 `assertions.py` 校验DOM顺序、单次POST、自动GET、身份、持久终态、预算、输入绑定及资源关闭，并在 `assertions.json` 保存原始回执摘要。

新clone需要从正式PG进程入口重建隔离环境，按正常页面流程提交合成分析，在草稿出现后停止API，同库重启并保留原页面，记录自动GET和终态，再进行持久核对。恢复期间保持手动读取次数为0，重新核对Provider及POST计数，结束后核对资源关闭。

## 接续范围

真实OpenAI Responses／Embeddings网络、语义和费用继续待验。公网Webhook DNS／TLS与接收端部署、其他停机宽限、服务管理器、Linux信号、远端部署、长期监控、Native设备及完整WCAG继续推进。录制ParserRunError具体错误码与Windows间歇打开延迟仍需原始证据。
