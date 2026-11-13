# Parser 文件操作与期限检查

基线 `91bc941f3cfd3de9441b082eb1378ce0a925fbc0`。本轮承接[准备阶段诊断](parser-preparation-2026-11-13.md)，处理长时间复制／校验返回后仍继续处理文件，以及结果复核期间未检查期限的问题。完整 PG 混合流程与完整 V1 仍未验收完成。

## 文件操作测量

使用原生产函数，对实际系统临时目录中的三个新副本分别计时。只包装文件属性、打开、读取、写入、刷新与文件树调用，不改变路径校验、内容、清单或 fsync。副本均为同一份 188 文件的受信源码；这是诊断样本，不是生产 P95。

| 样本 | 完整复制 ms | 目标树校验 ms | 首次打开合计 ms | 属性检查合计 ms | 随后重复校验 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 3734.364 | 3103.762 | 2932.246 | 22.487 | 147.917 |
| 2 | 3423.117 | 2829.336 | 2668.297 | 21.844 | 164.640 |
| 3 | 3321.320 | 2716.831 | 2559.450 | 21.291 | 181.620 |

首次打开新文件占这三次目标树校验的大部分耗时；同一副本随后校验明显更快。这个现象不证明具体安全软件、磁盘、缓存或其他系统组件是根因，也不能解释上一轮 16.95 秒的极端样本。没有更改系统安全设置、临时目录配置或代理。

回执 `.artifacts/parser-io-profile-r2/result.json`，SHA256 `916805bc96514577b6fb06395daed385e88637f39a21e2740cf52764aac7d685`；188 输入稳定，三个自有临时目录均已清理。更早的 `parser-io-profile-r1` 在工作区内测量且执行环境不同，仅保留原始结果，不作为严格的目录性能对照。

## 修改范围及限制

- 为文件树读取、复制和封存包核验增加内部可选 checkpoint。Parser 监督器传入既有取消事件和同一 8 秒期限；封存和其他无预算调用继续执行完整校验。
- 逐文件检查期限／取消，包括首次打开之后与读取／写入结束之后。取消后不继续打开后续文件；已打开句柄通过上下文正常关闭，临时目录照常回收。
- 返回结果后的目标树、源树／封存包和执行身份复核也使用同一期限，过期或取消的结果不能作为成功返回。正常成功仍须完成原有全部校验。
- 不修改 8 秒值、并发数 2、Job 回收、逐字节清单、源前后检查、symlink／reparse／硬链接和句柄身份限制；不增加缓存、重试或降级。
- 这是协作式检查：单次 OS 调用、目录枚举、环境核验及必要清理仍可能超过期限，不能据此承诺整个 HTTP 请求严格在 8 秒返回。

## 反例和源码绑定

新增 10 项确定性反例，覆盖源读取、复制写入、目标读取、源再次检查和结果最终检查，各自包含期限耗尽／取消。测试在一次真实文件操作完成后推进测试时钟或取消事件，不依赖真实睡眠；要求后续文件不再打开、准备失败不创建子进程、最终检查失败回收既有子进程，并释放两个并发槽。

首次受管启动因已修改测试文件与精确源码指纹不符而被拒绝，回执保留于 `.artifacts/parser-checkpoints-red/runner-failure.json`。随后复核测试差异，确认未增加 launch 种类、可执行 literal 或权限；仅更新测试文件指纹。旧生产实现实际执行新反例 **0／10 通过**，832 输入稳定、资源关闭、非自检拒绝 0。回执 `.artifacts/parser-checkpoints-red-r2/result.json`，SHA256 `75048bc3b5358302c3f2b5d66b72d7bba25d9eb6d8211ac297e121546976e00a`。

候选实现完成源码复核后，仅再更新运行时文件的精确指纹；ChildPolicy 其他行为保持原样。静态 AST 对照剥离新增 checkpoint 调用及参数后，五个受影响函数与原实现相同；启动命令、环境构造、限制值及原预算函数不变，全部已登记源码指纹匹配。这是当前 agent 的静态复核，不冒充独立审查。回执 `.artifacts/parser-checkpoints-review/static-review.json`。现有文件变更测试只透传新增内部参数，仍要求源被改写时拒绝。

## 验收结果与保留的失败

首次四模块受管回归 **89／94 通过、5 失败、无跳过**；新增 10 项反例全部通过。832 输入稳定，49 个子进程均已结束，资源关闭、非自检拒绝 0。失败集中在最先执行的五个 Michelin 正常解析用例；脱敏报告没有保存具体 Parser 失败码，因此不能直接把它们归因到某个阶段。原始回执 `.artifacts/parser-checkpoints-green/result.json`，SHA256 `fe34deebb4767bdf93eff563cbc86e692d83746d21fd48d6fdfa810084eee02a`。

随后只针对这五个用例，在相同受管入口增加固定阶段计时，保留全部原断言，结果 **5／5 通过**；监督回执 2532–2735 ms，所有子进程已回收，832 输入稳定、资源关闭、无意外拒绝。它没有复现此前失败，不能用于解释或抹去原失败，更不是把分轮结果拼成一轮全绿。

