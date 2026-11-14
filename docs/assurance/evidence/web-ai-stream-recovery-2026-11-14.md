# 真实Web界面的AI停机恢复验收

日期为2026-11-14，实施基线为 `4a54531595d8e81895c55515f19a04557451983e`。本轮接续此前浏览器驱动登录装配失败，验证生产Web经过API停机、同库重启及页面刷新后的恢复行为。[前置失败与Provider复核](provider-handoff-review-2026-11-14.md)

## 实际入口

本轮使用隔离PG18／TLS、非拥有者运行账户、批准的 `postgres-runtime-schema@4`、实际uvicorn进程及Next生产构建。Chrome DevTools控制独立浏览器context，经正常Web页面完成历史检索、证据选择、外发同意和分析提交。参数来源采用已有Hankook录制资料，模型适配器采用可等待及取消的合成Responses实现。

私有驱动复用正式 `postgres_process_acceptance.run()`，在 `active_ai_shutdown` 注入浏览器交互阶段。它包装原 `accepted`，在本轮正常合成注册成功后，从该注册请求取得实际用户名和随机口令到内存，继续调用原实现。浏览器随后通过原登录接口取得200及authenticated=true。登录动作文件在finally中清除。

生产构建BUILD_ID为 `fV1VrESoZp5ne3hWUeKqF`，422项构建输入与当前源码逐项一致。PG进程报告记录843项输入稳定，收尾再次核对其与已通过75项回归的输入清单一致。API源码摘要为 `cbbbb5de20e1a5bec37a8a6843da0f5fdf6e727a906ee62912b7c9640a85a061`。

## 页面与后端结果

| 场景 | 实际证据 |
| --- | --- |
| 准备证据 | 正常历史检索命中2条记录，选择1条结构化证据，准备31个字段；外发同意初始未勾选，提交按钮禁用，分析POST为0 |
| 首次提交 | 通过页面勾选本次外发同意并提交问题，分析POST为1、HTTP202，页面显示OpenAI Responses API及合成模型名称 |
| 活动SSE | 原页面收到1条证据字段草稿，连接文案为已连接分析进度，实际events/stream请求200 |
| API停机 | 向本轮隐藏控制台发Ctrl+C，uvicorn采用2秒宽限；日志记录宽限到期取消请求及Application shutdown complete |
| 页面断线 | 页面显示进度连接中断与HTTP500，临时草稿数量降为0；Next正常rewrite在API关闭期间返回500 |
| 同库重启 | 重新读取进度按钮恢复原请求，持久状态为outcome_unknown／ai_stream_interrupted，terminal=true、projection_only=false，answer和usage为空 |
| 预算 | 保留1次请求及47,433 tokens预留，has_pending_request=false；页面进行中提示清除 |
| Provider计数 | 停机前调用1次、关闭1次，重启后调用0次；恢复前后的原页面分析POST总数为1 |
| 刷新恢复 | 页面刷新后重新打开AI分析，使用原幂等键和请求ID只读恢复，事件cursor由序号1推进至4；该页面生命周期的分析POST为0 |
| 视口核对 | 390×844、768×1024、1440×900均恢复同一请求、草稿为0、分析POST为0，文档与对话框内容无横向溢出 |

此次停机持续到自动读取尝试用尽后才重启，恢复动作使用页面的“重新读取进度”按钮。页面刷新后的恢复由原会话恢复指针触发。较短中断期间的自动恢复仍需另行验收。

当前请求ID为 `f1683da2-2dbe-41a9-9cae-4d60990f9898`。后端原UUID重放证据继续引用此前独立HTTP验收，本次页面通过GET读取原记录。[活动HTTP／AI流记录](active-http-ai-shutdown-2026-11-14.md)

## 收尾与采集修正

本轮PG进程12项检查全部通过，14个服务进程记录均已回收。独立核对8个端口可绑定、集群postmaster.pid已移除、初始化口令文件及TLS私钥已移除、临时登录脚本及Parser临时目录已清除。浏览器context已关闭，页面仿真配置已复原。最后一次页面导航后的error／warn控制台列表为空，停机期间的500保留在断线记录中。

首轮视口采集在仿真配置切换后直接读取旧对话框，取得空选择器。后续经页面命令面板重新打开原分析后完成三种视口核对。截图与布局记录保存在本轮Git忽略槽，原始截图字节另行核对SHA-256。

## 回执绑定

完整字段断言、输入绑定、端口及秘密收尾由本机 `r3/assertions.py` 执行，结果为passed=true。该脚本核对7组浏览器场景及3种视口，并在结果中保存所有输入回执与截图摘要。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-04d9a389335f4395a57f42178d9c95f6/report.json` | `45f90b26713b8952f6a44799274d91fe3c2c21fa7fd906c39354f5e71a9164e8` |
| `.artifacts/web-stream-recovery-20261114/r3/assertions.json` | `a436f8ae5f2ec5cf4dbb35a7e9609669697f4ce9eab97a5083865a833d321273` |
| `r3/runner.py` | `cb01b5e08247570e0c61795400191fbe1130790bbb026fbf39aa0b5ebfb13f5f` |
| `r3/ui/recovered.json` | `17dd9a24a7497230f7616d63ff3fe0337274eea9ed68184dc915f0277ade4612` |
| `r3/ui/after-reload.json` | `021c95175d9db9bc4789ac9d4e897614a2493d14f06637aaf88b8fbcfb090d0f` |
| `r3/ui/phone-recovered.png` | `611f456d61afdf6793a1dbe0b8234ff123363ea5e3a0700bdd13be706cdbb6b9` |
| `r3/ui/wide-recovered.png` | `cc354f5d3d51ae16750a178775f6e539a05deaaf001237e88baa621ba81290df` |

表中的 `r3/` 均相对于 `.artifacts/web-stream-recovery-20261114/`。同机可核对私有驱动与回执，新clone需要依照正式PG入口和上述页面步骤重建隔离验收。

## 接续范围

继续实际OpenAI Responses／Embeddings网络、语义及费用验收，短时断线自动恢复、Webhook实际网络取消与自然租约、其他停机宽限、服务管理器、Linux、远端部署和自然长周期监控。录制来源此前ParserRunError的具体错误码与OS间歇延迟继续取证。

本次视口证据覆盖Chrome中的生产Web页面。Native宿主、六平台设备E2E、完整WCAG和其余V1 Gate继续逐项建立证据。
