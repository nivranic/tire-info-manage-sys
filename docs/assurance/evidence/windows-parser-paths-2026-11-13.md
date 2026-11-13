# Windows Parser 长路径与受管目录边界

起点 `7c3502808191ddcf5592419e887d327346383fe2`。依据原规格的 Windows 支持及已发现的长路径失败推进；本轮不改系统设置。完整 V1、PG 综合和间歇超时根因继续开放。

## 已确认的文件系统行为

在本机 `LongPathsEnabled=0` 的环境中，对相同合成源码创建 240、259、260、268、310 字符路径。普通路径在 240／259 字符时读取和树校验通过，从 260 起 `lstat`／读取返回缺失；相同文件的 Windows 扩展路径均可正常读取且字节一致。目录枚举在部分长度仍能列出文件，因此仅看枚举不能证明后续读取可行。回执 `.artifacts/pl-diagnose/result.json`。

还核对了 `..` 和尾随点：普通路径和扩展路径的解释不同。因此不能在未考虑路径语义时无条件加前缀，更不能先 resolve 而跳过重定向祖先的检查。

## 第一步：受管验收的等价路径比较

原 RegressionGuard 对同一私有目标的普通路径返回允许，扩展路径返回拒绝；私有目录外的两种表示均拒绝。原始对照 `.artifacts/pl-diagnose/guard/containment-before.json`。

现在先通过可信 resolver 取得实际目标，再只归一等价的 drive／UNC 扩展表示用于目录包含比较。未知命名空间不作前缀替换，未归一的父路径分量拒绝。文件描述符仍检查真实目标和身份，不以路径字符串开头匹配替代包含关系。目标范围、网络／SQLite／子进程规则及 ChildPolicy 均不变。

新增实际自检：私有扩展路径读写及清理成功，目录外扩展路径写入和建目录被拒绝。原 12 项自检保留，Windows 下合计 15 项检查、13 次预期拒绝。单独自检通过：`.artifacts/pl-guard/result.json`，SHA256 `aee26780c26abc259809aa4a9395935abe39874f2806834db9f5bb50f2c37823`。

文件树相关测试 **11／11 通过**，832 输入稳定、资源关闭、非自检拒绝 0。新增实际 NTFS junction 的包含边界、普通／扩展路径、父路径逃逸及内外文件描述符检查；junction 只删除本次创建的链接，目标保留。回执 `.artifacts/pl-gtest/result.json`，SHA256 `b00ee3ec3bfcdd0e7124fd25c18c5e755125c0a19f26be0d6efd39863ac5bf3e`。

这是 Python 受管测试边界的修正，不是 OS 沙箱、实际 UNC 共享或 Parser 长路径业务链路验收。Parser 文件操作与长路径封存包执行在后续阶段继续实现和验证。


## 第二步：Parser 文件操作与消费者

在路径门禁提交 `014e41c2fd5a7cc418a42112e40740bd412850b0` 上继续实现。`parser_bundles.py` 在普通的规范 Windows drive／UNC 路径进入文件操作前使用等价扩展表示，覆盖逐级属性检查、源读取、执行副本复制、封存目录创建及归档重读。转换不 resolve 祖先；仍逐级拒绝 symlink／reparse，打开后校验单链接和文件身份，逐字节清单、fsync、期限与取消检查均保留。

父路径、尾随点／空格、保留设备名和备用数据流不作隐式转换，显式命名空间保留原表示，避免改变 Win32 名称语义。保留名检查优先使用新版本 Python 的平台函数，3.12 使用已有 Windows Path 判定。不能据此宣称所有非规范长路径均受支持，也没有实际连接 UNC 共享。

原五项长路径反例 **0／5 通过**，非自检拒绝 0；原回执 `.artifacts/pl-red/result.json`，SHA256 `a36b56dd0df71bff59fc0d06d7b1b8e4c30ee82380368e165f901c83ed632715`。修正后初轮文件树 **17／17 通过**，包含实际长路径读取／复制、硬链接、根／嵌套 junction 及原句柄身份反例。回执 `.artifacts/pl-tree/result.json`，SHA256 `ba19a9217fce47fed6e93ef2c525f272ad26330cfd0c97c767973d1b07337f14`。

超过 300 字符的归档根目录完成封存、幂等重读、真实 Parser 执行及普通／扩展表示的同一对象确认；归档源码被改写后，核验拒绝且未启动子进程。专项 **1／1 通过**：`.artifacts/pl-store/result.json`，SHA256 `5868fc544d73efea306a36bba8c628f95b80cf3afb65b36c22be02bc3ea09ffb`。