- 定向复查 `.artifacts/parser-checkpoints-normal-observed/result.json`，SHA256 `4b065856d95621b38d805f05b5e463bc2f68d2e0792f20314382273bf1ca1c4e`。
- 阶段回执 `.artifacts/parser-checkpoints-normal-observed/parser-observations.json`，SHA256 `9a56c4d9f0bbec3aa185b1cc2032f6a534057d644ade7e31a0a71ee0ece4bd60`。观测只记录阶段、耗时、固定错误码与监督收据，不保存正文、stderr、环境或任意异常字符串。

随后带阶段的四模块回归为 **70／94 通过、24 失败**，失败集中在封存包模块，原回执 `.artifacts/parser-checkpoints-final-observed/result.json`，SHA256 `7a5237b374fb3c706d714ea7218a2100f983318d8f4ba308b667c54336caa8e4`。没有据此继续修改生产代码。

对其中不启动 Parser 的宿主身份测试单独复现，取得 `BundleError: parser_bundle_missing`，位置为 `_plain_path_info`。进一步记录失败路径长度 **268 字符**，叶节点为源码文件 `xiaomi_first_generation_pdf.py`，通过 Windows 扩展路径只读检查确认文件实际存在。同一脚本、同一用例改用短私有输出目录后通过。诊断目录触发了 Windows 路径长度限制；不能把这轮新失败混作前面的间歇超时，也不据此放宽链接或路径校验。生产长路径支持和准确错误分类仍未补齐，本轮未改系统长路径设置；复跑使用短输出目录只解决验收装配问题。

- 原始异常类型／位置：`.artifacts/parser-checkpoints-observer-diagnostic/fixed-failures.json`。
- 路径长度与存在性：`.artifacts/parser-checkpoints-path-diagnostic/fixed-failures.json`。
- 短目录对照：`.artifacts/pc-short/result.json`，SHA256 `7353337df0e0c30241bcb5eadb83aa3ddfca3e83d67fd751ca39c16fd6aae933`。

短目录 `.artifacts/pc-final` 的后续运行在第 64 项 setup 后中断，原会话句柄消失；后续只读进程检查未发现相关监督器或 Parser 进程。该轮没有最终 result，不能认定全部执行完毕或据部分进度声称完整资源清理验收。状态已单独写入 `interruption.json`。

对其 A/B/A 失败再次单独取证，回执为 `parser_isolation_unavailable`，ChildPolicy 记录一次 `denied.parser_dependencies`，未创建子进程。原因是私有观测器包装了 `_command`，而该测试的已审查 lambda 要求捕获的原命令函数保持精确代码身份。移除这一个观测包装后，同一 A/B/A 用例 **1／1 通过**，三次封存包执行成功、资源关闭、输入稳定、意外拒绝 0。门禁代码未为观测器放宽。

- `.artifacts/pc-aba/result.json`，SHA256 `e54b8ef88ab7350147b1c5d74e0fe903b831153bdf33bb4c122aa76d792d0748`；对应 `fixed-failures.json` 和 `parser-events.jsonl` 保存原始失败。
- 该私有观测器还曾在结束时重复独占创建已写入的失败回执，产生 `FileExistsError`；属于观测收尾错误，未改变生产代码。后续改为逐项独立失败回执与统一终态回执，并串行追加阶段事件。
- `.artifacts/pc-aba2/result.json`，SHA256 `c1bf39354fc14bd0ed1007f90fd8921486a3f34fc40e8ad92191bbc103c46fd9`，保存取消命令包装后的对照。

移除命令包装后的整体观测运行又暴露了工具自身的另一处干扰：监督包装器在返回前打开 `parser-events.jsonl`，被新增反例计入“过期后仍打开文件”。该轮 **84／94 通过，10 项新反例在此断言失败**，原 84 项通过、资源关闭、输入稳定、无意外拒绝；回执 `.artifacts/pc-v2/result.json`，SHA256 `1cbf3f8fdf121b455a46d525fc3ae17ae5e0875a755b2bc4069c919ee12bff1d`。没有放宽反例，也没有因此改变生产代码。

最终验收恢复为原项目受管入口，在短目录执行相同四模块，不包装 Parser 函数、不在执行路径写诊断日志：**94／94 通过，无跳过**。832 输入稳定、资源关闭、非自检意外拒绝 0、真实 Provider／接收端调用 0。回执 `.artifacts/pc-plain/result.json`，SHA256 `d7541429bce06389d11e0a960b413800676bbb942bfafcde85d37f336c37fd74`。

这次验证证明本轮文件操作检查、旧校验与封存包兼容合同在该工程回归中通过。它不解释最初五个正常解析失败的根因，也不证明全部间歇超时已修复。完整 PostgreSQL 综合流程本轮未再次运行，仍保留此前失败状态。


## 复跑与后续

使用未占用的短输出目录，保留既有失败回执，不覆盖旧槽：

```sh
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/pc-r1 --targets apps/api/tests/test_parser_tree.py apps/api/tests/test_parser_runtime.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_parser_runtime_environment.py
```

后续继续定位混合 PG 工作负载中的首次文件打开／准备耗时波动，保留此前已启动子进程的超时问题。需要严格硬时限时，必须另验可终止的准备／校验隔离设计；当前协作式检查不具备中断任意 OS 调用的能力。长路径支持与准确错误分类另行处理。正式验收优先使用原受管入口，避免包装受精确代码身份约束的函数，避免在被测文件操作期间落盘观测日志。
