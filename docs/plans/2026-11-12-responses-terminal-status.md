# Responses终态额度刷新与流式验收计划

## 目标与依据

上轮生产Web合成验收观察到，分析已完成并显示600 tokens，顶部模型状态仍展示受理时预留。点击“刷新记录与配置”后才更新。证据位于本机 `.artifacts/responses-web-20261112/browser-records.json`。

现行 `submit` 在受理后读取额度，`AIStreamProgress` 后续通过 `onDetail` 更新分析记录。终态更新路径缺少额度读取。用户已选定OpenAI Responses主线，本轮继续补齐该路径及其余流式模式的浏览器验收。

## 实现

修改 `apps/web/components/ai-analysis.tsx`。复用 `tireApi.aiStatus`，以请求序号仲裁初次读取、受理读取、手动读取及终态读取。晚返回的旧读取无法覆盖较新结果，过期读取错误也按序号过滤。

在分析ID或state变化至终态时发起可取消的额度读取。组件卸载或切换分析时中止该读取。额度读取失败沿用现有错误展示和手动刷新入口。

## 执行及验证

1. 保存本轮输入指纹，实施上述客户端改动。
2. 执行三端类型检查、既有Web测试与独立Web生产构建。
3. 使用 `scripts/ai_stream_acceptance.py` 的私有API、显式端口与新数据库，覆盖complete、held、grounding_failure、incomplete、truncated、terminal_mismatch、uncertainty_only、refusal。
4. 在实际UI验证终态额度自动更新，以及受理时旧状态延迟返回后的结果仲裁。检查引用、恢复、失败草稿清理与Provider调用数。
5. 取得API／Web关闭回执、核对证据指纹并恢复构建生成文件。将实际结果及剩余项写入续作记录与交接卡。

真实OpenAI语义待本机配置具备后验收。当前继续使用合成Provider字节，通过生产解析器及真实应用入口验证。

## 执行结果

终态自动刷新及26008 tokens旧响应延迟返回后的600 tokens保全均通过实际页面验证。8种wire模式与关闭／原标识恢复通过，9次合成Provider调用落账4个completed、4个failed、1个outcome_unknown。每个终态的顶部额度均匹配API，最终81586 tokens。

50项既有Web测试、三端类型及Web生产构建通过。API经shutdown退出0，Web经SIGINT退出1，端口及进程均为0，402个前端输入按字节恢复。只读checkpoint完整性ok，来源证据指纹保持，真实OpenAI调用0。

核对入口为本机 `.artifacts/responses-terminal-20261112/verification.json`，SHA256 `56f12e06b351eacf5be979457ba6c86fe71b7d6ba9cc148283157b45168bff42`。真实模型语义、额度读取失败注入、原生运行及完整V1仍待各自验收。

## 后续额度故障验收

复用既有生产构建，在新私有API／数据库及隔离浏览器上下文完成终态额度503、手动刷新恢复、过期错误仲裁，以及终态读取期间关闭后的迟到成功／错误验证。四次明确提交产生四次合成Provider调用，全部completed，累计2400 tokens。错误期间已校验分析与引用保留，重开按原标识恢复。关闭读取的两个AbortSignal均实际取消，释放迟到响应后当前视图保持正确。

本轮产品源码沿用原提交，402个前端输入及775个后端回归输入逐字节匹配。API退出0，Web经SIGINT退出1，端口及私有临时存储已关闭，checkpoint完整性ok。核对入口为 `.artifacts/responses-status-fault-20261112/verification.json`，SHA256 `6567b3c633a2287ac6ee14de2f4e300ec6765a1a577f959d3e7ea72b8a1f24e3`。真实Responses语义、原生运行及完整V1继续待验。
