# 胎迹 Agent 交接卡

更新于2026-11-15，本轮基线33b2807，沿现有main收尾。用户要求“完成本轮次后，暂停推进，更新交接文档，再给我一段交接提示词”。提交、push及远端核对后暂停目标，后续实施等待用户明确接续。完整V1仍有发布验收待完成。

发布提交从Git和本轮私有.artifacts/golden-pdf-20261115/publish.json核对。提交前撰写的文档以阶段基线定位代码，本轮验收摘要固定在下列文档中。[原始规格](requirements/2026-09-26-tire-intelligence-original.md) [本轮验收](assurance/evidence/professional-golden-pdf-2026-11-15.md) [实施计划](plans/2026-11-15-professional-golden-pdf.md)

纯clone可用下面的只读命令定位包含本交接卡的最新提交，再与当前HEAD及实时远端比较。后续提交到来后，以Git历史保留本轮发布定位。

```powershell
git log -1 --format=%H -- docs/AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md
git log --follow --format="%H %as %s" -- docs/AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md
git rev-parse HEAD
git ls-remote origin refs/heads/main
git status --short --branch
```

## 总需求与已有决定

原规格共12个核心模块、10项发布Gate、13项SLO及15项待确认决策。用户此前授权实施、复核优化、验证、提交、push和交接，专业材料由agent自主选择。用户最新要求将本轮结束后的推进状态调整为暂停。

首个真实模型采用用户指定的OpenAI Responses API。EPREL暂无Key，凭据缺失时继续独立工作。密钥通过本机环境配置。新分支／worktree及代理使用按当次明确授权处理，PowerShell使用7。原件、私库和验收回执位于Git忽略目录。

已落地的实施选择包括旧共享个人记录依据创建证据归创建者私有、捕获总期限上限70秒，以及本轮使用独立场次模式承载暂缺精确SKU身份的论文成绩。这些选择由agent制定，后续接手时可依据产品验收核对。

## 本轮交付

- 独立专业Golden增加可选PDF引用和出版物角色，冻结材料标签、提取器版本、页码及码点区间。纯函数依据独立原件摘要和正常上传的运行时标识生成预期引用。7份旧案例序列化与原字面量相等。
- 增加test_event_http模式，通过正常上传、保存和读取入口复现完整场次，显式声明空SKU、桥、候选和来源复核范围。旧private_http模式继续要求其完整SKU桥证据。
- 新增2017年滚阻论文独立字面量，核对两胎、11路面、22条成绩，保留原4胎范围、选录状态、混合尺寸、PDF第4页表2、出版物角色及50 km/h例外。数据按出版方CC BY 4.0保留作者与出处。[数据说明](../packages/domain-types/fixtures/professional-test-pdf-v1/README.md)
- 恢复R74缺失的两份JSON回执和PDF原件，三份字节数及SHA-256均匹配冻结清单。JSON从历史工具回执恢复，PDF由新隔离库正常HTTPS捕获。全部9个外部文件绑定通过，捕获数据库已关闭。
- 完整7案例观察器重放完成。原先依赖R74材料而跳过的54项，已按历史nodeid及计数逐一交叉核对，本轮54项全部执行通过。

## 实际验证及证据范围

| 验证 | 本轮结果 |
| --- | --- |
| 新合同红批 | 1项失败，复现旧合同拒绝新形状 |
| 合同及旧序列化专项 | 13通过 |
| PDF正常HTTP及篡改专项 | 14通过，含真实22值与重算摘要反例 |
| 既有合成桥及新模式范围 | 7通过 |
| 最终6模块受管回归 | 243通过，0失败、0跳过、0不完整 |
| 最终输入及进程 | 869输入稳定，25个受管子进程全部exit 0并回收 |
| 原54项条件用例 | checks 20、bindings 10、review 24，全部通过 |
| 完整旧观察器 | 7／7案例完成，state=passed，release_gate=inconclusive |
| 观察器检查覆盖 | 8项已知关联、3项不同身份对，源码稳定 |
| 资源关闭 | resources_closed=true、捕获库关闭、受管存活子进程0 |
| 真实外部模型调用 | 0 |

纯比较器结果的evaluation_mode为offline_bound_snapshot，CaseResult.private_http_observed固定false。实际当前HTTP执行由受管回归及actual.execution记录。真实论文成绩继续为manual_transcription／unverified，代表性真实精确SKU正例和真人Golden均为0，human_truth_status为pending_external_review。

本轮API验收覆盖professional_golden_checks、professional_golden_bindings、professional_golden_review、professional_golden_corpus、professional_golden_cli与test_test_events。数据库迁移为036，PG运行合同postgres-runtime-schema@4，FTS为accepted-heads-fts@7。目标PG部署仍需依据实际catalog及当前API源码生成批准合同。

