# 2026-10-26 计划：来源页 URL 迁移事件（迁移 032）

## 背景与定位

R134 交付了"已采纳文本原文变化"监控（`page_changed`），其计划 §边界显式延后了 URL 迁移事件：*“URL 不同时不跨地址比较；新成功观察自然成为后续该 query 的基线。首片不新增 URL 迁移事件，也不把 URL 漂移称为原文变化。”* 本片按该延后清单补齐第一项，属于交接卡 P2"剩余监控"工程项。

## 语义定义（不变量）

1. **url_moved 事件**：同一 `source_id` + canonical query 的**相邻两次成功观察**（前次 status ∈ {ok, not_modified}，本次 status = ok）的 `source_url` 不同时，记录一次 URL 迁移。内容哈希不参与判定（不跨地址比较内容，维持 R134 口径）。
2. **与 page_changed 互斥**：URL 不同时既不产生 `page_changed`（维持现状），内容比较在新 URL 上以本次观察为新基线。
3. **A→B→A**：产生两次独立迁移事件（相邻对各自成立）；事件不可变、不可重算。
4. **规则**：新 Kind `url_moved`，页面类规则语义与 `page_changed` 对称——`kinds == ['url_moved']`、无 fields、无 conditions、无 variant_id、仅已登记轮胎来源；页面类与规格类规则不得互换，页面类内部 kind 亦不可编辑互换。
5. **提醒**：独立通知表 `source_page_url_move_notifications`（rule_id × event_id 唯一，仅 read_at 可变），不动 029 任何既有表/触发器/指纹合同。
6. **回执核对**：每事件与通知带指纹，读取路径全量复核（verification/snapshot/query 链、双侧各自 URL 一致、时间序、canonical query）。

## 变更面

| 文件 | 变更 |
| --- | --- |
| `tire_api/source_page_url_models.py`（新） | `SourcePageUrlMove`、`SourcePageUrlMoveNotification` 表 + SQLite/PG 不可变守卫 + before_flush 防护 |
| `tire_api/migrations.py` | `include_source_page_url_moves` 开关 + `032_source_page_url_moves` 链块 |
| `apps/api/tests/version_registry.py` | 追加 `032_source_page_url_moves`（集合断言自动级联） |
| `tire_api/source_page_monitoring.py` | 仅抽出"最近前驱验证"共享助手（行为不变） |
| `tire_api/source_page_url_monitoring.py`（新） | `append_url_move`/`checked_url_move`/通知匹配与视图/三个只读+已读路由 |
| `tire_api/monitoring.py` | Kind 增 `url_moved`；创建/编辑/目标校验对称扩展；注册新路由 |
| `tire_api/service.py` | 验证落定处挂载 `append_url_move`（与 page 同事务、同锁） |
| `apps/api/tests/test_source_page_url_moves.py`（新） | 行为 + 迁移历史链测试 |

## 验证计划

1. 快速迭代：裸 pytest 新测试文件 + 迁移族 + test_core（隔离私库）。
2. 正式批：受管 runner 短槽新批（新文件 + source_page 迁移/行为 + 核心三模块 + schema_startup）。
3. 边界：不动正常库/默认 API；不重写 029 回执；Web UI 集成与 Worker 长周期观察列为后续片。

## 回滚

代码按文件精确恢复；032 仅新增表与版本行，历史库未升级前不受影响；已升级库保留空表即回滚后的合法状态（无数据依赖）。