另覆盖 `_plain_path` 的车型映射消费者：读取长路径中的四个固定映射声明，只解析 AST，不执行源中的顶层 raise；字节被改写后拒绝。这是合成映射源的路径与完整性验证，不是真实 PDF 内容或来源许可验收。

初轮四个完整 Parser 模块加消费者专项 **103／103 通过**、832 输入稳定、资源关闭、无意外拒绝。回执 `.artifacts/pl-final/result.json`，SHA256 `8f1040936dc2f115cc76f117659163055984fbe14cc3f760f8c22822ba69fc5f`。

复核补充了保留设备名／备用数据流的语义反例：修正前 **0／1 通过**，纯路径比较未访问设备或数据流，回执 `.artifacts/pl-alias-red/result.json`，SHA256 `34224d93550d10c236245c5ee1fa49fde25ccf673bd0e079c7a88be16356921c`。最终代码保留其原表示，并增加中文长目录的普通／扩展两种读取复制验证。最终原受管入口 **105／105 通过，无跳过**，832 输入稳定、资源关闭、非自检拒绝 0、真实 Provider／接收端调用 0。回执 `.artifacts/pl-final2/result.json`，SHA256 `b551b3f6da546b98c783eb2292f80fe82161360dae8bf73169148906d3a704fb`。

## PostgreSQL 综合流程

保留名修正前，采用原 core 断言和已有固定 Parser 失败回执收集，使用现有项目 Python，未运行依赖更新；隔离 loopback 集群使用随机口令，结束关闭。一次完整 **58 项通过**，覆盖此前失败的历史重解析、Parser A/B/A、召回回滚，及向量／融合检索、报告、身份并发、导出恢复与恢复后读取。

报告记载核对 166 个模型表、12 份证据对象、5 份报告对象；这是该验收覆盖范围，不把它误写成数据库全部物理表数。832 输入稳定、Parser 失败回执 0。PID／初始化口令文件已移除，端口无监听。回执 `.artifacts/postgres/pgverify-9e27dd81bf184dabb23a3c7cefeead42/report.json`，SHA256 `c5b3f3bddb3572d9b659299786babfa2bbd06e6304abb678568e1b2cd6c2b4ba`。

这不解释此前间歇超时的根因，也不替代生产角色／ACL／RLS、RTO／RPO、自然长周期或真实模型验收。最终源码另开独立集群执行相同 core 流程，再次 **58 项全部通过**，832 输入稳定、Parser 失败回执 0；仍核对 166 个模型表、12 份证据对象和 5 份报告对象。回执 `.artifacts/postgres/pgverify-5ecde07aba10454390cc72d42a164e23/report.json`，SHA256 `5abb02e4df366fa21166ec5ca0132056684634ae54dfe43b2165c4749837348b`。该集群已关闭，PID／临时口令已移除，55487 无监听。


## 复跑、边界与后续

```sh
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/pl-r1 --targets apps/api/tests/test_parser_tree.py apps/api/tests/test_parser_runtime.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_parser_runtime_environment.py apps/api/tests/test_vehicle_raw.py::test_long_mapping_source_is_read_as_literals_without_execution
```

PG 正式入口为 `pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin '<PostgreSQL bin directory>' -Port 55487 -Suite core`。本轮私有 wrapper 仅改工作区定位并直接使用已安装的项目 Python，再调用原 `run_observed()`，未删改 core 断言或改变超时、重试、数据库权限。新 clone 需重建依赖及材料；私有回执不随 Git 交付。

已验证 Windows 本地规范归档路径（含中文）、普通／显式扩展表示及短临时执行目录下的真实 Parser。未验证实际 UNC 共享、所有非规范长路径、超长宿主安装／TMP 目录、其他操作系统实机或生产部署。当前测试通过不表示历史间歇超时已根治，也不是性能 SLO 证明。

后续优先推进 PG 许可运维入口、生产角色／吞吐和部署治理，继续 Native、自然长周期监控及真实 OpenAI 验收；针对新的超时保留原始回执再定位，不删除既有失败或用反复重跑替代根因分析。

回退应以完整业务提交及对应测试指纹为单位，保留既有封存包和失败回执，不删除或重写归档。回退后旧实现的普通长路径限制会重新出现；本轮没有迁移生产数据或修改全局系统选项。
