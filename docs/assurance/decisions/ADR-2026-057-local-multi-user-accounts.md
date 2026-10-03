# ADR-2026-057: 本机多用户账户——stdlib scrypt + cookie 会话绑定 + 读路径聚合 + 首用户即管理员

- Date: 2026-10-03
- Status: approved & implemented（波次4；用户决策=完整多用户+权限分级 admin/研究员）
- Affected assets: apps/api/tire_api/auth.py（新）、db.py（users 表与 local_sessions
  加列）、migrations.py（014_local_sessions_user）、读路径 main.py /
  ai_analysis.py / ai_rule_drafts.py / embedding_api.py / offline_packs.py /
  reports.py / monitor_tasks.py / recall_monitoring.py /
  recall_discovery_monitor_routes.py、管理守卫 source_settings.py /
  parser_releases.py / quarantine_review.py / identity_contract.py
- Related: docs/DEPLOYMENT-KEY-POLICY.md；risk-register R-011/R-012

## Context

原 local_sessions 为纯匿名 cookie（main.py 注释明示 production identity 未
实现）；核验人 operator 为自由文本，无身份约束。用户决策：实现完整的本机多
用户账户与权限分级（admin / 研究员），不引入 token、不新增第三方依赖。

## Decision（a-e）

1. **(a) 口令哈希 = stdlib hashlib.scrypt**：N=2^14、r=8、p=1、dklen=32、
   32 字节随机盐；存储格式 `scrypt$n$r$p$salt$hash`；校验用
   `hmac.compare_digest` 恒时比较——零新依赖。
2. **(b) 存储**：新增 `users` 表（apps/api/tire_api/db.py，ORM 模型经
   create_all 建出）；`local_sessions` 加可空 `user_id`（迁移
   `014_local_sessions_user`，照 006 裸列先例不带 FK 约束；既有会话保持
   NULL=匿名）。
3. **(c) 端点与角色**：`/v1/auth/register|login|logout|me`
   （apps/api/tire_api/auth.py）。登录=把 user_id 绑定到当前 cookie 会话
   （不引入 token），登出=解绑；首个注册用户 `is_admin=true`，其余 false；
   进程内按用户名失败计数限速（5 次连续失败→60s 封锁，重启清零可接受）。
4. **(d) 读路径聚合，写路径零改动**：`session_scope(db, session_id)` 返回
   绑定用户的全部会话或仅本会话，匿名行为不变；应用于 session 过滤列表
   （`.in_(scope)`）：watchlists/changes（main.py）、AI 历史（ai_analysis/
   ai_rule_drafts）、embedding、报告、离线包、监控规则草稿、召回监控×2
   （recall_monitoring / recall_discovery_monitor_routes）、监控任务
   （monitor_tasks）。车库/已存比较/驾驶偏好/证据文档维持工作区全局共享：
   既有 `scope=local_workspace` 是明确设计且 UI 文案即「共享车库」，跨会话
   可见已满足；改为用户私有会破坏存量数据连续性——此为勘察后的事实修正。
5. **(e) 管理写守卫 require_admin**：来源设置 revisions
   （source_settings.py）、解析器 bootstrap/transitions/evaluations/reviews
   （parser_releases.py）、隔离复核 reviews（quarantine_review.py）、身份
   迁移 apply（identity_contract.py migration-applications）返回
   `403 {"code": "admin_required"}`；事实/身份修订等研究员 curation 不设
   门禁（审计已记 operator_session_id）。

## Verification

实现锚点（本轮逐文件核对）：auth.py 的 scrypt 参数/格式/恒时比较/限速常量；
db.py User/UserSession；migrations.py 014；session_scope 上述全部读路径接线；
require_admin 在 (e) 列出的四类端点内调用。账户家族行为验收随波次4收尾执行
（本 ADR 定稿时未运行全量测试，不作"已绿"声明）。

## Known disadvantages / Residual risk（边界原文）

- 这是 loopback 单进程服务的本机角色分级，不防御本机恶意进程（cookie 与本机
  SQLite 对本地进程可读）；不得作为服务器部署的鉴权方案直接使用（联动
  docs/DEPLOYMENT-KEY-POLICY.md 与 R-011/R-012）。
- 注册开放=本机任意使用者可注册为研究员（loopback 形态接受）。
- 限速为进程内计数，重启清零（PoC 接受，不承诺跨进程防护）。

## Rollback trigger / Revisit condition

任何"部署到服务器"动议触发 R-012 复评：本方案不迁移、须重新设计鉴权。
