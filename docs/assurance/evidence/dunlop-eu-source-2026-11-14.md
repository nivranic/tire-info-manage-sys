# Dunlop 欧洲规格来源与独立进程验收

日期为 2026-11-14，继续验收基线为已发布的 `b2860fd`，功能提交为 `224ade3`。本阶段补齐 Dunlop 在独立 uvicorn、非拥有者 PostgreSQL/TLS 与正常 API 下的实际消费证据。完整 V1 持续进行。[实施计划](../../plans/2026-11-14-dunlop-eu.md)

## 来源与字段范围

固定欧洲 SPORT MAXX RT2 产品页已取得 robots 允许访问及实际 200 回执。指定 Angular transfer-state 响应内有 27 条规格，Material Code 与有效 GTIN 各 27 个。22 条具有明确 XL，另外 5 条的独立 XL 为 null。载重速度、几何尺寸、Material Code/rep_code、GTIN 校验及逐行 EU 标签由确定性 Parser 核对，各字段保留 JSON 路径证据。[官方规格页](https://www.dunloptyres.com/en/tyres/sport-maxx-rt2)

厂商 EPREL ID 与链接按厂商声明保存，监管绑定继续待验。M+S、雪地、冰地、轮辋保护按行级声明保存，mobility technology 与 OE 品牌/车型维持原文范围。独立防爆、静音与 OE 标记继续待证。开放再分发及专业材料复用许可继续核对。[官方 robots](https://www.dunloptyres.com/robots.txt)

## 已观察的正常入口

| 范围 | 结果 |
| --- | --- |
| 前序在线 canary | 明确选择 dunlop-eu、SPORT MAXX RT2、235/55R19，首次及重复读取均 ok，匹配 2 条，真实隔离 Parser 完成并回收 |
| 前序正常 ASGI | 注册、来源与 live-query 路由共 17 项通过，两次 live，1 份快照、2 个 variant、2 次 verification，历史证据与哈希核对通过 |
| 本轮独立 HTTP/PG | 正常 uvicorn 进程、TLS、非拥有者运行角色与批准空参考 @4 合同，来源管理目录含 17 项，Dunlop 为 ready/can_fetch |
| 实际官网查询 | 两次正常 live-query 均 live，各自实际执行 Windows Job Parser，退出 0、reaped=true、stderr 为空 |
| 精确版本 | `543000`、GTIN `5452000703941`、101Y、XL=null 与 `544985`、GTIN `5452000725776`、105Y XL 保持两个独立 variant ID |
| 重复核验 | 两条 SKU 的 fact_version 均为 1，身份 source_scoped，Parser 部署修订保持 1，两个原始证据均可重开并核对正文哈希 |
| 最终同原文重复读取 | 原件 520,389 字节，SHA-256 为 `604131c4cee7c582852d1fc8e3d88d13c9f28ac1d9a51eaa84e76de933ed51cf`，复用快照与原始观察时间，verified_at 更新 |
| 基础进程与恢复 | 12 项全部通过，含 166 张模型表、1 份已有原件、199 个 Parser 资产文件独立恢复与恢复后消费 |

PG 基础流程采用已有 Hankook 录制片段，Worker 检查来源不可用终态，租约恢复采用既有隔离时间戳装配。最后一项扩展使用真实 Dunlop HTTPS，经恢复后的实际 HTTP 服务与非拥有者 PG/TLS 消费。真实模型保持关闭，生产及长期运行按后续 Gate 验收。

## 原文变化与事实版本

第二批两次正文均为 520,389 字节，相差 10 字节，位于页面社交组件的 `rev`。两份正文解析出的 27 条轮胎数据完全一致。正常 API 为不同原文保存两个独立快照，两个 SKU 的 ID 与事实版本保持稳定。

最终批次的两次原文哈希相同，正常 API 复用同一快照，保留最初 observed_at 并更新 verified_at。验收脚本按原文哈希检查快照，再通过证据 API 重开各次观察的原始正文、哈希及 observed_at。相关原件和差异诊断保存在本机忽略槽。

## 原始失败及纠正

| 批次 | 已取得证据与失败原因 | 处理 |
| --- | --- | --- |
| 第一批 | 前 11 项通过，Dunlop 第一次实际查询为 live。私有脚本 write_text 在 Windows 保存正文时转换 22 个换行，保存文件哈希与原 API 正文哈希不同，规范换行后的哈希与原件一致 | 私有验收脚本改为 write_bytes，保留原文件与回执 |
| 第二批 | 前 11 项通过，两次 live、两条事实版本稳定，脚本仍要求两个 provenance 相同。正文社交组件 rev 实际变化 10 字节，生成两个对应快照 | 根据现有原件快照合同修正脚本校验，检查相同原文复用、不同原文分开保存及各次证据重开 |
| 最终批次 | 12 项全部通过，847 项输入稳定，来源两次 live，资源回收核对通过 | 保存完整回执与统一断言 |

本轮业务源码沿 `224ade3`，API 包摘要与前序 79 项、371 项及 16 项回归绑定相同。上述两处纠正发生在 Git 忽略槽内的验收脚本。前序回归的首批 360/371 及普通宿主权限对照 16/16 结果继续保留。[回归与交接](../../AGENT-HANDOFF-2026-11-14-PUBLISH.md)

## 合同与资源回收

API 包源码 SHA-256 为 `1db34a8b02cc8571b7c76b9c6e1819e54a59cc75d9ccdbde204627769fec1203`。本批独立空参考库生成的 @4 合同 SHA-256 为 `1bb06c0de86d15c2d6d0f90dbb0546778b43814d77fc928e03ab3f4583390b6e`，运行角色依据该固定摘要使用 verify 启动。实际部署继续独立生成、审查并批准匹配环境的合同。[运行合同](../../POSTGRES-RUNTIME-SCHEMA.md)

三个一次性集群均已停止。36 个服务记录均回收，43 个进程 ID 的结束后系统快照为空，19 个端口可重新绑定。postmaster.pid、初始化口令、TLS 私钥与 Parser 临时目录已核对移除。最后 Dunlop HTTP 服务沿 Ctrl+C 完成退出，启动器与实际服务退出码均为 0。

本轮私有 wrapper 基于正式 `scripts/verify-postgres.ps1`，只调整仓库定位、已安装解释器、来源验收扩展及本批指针落点，保留集群、TLS、角色、合同、恢复和结束回收流程。

## 回执绑定

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-1a03c965d88c49dba6d2b2674c233239/report.json` | `ea6caac02edda5227423ada00045162753bd94511f7e75d9f6aed11019a7cf7b` |
| `.artifacts/postgres/pgverify-d2ec942ec65f4fadacbedd9b5a50ec4d/report.json` | `9b8aff9c78c7105fcd40b267a277e0405a716acf195c513b389f1b23432d56e4` |
| `.artifacts/postgres/pgverify-3e665118663542899c6710014515c093/report.json` | `7eb4df2cbeb47485295eb44aeccc9a8d32f894d08398cb5a15c5e410058c8cdf` |
| `.artifacts/dunlop-source-20261114/pg-assertions.json` | `1f6c3de056c726aa69231e769d68e33aa567bc380bdf3f3a4f539df9b23e2af8` |
| `.artifacts/dunlop-source-20261114/response-difference-r2.json` | `d70abbea912242a428f47c5b4d01f4952bfdbab87c7e97fac10c52fd0601f856` |

`pg-assertions.json` 进一步绑定三批回执、对应驱动版本、系统进程快照和差异诊断。统一断言核对当前 847 项输入与前序回归清单、源码合同、真实查询、版本稳定、原件哈希及资源关闭。私槽随本机保存，新 clone 通过正常来源 API、正式 PG 生命周期及源专项扩展重建对应证据。

## 接续验收

继续其他 P0 来源与地区、代表性精确 SKU、人工 Golden、EPREL 独立监管绑定及正式数据许可。真实 OpenAI Responses/Embeddings、公网 Webhook、自然长周期监控、Native 设备、无障碍、Linux/服务管理器、远端部署与生产 SLO 继续推进。
