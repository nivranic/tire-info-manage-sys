# API/Worker 隔离回归工装实施计划与运行合同

日期：2026-10-19。原 Goal 继续 active；本轮不实施首代 SU7 PDF 链路、不启用 EPREL、不运行正常数据库或真实 Provider。完整 148 模块执行须由 Root 审查三份工装自检和整合代表结果后启动，不能把本文的待执行命令写成已通过。

**Goal:** 用新私根、显式模块和分阶段权限复跑当前 API/Worker，并保留测试真实语义、失败、skip 与安全边界。

**Architecture:** `run_api_worker_regression.py` 负责 bootstrap、pytest 生命周期和安全回执；`regression_guard.py` 负责文件/SQLite/网络/metrics；`regression_children.py`、`regression_child.py`、`regression_node_guard.cjs` 负责精确受管子进程。各自使用标准库预安装边界；不通过修改产品断言、扩大 Parser 预算或更改已封存证据获取绿灯。

**Tech Stack:** Python 3.12、pytest、Python audit hook、受管 Python/Node 子进程；PowerShell 7 启动。Python audit 是进程内约束，不宣称为 OS syscall 沙箱。

## 1. Phase 0 与源码范围

续作基线为 `.artifacts/r82-regression-a8ad637b725f4f59bad7b2f4a44f4924/baseline.json`，逐条核对 R81 已封存 **1104** inventory 原记录及 **114** evidence 原记录后生成；不会把协作中新增的 R82 文件吸收为旧文件。R81 主 seal SHA `184bf38a6b3dd554bae69a7ec9f9a944aacede39c7bbcb7c8c1dcea3d79bd6be` 保持原字节。新增源码、文档和本轮证据在结束时另列增量，不修改旧 seal。

| 责任 | 文件 | 内容 |
| --- | --- | --- |
| runner | `scripts/run_api_worker_regression.py` | 显式 146 API＋2 Worker，bootstrap／selfcheck／collect／run、安全 JUnit/报告、前后输入绑定 |
| runtime guard | `scripts/regression_guard.py` | 私根写／SQLite authorizer、只读 R38 原备份、真实 socketpair、已知 IPv6 probe 分类、精确动态 metrics |
| child policy | `scripts/regression_children.py`、`scripts/regression_child.py`、`scripts/regression_node_guard.cjs` | 完整 argv 类型匹配及固定源码绑定、子进程自身私根环境与边界、进程回收；不记录原 argv/env 或其秘密派生 hash |
| 最小测试缺陷修复 | `apps/api/tests/test_identity_migration.py` | 唯一将末尾报告改为 `tmp_path / 'backup-replay.json'` 并删除旧父目录 mkdir；原 nodeid、断言和只读原备份读取不变 |
| 本合同 | `docs/plans/2026-10-19-api-worker-regression.md` | 接口、阶段门、日志与验收边界 |

R38 修复是显式源码 delta，不做系统／Path 隐式重映射、不准写共享旧 artifact。原备份例外只允许固定 `mode=ro&immutable=1` URI，并在结束重新核字节／SHA。

每次输入绑定包括 API 产品/测试、Worker、scripts Python、Node guard、两类 fixtures、API-client/domain-types 源码与各 package.json/tsconfig、根 package.json/package-lock.json/tsconfig。全部 before/after 一致才可通过；不将 R81 的 581 直接沿用为 R82 输入数量。

## 2. 模块接口与生命周期

- `RegressionGuard(repo_root, private_root, output_root, child_policy=None)`：`install()`、`snapshot()`、`denied_count(phase)`、`set_test_nodeid(nodeid|None)`、`register_metrics_runtime(TelemetryRuntime)`、`verify_backup()`。
- `ChildPolicy(repo_root, private_root, output_root)`：`install()`、`audit_launch(executable,args,cwd,env)`、`snapshot()`、`denied_count(phase)`。
- runner 先构造两者，Guard.install 后 ChildPolicy.install；两个对象 phase 同步为 selfcheck／collection 或 run／teardown／receipt。未登记子进程始终拒绝。
- `pytest_collection_finish` 只从已自然导入的 `sys.modules['tire_api.telemetry']` 取得类再登记，不为 metrics 提前导入应用。`pytest_runtest_protocol` wrapper 在完整 setup/call/teardown 期间设定精确 nodeid，finally 清理。
- metrics 仅受核 nodeid 内官方 `start_metrics_server(0)` 创建的真实对象／实际 127.0.0.1 端口；监听／客户端／关闭后探测均按精确对象或已关闭 endpoint。不得泛放 loopback、DNS、Python/Node 或 subprocess。

