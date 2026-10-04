# 部署密钥政策（DEPLOYMENT KEY POLICY）

> 生效：2026-10-03，用户明确约束。适用于本项目任何"部署到服务器/对外提供服务"的形态。

## 红线

1. **GLM Coding Plan 专用密钥严禁用于任何服务器部署。** 该密钥按个人编程订阅计费，
   服务端流量模式（多用户/高频/自动化）会触发封禁。它只允许出现在**本地开发机的
   用户级环境变量**中（当前仅 `HKCU\Environment` 的 `TI_ANTHROPIC_API_KEY`）。
2. 任何 AI Provider 密钥（`TI_ANTHROPIC_API_KEY` / `TI_CHAT_API_KEY` /
   `TI_OPENAI_API_KEY`）都**不得**写入仓库源码、配置文件、`.env`（被 gitignore 也
   不行，历史会被提交）、Docker 镜像层、CI 变量的明文字段或部署脚本字面量。
3. 服务器部署必须使用**独立计费的 API key**（按量付费账号），并与本地开发密钥
   物理隔离（不同密钥、不同环境）。

## 部署前置检查（部署轮必须逐项执行）

- [ ] 服务器环境中的 `TI_*_API_KEY` 均来自独立计费账号，与本地 Coding Plan 密钥不同
- [ ] 镜像/制品扫描无任何 `TI_` 密钥字面量（`grep -r "TI_.*KEY" 构建上下文` 为零命中字面量值）
- [ ] `.env` / compose / k8s secret 引用均来自密钥服务或运维托管，不进 git
- [ ] AI 预算护栏（`TI_AI_DAILY_REQUEST_LIMIT` / `TI_AI_DAILY_TOKEN_LIMIT`）按服务器
      场景重新设定，不复用本地默认
- [ ] 登录成功必须轮换会话 ID：当前 `bind_session`（apps/api/tire_api/auth.py:99-104）
      仅把 user_id 写进既有 cookie 会话、不换 ID——会话固定风险在 loopback 单机
      可接受，服务器形态必须改为登录成功后轮换
- [ ] scrypt 成本参数复评：当前 N=2^14（auth.py:27）低于 OWASP 对交互式登录的
      建议（N≥2^16），部署轮须按服务器实测登录延迟后上调
- [ ] 注册策略与首用户引导窗口重审：当前开放注册、首用户先到先得成为 admin
      （auth.py:107-115），服务器形态必须改为受控注册并重新设计管理员引导
- [ ] 账户治理能力补齐：当前无提权/降级、改密、删户、用户列表端点（auth.py 仅有
      register/login/logout/me），部署前必须补齐；唯一 admin 忘密码时只能手改
      本机 SQLite（见 risk-register R-014）

## 现状（2026-10-03）

项目尚无服务器部署（生产部署属路线图 P2 项，见 HANDOFF §6）；当前密钥只存在于
本地开发机用户环境变量，仓库与产物中零密钥字面量（Mimosa 凭据模式扫描 0 命中）。
本文与 `docs/assurance/risk-register.yaml` R-011 为该约束的权威记录。
