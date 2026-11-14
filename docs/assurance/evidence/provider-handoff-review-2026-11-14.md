# AI Provider 与交接收尾复核

日期为2026-11-14，实施基线为 `f42e587655a690fcde1bee14e428b797efcc6e17`。完整V1持续进行。

## AI 接入顺序

用户选定的首个真实接口为 **OpenAI Responses API**。原规格第710行将Google Gemini列为多模型备选，第720行列出GeminiAdapter。此前agent自行提前安排实现，在 `d5fded1` 交付了可选适配器及合成回归。[原始规格](../../requirements/2026-09-26-tire-intelligence-original.md)

本次核对 `ai_gateway.py` 的配置、工厂和状态入口。当前执行环境的 `TI_AI_PROVIDER` 未设置。隔离配置探针同时提供合成OpenAI和Gemini参数，省略Provider选择后，三个入口分别返回 `openai_responses`、`OpenAIResponsesAdapter`、`openai_responses`。探针的真实模型调用计数为0。活动HTTP／AI流验收显式指定 `openai_responses`，模型端使用合成Responses实现。

真实OpenAI Responses与Embeddings的网络、语义及费用验收继续待完成。Gemini的实现排期由此前agent决定，用户接入顺序继续按OpenAI执行。

## Parser诊断与专项回归

`DiagnosedRecordedRegistry.fetch` 在已有安全异常类型／栈记录上，增加固定Parser错误码及六个回执字段。错误码复用 `parser_failure_reason`，未知值归为 `parser_failed`。回执仅投影 `pid`、`exit_code`、`elapsed_ms`、`reaped`、`limits_backend`、`bundle_id`。

新增5项回归，覆盖已知／未知错误码、额外回执字段及异常消息省略、普通异常、成功结果透传和任务取消。异常按原对象继续抛出。最终三模块 **75／75通过**，跳过与不完整均为0，843项输入稳定，资源关闭，非自检拒绝0。

首批受管回归为67／75，8项既有测试在原件保存阶段失败。专项取证得到 `ObjectStoreError`，其上下文为 `PermissionError`、errno13、WinError5，Parser调用为0。沙箱内最小 `os.link` 探针复现相同错误。经普通权限复跑同一正式受管入口，75项通过。首批及三个诊断批的失败回执保留，原件存储继续使用既有原子硬链接发布逻辑。

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_parser_failure_reasons.py apps/api/tests/test_ai.py apps/api/tests/test_ai_provider_smoke.py
```

## 浏览器恢复验收现场

后续已在 `4a54531` 基线上完成较长API停机后的手动只读恢复与刷新恢复，以下保留本阶段原始失败及当时接手步骤。[后续Web验收](web-ai-stream-recovery-2026-11-14.md)

真实Web界面的API停机／重启恢复继续待验。现有两次尝试均为失败记录。

| 批次 | 已取得的证据 | 后续工作 |
| --- | --- | --- |
| `pgverify-8c2c71803cdd4264b379ebcdbbd68b69` | 1项前置检查完成，录制来源种子查询出现 `ParserRunError`，归一化结果为 `source_fetch_failed` | 该批具体Parser错误码未采集，使用新增诊断在新私槽继续定位 |
| `pgverify-fc9557e9720c42319f9bab770df97342` | 11项既有PG进程前置检查通过，生产Web及API启动，页面显示连接，浏览器登录401 | 修正私有驱动的合成登录凭据装配，再进行实际AI提交、停机与恢复 |

第二批驱动引用 `admin_support.ADMIN_PASSWORD`，而正式进程验收使用本轮 `secrets.token_urlsafe(24)` 注册合成账户。两者来源不同，浏览器尚未启动AI请求。结束驱动后缺少pending分析的断言失败已保留。

两批共14个服务进程记录均已回收，报告的端口关闭及输入稳定检查通过。收尾独立核对两个集群的 `postmaster.pid`、临时初始化口令及TLS私钥均已移除，临时登录脚本不存在，8010、3005及50768可绑定。

生产Web构建的422项输入与当前源码逐项一致，BUILD_ID为 `fV1VrESoZp5ne3hWUeKqF`。同机接手可复用该构建，新clone按项目工作流重建。

### 浏览器下一步

1. 从全新Git忽略槽创建下一批驱动，先核对端口和当前源码。输出根采用驱动文件所在目录，为前端构建副本生成唯一目录名。
2. 包装正式验收的 `accepted`，在本轮合成 `/v1/auth/register` 成功后，从该注册请求捕获实际用户名和口令到内存，并继续调用原实现。浏览器使用对应凭据，临时脚本在finally中删除。
3. 继续保留正常随机会话与生产认证入口。通过原页面选择历史证据、明确同意外发、提交AI分析，观察草稿后及时请求本批API停机。
4. 观察断线和草稿隐藏，同库同端口重启API，核对未知终态、预算、cursor、刷新及Provider调用计数。保存实际浏览器证据后完成服务、端口及临时秘密核对。
5. 依据新失败原始证据定位Parser问题，原8秒监督器期限继续作为当前运行配置。

同机私有原型位于 `.artifacts/web-stream-recovery-20261114/r2/runner.py`，该文件保留旧口令装配供复核。控制阶段为 `ready`、`stopped`、`restarted`，通过本批 `control/stop.command`、`restart.command`、`finish.command` 推进。模型端继续为合成Responses，真实OpenAI验收独立跟踪。

## 回执绑定

以下文件保存在本机Git忽略槽。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/provider-handoff-20261114/review.json` | `6bf3335a4ff8da5615d26aa11434ff1044392eaf652120bc3c31b25068cf2d31` |
| `.artifacts/provider-handoff-20261114/regression-r2/result.json` | `58c240584f0c6549bc36cb77f42e50644d291ee16caf207add3ec45090c83077` |
| `.artifacts/provider-handoff-20261114/regression-r1/result.json` | `ecd41666fcada5d7a88b922353244df67038e76a078721ea4d8f66420a8fea7d` |
| `.artifacts/provider-handoff-20261114/diagnostic-r3/synthetic-failure-diagnostics.json` | `d26ee886673307762e7c5900203abf8d741b4fa9dfd7ba01f016692b751b46a7` |
| `.artifacts/provider-handoff-20261114/hardlink-sandbox.json` | `c0d4a5293445fbe1a07351352fdc08a478291f4c13a1e684638cfcf65a4f4e17` |
| 第一批浏览器前置PG报告 | `dc707a7ae3c5e638af325d119c356545cdf7045bcd80df00dd117f60e6242dcd` |
| 第二批浏览器前置PG报告 | `38508238e73b60ece9b1a60322751988ee8614a4f36fc83cc8feac8eeb0482df` |

本轮API包源码与前端源码保持该实施基线。生产模型、浏览器恢复、Webhook实际网络、Native设备、无障碍、远端部署及其他发布Gate按交接卡继续验收。