## 3. Bootstrap 与 CLI

新进程从 `python -I -X utf8 -B` 启动。`-I` 忽略宿主 Python 启动路径；runner 在导入 pytest/应用前显式设置 sys.path。输出目录必须不存在且位于仓库 `.artifacts` 下，private_root 固定为该目录的 `private/`，cwd 也设为私根。

清宿主 TI/TIRE/Provider/云/EPREL/测试轮次凭据前缀、DATABASE_URL、代理与密钥后缀，另清 PYTEST_ADDOPTS/PYTEST_PLUGINS、NODE_OPTIONS/NODE_PATH/NODE_COMPILE_CACHE、PYTHONSTARTUP/PYTHONHOME/PYTHONINSPECT 和任意 R82_*；只记录删除数量，不输出原值。随后绑定：

- DATABASE_URL 与 TIRE_DATABASE_URL 指向同一新私库；AI/embeddings/observability 默认关。
- TEMP/TMP/TMPDIR、对象存储、Parser bundles 均在私根。
- 显式 R70、R71、R72、R75、R77、R78、R79、R80 所需根及 R70 guard report/R75 output。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`；不得继承未知显式插件或日志参数。
- Windows 平台信息用当前可信解释器原生 API，避免平台探测无关子进程。

CLI：`--phase selfcheck|collect|run`，`--output-root <NEW_DIR>`，可选 `--targets <registered-file-or-nodeid> [...]`、`--actual-dir <explicit-existing-r76-dir>`。未指定 targets 时使用代码中的显式 148 模块；当前 API 模块集合漂移即失败，不静默换成自动 discovery。传给 pytest 的 test/config/rootdir/basetemp 均为绝对路径。

示例（仅命令，不代表已执行；每次换新的 12 位十六进制后缀）。执行根使用 `.artifacts` 顶层短路径，避免在主证据 GUID 根下再次嵌套而触发 Windows Parser bundle／pyc 路径长度问题；不改变产品预算或测试断言。独立 collect 已有 R81 gate，本轮不重复执行；正式 run 自然完成 collection。

```powershell
& 'E:/Mix/project/tire-info-manage-sys/apps/api/.venv/Scripts/python.exe' -I -X utf8 -B 'E:/Mix/project/tire-info-manage-sys/scripts/run_api_worker_regression.py' --phase selfcheck --output-root 'E:/Mix/project/tire-info-manage-sys/.artifacts/r82-s-<12HEX>'
& 'E:/Mix/project/tire-info-manage-sys/apps/api/.venv/Scripts/python.exe' -I -X utf8 -B 'E:/Mix/project/tire-info-manage-sys/scripts/run_api_worker_regression.py' --phase run --output-root 'E:/Mix/project/tire-info-manage-sys/.artifacts/r82-t-<12HEX>' --targets 'apps/api/tests/test_telemetry.py::test_explicit_worker_http_export_is_loopback_guarded_and_closes' --actual-dir 'E:/Mix/project/tire-info-manage-sys/.artifacts/r82-regression-a8ad637b725f4f59bad7b2f4a44f4924/r76-fresh-b5c44f8aa2414cd8b602f8cfb0bf2f9e'
```

正式全套只有 Root 确认后，在单一新 session 用 `.artifacts/r82-f-<12HEX>` 和相同 runner 的 run 阶段、不传 targets 执行，并显式传上述本轮 actual-dir；不在运行途中改源码。148 是模块数，不是预计通过数。

## 4. 日志与真实测试语义

`--capture=sys` 将 pytest 的标准流捕获保留在内存；它不宣称与默认 fd capture 完全等价。capsys、caplog、业务 logger 和父测试读取的 child PIPE 保持真实测试内容，不能提前脱敏导致 secret 不泄漏用例假绿。只有 pytest 的独立 file/report 输出边界丢弃任意原文，最终回执再取安全字段。

不写原 pytest JUnit、不写 longrepr/sections/capstdout/capstderr、不保存原异常消息、响应 repr、重置口令、签发 token 或未知 assert 内容。无法全面识别任意秘密，因此明确采用**安全类型＋文件＋行＋阶段摘要**；终端也只输出同类安全结果，绝不先落 raw 再删除。reprcrash 的真实失败位置优先，test 定义行仅 fallback。pytest file logging sink 独立替换，caplog/report 对象仍保留原值供测试断言。

安全 JUnit 自建，case 结果互斥：任一 failed 优先，其次 skipped，其次 call passed，否则 incomplete；setup/teardown error 与 call failure 分开统计，SubTestReport 单列不混主 case 数量。skip 仅允许已读源码中的固定安全字面量，其余用 case 索引和 reason_code 保留未知，不伪造具体理由。参数化 nodeid 的参数值不持久化，保存稳定索引、无参数节点和源码绑定；不是可原样重放所有完整 nodeid 的 manifest。

privacy selfcheck 生成一次合成秘密，只在内存让其经过失败摘要／参数节点／抑制流，再检查安全落盘中不含值；不打印该值或其 hash。子进程原 stdout/stderr 可供父测试判断，但不由工装另存原副本。

## 5. 阶段门与回执

1. selfcheck：DNS／外网 connect／未登记 loopback bind-listen-connect／未登记 child／非私库／外部写／ATTACH 均在动作前拒绝；memory SQLite/socketpair 正例与隐私检查单列。故意拒绝不计为产品失败。
2. collect：明确 `--collect-only`，若进入 runtest protocol 即失败。输出安全 nodeids/collection reports，不把条数写成测试通过数。
3. run：先已有 guard/child 自检，再少量现有代表覆盖真实 Parser＋Windows Job＋stale-pyc、R38、CLI、Node、metrics 的整合边界。backend_core 和 guard agent 各自专门反例不机械重复。正式全套另待 Root 确认。
4. 结束：输入首尾一致、ChildPolicy.live_process_count=0、metrics.active_listeners=0、verify_backup.unchanged=true、所有意外拒绝为零。known IPv6 导入 probe 仍保留原 denied.network_bind/raw 红判定，另写限定分类；不能改成网络尝试 0 或靠分类抹掉其他失败。

每次输出 source-before/after、bootstrap、selfcheck/privacy、nodeids、collection/test/subtest reports、安全 JUnit、result 与 classification；raw runner exit 和 pytest exit 分开。结果来源、参数节点省略、skip、日志删减、资源关闭与未运行范围必须可读。

## 6. R76 新 actuals

Root 已授权复用 `scripts/run_professional_golden.py` 在本轮主私根下创建全新 basename `r76-` 的七案 ASGI 捕获；该脚本自带 guard，不修改旧 actuals，不选 latest。命令 stdout/stderr 仅在内存处理，另存安全 exit/路径/输入绑定摘要。若出现正常 DB／外网依赖则停止，不绕过。

```powershell
& 'E:/Mix/project/tire-info-manage-sys/apps/api/.venv/Scripts/python.exe' -I -X utf8 -B 'E:/Mix/project/tire-info-manage-sys/scripts/run_professional_golden.py' --output 'E:/Mix/project/tire-info-manage-sys/.artifacts/r82-regression-a8ad637b725f4f59bad7b2f4a44f4924/r76-fresh-<GUID>'
```

后续 runner 用 `--actual-dir` 显式指向该新 run 根；此路径需存在、位于 artifacts 下且 basename 为 r76-，并包含 `actuals/` 子目录。bootstrap 将 `R76_REVIEW_ACTUAL_DIR` 精确绑定到该子目录，因为既有测试要求目录内恰好为七案 JSON。不自动调用捕获、不隐式复用旧实例；未提供时如实保留相关 skip。它们是受控私库 ASGI 材料，不是专业精确 SKU／真人 Golden 或真实 Provider 通过。

## 7. 验证与回滚

当前先审代码/AST/CLI，再等三份自检，最后整合小组；实际结果写新 R82 报告，不提前填“通过”。完整 API/Worker 之外的浏览器、Native、六平台、PG/TLS/IAM、真实来源/Responses 和完整 V1 均不由本工装验收。

若不采用本轮工装，只撤回本轮新增脚本/合同及 R38 那一处明确 delta；不得 reset/clean/stash 未知工作或回写旧 seal。私根证据保留用于审计，正常数据库不回滚，因为本轮不启动或迁移它。