前阶段API239、Web69、PG／TLS6及浏览器复跑11项的范围见前阶段验收。前阶段首批6项PDF回归失败和首次浏览器409原因仍待确认，其后复跑通过，历史失败回执已保留。[AI成绩选择交接](AGENT-HANDOFF-2026-11-15-AI-SELECTION.md)

## 12模块进度与余项

| 模块 | 已有实现 | 主要余项 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、筛选、授权回退、13区域目录 | 其余P0来源／地区及长期稳定性 |
| 精确版本 | 代码、GTIN、OE、地区、冲突、Golden及SKU桥 | 代表性真实SKU、真人Golden及错合并指标 |
| 车型适配 | SU7轴位、个人Garage、官方PDF与SKU桥 | 更多车型、OE及Native真实消费 |
| 比较 | SKU、个人保存、混合尺寸、条件和真实选录值 | 精确SKU正例及推荐质量 |
| 测评库 | TestEvent、逐胎尺寸、PDF引用、22条真实成绩及独立PDF合同 | 人工复核、更多真实来源及精确身份 |
| 信息监控 | Worker、差异、三地召回、通知与SSE | 自然长周期、lag及更多差异 |
| CRUD | 来源、规则、偏好、测试、账户、Provider与费用规划 | 全实体、生产权限、BYOK及账单 |
| 证据浏览 | SHA、Parser、引用恢复、许可PDF捕获 | 实际部署、许可治理及对象存储 |
| 个性化 | 关注、偏好、兴趣、个人Garage及保存比较 | 跨设备、其他共享实体及长期质量 |
| AI研究 | grounding、流式、报告、检索评估及显式成绩选择 | 真实Responses／Embeddings及语义质量 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key、PG角色 | 公网接收端、吞吐、SDK产品化及完整WebSocket |
| 管理后台 | 健康、回滚、隔离、任务、纠错与审计 | 生产IAM／Tenant／RLS及完整发布验收 |

## 发布验收余项

10项Gate仍需针对实际发布范围取证。

| Gate | 主要余项 |
| --- | --- |
| P0来源provenance 100% | 补齐来源及地区覆盖 |
| 未授权本地回退0次 | 全平台核心流程 |
| Golden SKU错合并0次 | 代表性真实人工Golden |
| AI事实回答引用覆盖100% | 真实模型、代表性材料和语义质量 |
| 高危AuthZ／SSRF漏洞0 | 生产权限及完整安全验收 |
| P0／P1未处理故障0 | 开放风险和发布全量回归 |
| WCAG 2.2 AA核心流程 | 读屏、全部交互状态及完整流程 |
| 六类目标平台核心E2E | Windows、macOS、Linux、Web、Android及iOS矩阵 |
| Adapter健康及回滚 | 全P0来源及长期运行 |
| 数据库／Parser版本回退 | 实际部署切换与完整发布包回退 |

13项SLO覆盖结构化查询P95≤300ms、设备本地检索P95≤200ms、输入反馈≤100ms、移动网络LCP≤2.5s、Adapter自身开销≤300ms、权威源正常响应时live query P95≤3s、按源策略5–10s超时、通知lag≤5min、后续99.9%可用性、RPO≤15min、RTO≤60min、未授权回退0次及Golden错合并0次。生产级达标证据仍待逐项建立。

原规格15项决策覆盖首批轮胎范围、首发地区、本地知识库定义、完全单机模式、Offline Pack大小、用户／Tenant体系、VIN留存、AI付费方式、中国区Provider、价格／库存监控、专业数据授权购买、Windows 10支持期、Native分发、用户量／SLA及企业私有部署。逐项依据原规格和用户后续明确决定处理。

## 私有资料及重放

关键回执位于.artifacts/，摘要见本轮验收。新clone需要按冻结摘要取得材料，才能重放依赖原件的验收。

### 代码与冻结清单

| 入口 | 位置 |
| --- | --- |
| 独立合同、PDF绑定与比较 | [professional_golden_checks.py](../apps/api/tire_api/professional_golden_checks.py) |
| 正常上传与两种HTTP观察入口 | [professional_golden_support.py](../apps/api/tests/professional_golden_support.py) |
| 合同、篡改及真实22值回归 | [test_professional_golden_checks.py](../apps/api/tests/test_professional_golden_checks.py) |
| 7案例与9个外部文件的准确路径、字节数、摘要 | [冻结manifest](../packages/domain-types/fixtures/professional-test-bridge-v1/manifest.json) |
| 22值、原件路径及PDF范围 | [新字面量](../packages/domain-types/fixtures/professional-test-pdf-v1/real-crr2017-original-measurements.json) |
| 完整观察器 | [run_professional_golden.py](../scripts/run_professional_golden.py) |
| 受管回归及资源边界 | [run_api_worker_regression.py](../scripts/run_api_worker_regression.py) |

### 资料恢复与验收定位

原9绑定包括仓库内6份合成PDF及忽略目录3份R74材料。6份合成PDF随Git取得，3份R74的路径见下表，精确摘要见冻结manifest和本轮验收。新clone还需取得新字面量指定的2017年论文原件。

