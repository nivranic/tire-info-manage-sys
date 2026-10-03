# COHS 实例 — 胎迹轮胎情报系统

> 本目录是 COHS v1.0（Comprehensive Optimization and Hardening Standard，权威正文
> `~/.agents/standards/COHS.md`）在本项目的**实例化载体**：资产清单、风险登记、
> 决策日志与本轮证据索引。按 COHS「适度工程化」原则裁剪：不复制全局标准正文，
> 不引入本项目（本机单用户 PoC 阶段）用不到的基础设施。

## 范围与假设（显式声明，不隐式猜测）

| 项 | 声明 |
|---|---|
| 阶段 | 本机单用户 PoC（`mode=local_single_user_poc`）；无生产部署、无多租户、无公网暴露 |
| Surface | Web(Next 3000)、API(FastAPI 127.0.0.1:8000)、Worker(监控调度)、Windows(Tauri)、Android(Capacitor)、3 共享包 |
| 敌手模型 | 本机单用户；外部攻击面仅限 API 监听 127.0.0.1 与外联抓取的 SSRF/凭据边界（已有白名单/限额门） |
| 数据敏感度 | 轮胎公开数据 + 本机会话；无 PII/金融数据；Keystore 凭据为设备本地 |
| 验证边界 | 阶段/Mock/构建/真实浏览器/原生运行/真实模型是不同证据等级，不可互换（沿 HANDOFF §8 口径） |
| 明确不在本轮范围 | 生产 OIDC/RBAC/RLS、签名分发、SLO/容量/Chaos、真实来源外联（P2 未授权）、真实模型验收（密钥未设） |

## 文件

| 文件 | 用途 |
|---|---|
| `inventory.md` | 资产清单快照（surface/模块/端点/数据资产/集成，多来源校准） |
| `risk-register.yaml` | 开放风险登记（owner + compensating control + 复评触发） |
| `decisions/` | ADR 决策日志（COHS §28 模板裁剪版） |
| `evidence/` | 每轮 assurance 证据索引（引用 .artifacts 回执，不复制） |

## 维护规则

1. 每轮实质性推进后更新 `risk-register.yaml` 与 `evidence/`；重大协议/架构决策入 `decisions/`。
2. 风险关闭需满足：复现 + 根因 + 修复 + 回归 + 独立验证证据链（COHS §53）。
3. 任何 Risk Exception 必须有 owner、理由、补偿控制、到期/复评触发——无永久例外。
4. 「无遗留问题」的正确读法：在声明的范围与证据窗口内，不存在已知且不可接受的问题。
