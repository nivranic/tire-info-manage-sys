# 胎迹 Agent 接手入口

更新于2026-11-15，沿现有main继续完整V1。

先读[最新交接卡](AGENT-HANDOFF-2026-11-15-AI-SELECTION.md)，其中汇总12个模块的进度、当前合同、剩余需求与接手顺序。验证范围、首次失败及回执摘要见[AI成绩选择验收](assurance/evidence/ai-test-measurement-selection-2026-11-15.md)。需求以[原始规格](requirements/2026-09-26-tire-intelligence-original.md)为准。

## 当前工程状态

- 最新阶段支持同场混合尺寸，SKU桥、关注、FTS、Web和离线消费者使用逐参测胎尺寸。派生检索索引为accepted-heads-fts@7。
- 许可论文完整捕获及22条真实转录值已验，支持冻结捕获期限。AI显式成绩选择及10／12条两组真实报告已验，保留原成绩序号及PDF引用。整场单包61,421字节超过44,000字节上限，原失败保留。
- 最终API专项239、Web69、PG／TLS6及浏览器11项通过。首批6项PDF回归和浏览器409复跑通过，首次根因尚未确认。
- 数据库迁移为036，PG运行合同为postgres-runtime-schema@4。目标部署按实际catalog与当前API源码生成批准合同。
- 上阶段已完成账户持久归属和个人Garage／保存比较。旧共享记录归创建者私有，该策略由agent依据创建证据制定。
- 首个真实AI采用用户指定的OpenAI Responses API。EPREL尚无Key，真实模型与监管接口验收继续待外部条件。
- 原规格按12个模块、10项发布Gate、13项SLO及15项待确认决策组织。完整发布验收继续推进。

## 优先接续

1. 核对HEAD、origin/main、git status和本阶段发布回执。
2. 补齐独立专业Golden的PDF引用字面量合同，从正常入口复现真实选录值，继续追踪首批PDF失败。
3. 补齐历史R74私有材料，重放完整专业Golden观察目录，执行条件跳过用例。
4. 推进真实SKU、真人Golden、Android instrumentation／设备、Native及跨设备E2E，再按条件验收真实AI、长期监控、WCAG、部署恢复与SLO。

## 历史阶段

| 阶段 | 入口 |
| --- | --- |
| 捕获期限及真实滚阻论文 | [论文交接](AGENT-HANDOFF-2026-11-15-CRR2017.md) |
| 混合尺寸合同及三端离线 | [混合尺寸交接](AGENT-HANDOFF-2026-11-15-MIXED-SIZES.md) |
| 个人Garage及保存比较 | [个人资料交接](AGENT-HANDOFF-2026-11-15-PERSONAL-RECORDS.md) |
| 账户持久归属及会话轮换 | [账户归属交接](AGENT-HANDOFF-2026-11-15-ACCOUNT-OWNERSHIP.md) |
| 成绩PDF原件引用 | [测试PDF交接](AGENT-HANDOFF-2026-11-14-TEST-PDF.md) |
| 许可研究原件与捕获 | [材料交接](AGENT-HANDOFF-2026-11-14-MATERIAL.md) |
| 中国召回AI及监控 | [召回AI交接](AGENT-HANDOFF-2026-11-14-SAMR-AI.md) |
| 来源、PG权限、停机恢复与发布 | [阶段总览](AGENT-HANDOFF-2026-11-14-PUBLISH.md) |
| 更早实现总表 | [历史总表](AGENT-HANDOFF-2026-11-13.md) |

旧KIT C2沿封存状态和原始失败记录处理，细节保留在对应历史卡及验收中。