| 目录 | 内容 |
| --- | --- |
| golden-pdf-20261115/ | 恢复记录、原54项交叉核对、资源关闭及发布回执 |
| golden-pdf-20261115-final/ | 最终6模块结果及逐项执行报告 |
| r76-http-golden-pdf-20261115/ | 7案例实际观察、比较报告及执行回执 |
| r74-original-recovery-20261115/ | 新隔离库正常捕获与关闭结果 |
| r74-live-c726bf6f944a4e6fb094e7ec79188e23/ | 冻结清单要求的捕获回执及PDF原件 |
| r74-pdf-review-8ef032fe57a44573b3c1f5e7cb771ad5/ | 冻结清单要求的复核JSON |

2017年论文原件的位置、字节数和摘要由新字面量及数据README规定。材料缺失时对应真实HTTP用例条件跳过，摘要错误时失败。完整旧观察器依赖专业Golden原清单中的9个外部绑定。旧KIT C2的历史封存状态与原始失败记录继续按历史卡处理。

同机接手可直接核验这些已恢复文件。异机接手需从具备访问权限的原工作区或原始工具回执取得两份R74 JSON，按原字节及换行恢复，并校验冻结摘要。其恢复脚本和校验记录位于.artifacts/golden-pdf-20261115/r74-recover-json.py及r74-json-recovery.json。历史JSON包含当时的捕获与复核标识，重放依赖这些归档字节。R74 PDF可通过本轮验收链接的出版方及既有许可策略正常捕获，再核对原件摘要。缺少归档回执时，完整旧观察器会报告外部证据缺失，相关验收保持待验。

前阶段首次PDF失败的逐项回执为.artifacts/ai-measurement-selection-20261115-regression/test-reports.json，独立诊断和最终批分别在ai-measurement-selection-20261115-diagnostic及ai-measurement-selection-20261115-final。浏览器首次回执为.artifacts/ai-measurement-selection-20261115-real/web/run-86db1bee-1d23-4bac-a312-8d0b7bbaaecb/report.json，复跑为同级run-4ac8b453-73f7-495a-925b-5f4ecf7844bc/report.json。PG回执为.artifacts/postgres/pgverify-542a012c1bdf466bba74cd7220e6749b/report.json。上述路径的结果摘要保留在前阶段验收中。

在材料齐备的工作区，可用新的输出目录重放。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_professional_golden.py --output .artifacts/<new-observer-run>
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/<new-regression-run> --actual-dir .artifacts/<new-observer-run> --targets apps/api/tests/test_professional_golden_checks.py apps/api/tests/test_professional_golden_bindings.py apps/api/tests/test_professional_golden_review.py apps/api/tests/test_professional_golden_corpus.py apps/api/tests/test_professional_golden_cli.py apps/api/tests/test_test_events.py
```

## 用户明确接续后的顺序

1. 阅读本卡、原始规格、本轮验收和前阶段AI选择交接，核对main、HEAD、origin/main、工作区及发布回执。保护已有改动。
2. 从原始失败回执追踪前阶段首批PDF失败及浏览器409。当前根因待确认，已有复跑通过证据。
3. 推进代表性真实精确SKU与真人Golden，扩大来源、地区和身份覆盖。复用本轮PDF字面量与正常入口验收。
4. 完成Android instrumentation／设备、Native宿主和跨设备E2E，再按实际条件推进Responses／Embeddings、EPREL、自然长周期监控、WCAG、生产恢复和SLO。

## 可复制接手提示词

```text
接手胎迹完整V1。先读docs/AGENT-HANDOFF-CURRENT.md、docs/AGENT-HANDOFF-2026-11-15-GOLDEN-PDF.md、原始规格及卡内验收链接，核对main、HEAD、origin/main、工作区和本轮publish.json。

上一聊天已按用户要求在本轮收尾后暂停。本消息授权接续时再开始实施。完整范围为12模块、10项发布Gate、13项SLO和15项待确认决策，剩余项按最新交接卡推进。

本轮已完成独立PDF成绩合同和test_event_http正常入口，核对2017年论文22条成绩，按冻结SHA恢复R74全部三份缺失材料。最终6模块243通过、0失败、0跳过、869输入稳定，25子进程退出并回收。旧7案例工程检查通过，release_gate=inconclusive，真实SKU正例和真人Golden均0，真实模型调用0。私有材料在忽略目录，新clone须按摘要重建后重放。

优先核对历史首批PDF失败和浏览器409原始回执，再推进真实SKU、真人Golden、Android／Native／跨设备和其他发布验收。真实模型采用OpenAI Responses API，EPREL暂无Key，凭据缺失时推进独立工作。沿现有架构和main工作，保护已有改动，使用PowerShell 7。新分支／worktree及代理使用须有当次明确授权，原件、私库、凭据及个人绝对路径保留在Git忽略目录。交付时明确已实现、实际验证、失败及待验范围。
```
