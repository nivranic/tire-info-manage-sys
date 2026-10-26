# G1a：结构及适用范围纯核

依据 `.artifacts/fact-query-contract-review-20261021/REVIEW.md` 第 3 节收敛规格；审查文件 SHA-256 为 `de0966663191fc642e57eb0a5479968e3c1bf71a4bb8405ab48b0718f595289a`。本轮只新增产品纯核与其独立 unittest；不承接原候选的账户、HTTP、SDK、字段值或九字段清单。

1. `apps/api/tire_api/external_fact_policy.py`：固定 schema/purpose、封闭有界修订、规范 UTC 秒时间、精确观察三元组与字段集合、连续链及显式 expected_head。输出固定三态及固定内部原因。验证结果仅保存冻结的最新修订与 head，无调用方可变别名。
2. `apps/api/tests/test_external_fact_policy.py`：按精确文件路径加载源码；冻结字面量与独立 serializer 向量、合法摘要的语义负例、上限/重复/时间/不可变性及信任限制。UTC aware now 在本切片限定为标准库 `datetime.timezone` 的零偏移对象，不调用自定义 tzinfo。
3. `.artifacts/external-fact-policy-core-20261021/audit_harness.py` 与 `launch_audit.ps1`：候选隔离入口；Root 审核并独立核对候选 pins 后，才单次运行固定 Python 3.12.10，120 秒有界、清空继承环境、`-I -S -B -X utf8`，只加载这两个源文件。Python 导入目标前安装钩子，拒绝 SQLite、网络、child、应用/相关第三方导入及写操作；安全汇总不展开 traceback 或原始流。

候选 pins 使用封闭 `external-fact-policy-input-pins@1` JSON：`schema`、`files`；每个 files 项恰含 `path`、`sha256`、`bytes`，覆盖 launcher 所列关键 exe/DLL、两文件、工装及相关 stdlib。manifest 自身通过外部 `ExpectedManifestSha256` 锁定，不自含 hash。此清单是关键输入集合，不是完整传递依赖闭包、OS 沙箱或正式批准记录。launcher 只写全新独立 run 槽，并核对关键文件首尾保持。

工装限制：Python 执行期限 120 秒，停止及流收集另有各 5 秒有界清理。`ReadToEndAsync` 抑制原始流但没有独立捕获内存硬上限；receipt 明示该限制，仅记录已收集流的 UTF-8 字节数，未完成收集为 null。`tests` 是 unittest 主 test 方法数，`subtests` 独立计数，不混加。钩子覆盖含 `_winapi.CreateProcess`、`os.startfile` 的 child 审计事件；仍不构成完整 OS 层阻断证明。

无密钥摘要只证明自洽，expected_head 不是认证；重写全部记录并提供新 head 仍可自洽。真实权利依据、审阅身份、当前受控 head、持久化/并发及撤回属于 G1b。真实许可、外部投影/路由与 G2 产品验收未完成。opaque evidence_reference 不打开、不联网、不核真实字节。

当前仅静态文件阅读、PowerShell 7 解析与 SHA-256 核对；未运行 Python、测试、应用、DB、迁移、网络、Provider、UI 或设备。最终执行结果由 Root 另记；合成纯核测试通过也不构成真实许可或 V1 验收。回退仅移除本轮新增文件，保留其他 dirty 改动及原有授权行为。
