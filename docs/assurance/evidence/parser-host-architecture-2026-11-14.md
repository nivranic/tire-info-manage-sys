# Windows Parser 缺省架构启动修正

日期为 2026-11-14，基线为 `9e41c20`。本轮接续文件打开取证，处理实际启动器省略 Windows 架构环境变量时的解析失败。完整 V1 持续进行。[文件打开取证](parser-file-open-2026-11-14.md)

## 原始证据与修正

本机工具宿主的 PROCESSOR_ARCHITECTURE 和 PROCESSOR_ARCHITEW6432 均缺省，`platform.machine()` 返回 AMD64。相同合成 PDF 通过原 `parse_isolated()` 入口执行时，在子进程创建前返回 `parser_isolation_unavailable`。诊断进程显式提供实际 Python 架构后成功。

原 `_environment()` 将两个可选环境变量均缺省作为拒绝条件。现为此场景使用 `platform.machine()` 派生架构值，该函数也是 bundle 环境声明的既有来源。已有有效架构字段沿原环境白名单传递，未知元数据仍由架构检查拒绝。运行时的摘要变化通过既有 bundle／执行身份及 PostgreSQL 源码合同绑定。

单元测试覆盖五种派生架构值、未知派生值、已有无效值及环境白名单。新增真实子进程回归显式移除两个架构变量，核对正常解析、退出和回收。经审查同步了运行时及真实进程测试的两项公开源码 pin，受管执行继续核对源码、命令形状及私域访问。

## 最终结果

| 范围 | 实际结果 | 回执及 SHA-256 |
| --- | --- | --- |
| 修正前成对复现 | 继承环境失败，提供实际架构后成功 | `.artifacts/parser-host-architecture-20261114/before.json`，`2da61b91cceed093839d515b27a0d3d540467c243f8f779c82542fa9718fa099` |
| 修正后原入口 | 8／8通过，架构变量均缺省，输出匹配、进程回收及目录清理通过 | `.artifacts/parser-host-architecture-20261114/after.json`，`6a3eb2977b836129dbf74fb2218b9f50200069a9e014f92bdc60f0b474493d94` |
| 最终五模块受管回归 | 125／125通过，跳过及不完整0，842输入稳定，资源关闭，非自检拒绝0 | `.artifacts/parser-host-architecture-20261114/regression-r3/result.json`，`3a38667650c73fcc142532da65496e1b24f0c74d833eb0d07f650b5778c36dd4` |
| 正式PG／TLS运行合同专项 | 60项通过，842输入稳定 | `.artifacts/postgres/pgverify-a1be701e48fe4feb8b10e14a700e6265/report.json`，`fb7cd5394103680a7a71fc5b3e2ce7d9cdc29abe01933de2c69a163a6a47d0f7` |

8次原入口覆盖系统／项目临时目录、PDF／Hankook、当前安装／修改前本机封存bundle，每个组合执行一次。监督器期限为8秒，资源限制、代码前后核验和输入输出校验均参与执行。当前及修改前bundle均在缺省架构环境下得到正确结果。

五模块覆盖环境、真实进程、文件树、bundle及PDF，包含取消、超时、资源限制、历史包和路径边界。PG专项通过新空参考合同核对API／Worker、旧库、权限反例及HNSW维护。当前API源码摘要为 `e467c68763b69fdc5c12f5c8bd10432ae35676be47962fb5a35edb34f41dfda3`，部署须按既有流程重新生成并批准@4合同及固定摘要。

## 原始失败与装配纠正

- `regression-r1` 在旧源码pin处被受管启动拒绝。审查本轮差异后同步对应两项pin。
- `regression-r2` 的124项中123通过，旧PDF目录测试仍将当前15来源目录按历史11来源断言。原目录生成函数的AST与基线一致，诊断保存在 `catalog-fixture-before.json`。
- `catalog-regression-r1` 的当前目录场景通过，历史文件树装配因仍搭配当前声明而被完整目录检查拒绝。后续复用既有历史安装重建，并通过 `snapshot_manifest()` 传入对应11来源声明。
- `catalog-regression-r2` 两项通过。最终完整五模块重新执行，当前目录拒绝缺失PDF能力，重建历史11来源目录保留已有兼容行为。

上述失败和原始回执保留于Git忽略目录。本轮PG集群关闭、口令／TLS私钥缺席、自用端口及受测输入核对见 `.artifacts/parser-host-architecture-20261114/closure.json`。

## 复跑与剩余范围

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_parser_runtime_environment.py apps/api/tests/test_parser_runtime.py apps/api/tests/test_parser_tree.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_document_pdf.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <postgres-bin-with-pgvector> -Port <unused-port> -Suite runtime-schema -CliTls
```

本轮使用合成材料、隔离数据库和当前Windows实际子进程。架构值分支已有单元测试覆盖，其他实际架构／设备、真实服务启动器、远端部署和生产SLO继续验收。新文件打开延迟的OS归因及原三份间歇超时继续待查。下一步推进正常HTTP／Worker部署及环境传播、取消和全资产恢复。
