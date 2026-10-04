"""单一权威期望清单：全部历史 schema 迁移版本。

测试侧独立维护（刻意不从 tire_api.migrations 导入——源与断言同源会失去
"新增迁移必须同步更新断言"的哨兵价值）。新增迁移时在此追加版本号，
再更新各迁移测试中的"到某版本为止"子集（它们描述历史快照，不是全集）。
由第56轮圆桌裁决引入：此前版本断言分散在 9 个文件，第 57 次迁移时
又造成过 61 失败中的整个迁移族（plans 第56轮记录）。
"""

EXPECTED_SCHEMA_VERSIONS = [
    '001_verification_validators',
    '002_monitor_rule_conditions',
    '003_parser_release_provenance',
    '004_query_selection_filters',
    '005_variant_identity_contract',
    '006_source_settings',
    '007_monitor_tasks',
    '008_recall_discovery_monitoring',
    '009_ai_streaming',
    '010_offline_packs',
    '011_query_fallback_policies',
    '012_device_ai_preparations',
    '013_device_ai_ledger_triggers',
    '014_local_sessions_user',
]

# 008 之前的历史基线（构造 pre-009 升级起点用；与断言基线是两个概念，勿合并）。
PRE_009_VERSIONS = EXPECTED_SCHEMA_VERSIONS[:8]
