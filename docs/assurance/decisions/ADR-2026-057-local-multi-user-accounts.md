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
   门禁（审计已记 operator_session_id）。**[已被第57/60轮裁决部分推翻，见
   补记1与补记8——curation/identity-revisions 等全局目录写已加门禁。]**

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

## 圆桌裁决补记（2026-10-04）

五角色评审（波次4 多用户账户）对上述 (a)-(e) 的收敛裁决，作为本 ADR 的
修正与补录；所引行号为 2026-10-04 修复后快照。

1. **读路径裁决升级（修正 (d)）**：原 (d) 只聚合列表端点，详情/写/导出仍
   校验单会话，同用户跨会话"看得到打不开"。裁决=所有权校验全部跟随用户
   scope：owned_pack（ai_analysis.py:158-160）、owned_report（reports.py:66-68）、
   离线包 owned（offline_packs.py:206-207）、reparse 运行详情（reparse.py:447）、
   关注删除守卫（main.py:397-399）均改为 `not in scope` / `.in_(scope)`；
   关注去重同步扩到用户 scope（main.py:386），离线包冻结基包内容同样按
   session_scope 解引用（offline_packs.py:326、377）。(d) 中"写路径零改动"
   的表述就此作废。
2. **刻意全局清单补录（补全 (d) 工作区清单）**：除车库/已存比较/驾驶偏好/
   证据文档外，另三类刻意不聚合：tire 告警规则——AlertRule 无会话列
   （db.py:362-367，经 monitor_jobs 归属），monitoring.py 规则端点保持全局；
   站内通知已读态——/v1/notifications 列表与已读写均无会话过滤
   （monitoring.py:405-437），读态全局共享；query_fallback_policies——自述
   scope=current_session 的单会话域（query_fallback_policies.py:529），与
   cookie 同意语义绑定，刻意不聚合到用户。
3. **驾驶偏好全局可写的已知后果**：修订链为全局单链（db.py:270-276，
   revision 全表唯一），/v1/driving-preferences 读写不分用户
   （research.py:247-257）——研究员 B 修改比较权重会改写研究员 A 的比较
   结果，属正确性影响而非隐私观感。接受为现状（存量数据连续性优先），
   重评触发=首个真实多用户共用场景。
4. **session_scope 无界增长**：UserSession 无清理任务（db.py:36-42 有
   expires_at 但无人执行过期清理），session_scope 的 in_ 列表随历史会话
   线性膨胀。PoC 接受；长期需会话过期清理机制。
5. **注册语义补记**：已登录会话再注册→409 already_authenticated
   （auth.py:108-110，防静默改绑丢身份）；首用户判定以 ingestion 锁串行化
   （auth.py:111-113），防并发注册产生双 admin。

6. **治理能力落地（2026-10-04 第58轮，R-014 收窄为 partially-closed）**：
   GET /v1/auth/users（管理员列表，含会话数）、POST /v1/auth/users/{id}/role
   （提权/降级；唯一管理员自降级 409 last_admin 防锁死）、POST
   /v1/auth/users/{id}/password（管理员重置任意用户口令并强制其全部会话
   登出）、python -m tire_api.manage reset-password 本机自救通道（唯一
   admin 忘密码场景；口令仅从参数或 TI_MANAGE_NEW_PASSWORD 环境变量读取，
   源码零字面量）。仍不提供：删户（数据归属未定义）与用户名变更。

7. **路线图收尾（2026-10-04 第59轮，R-014 关闭；解决补记 3/4）**：
   - **守卫 Depends 化**：14 处函数内 require_admin 全部改为
     make_admin_guard(get_db) 依赖工厂（auth.py；各路由模块在自身
     register 闭包内以本地 get_db 装配）。语义变化=守卫先于 body/查询参数
     校验：未登录或非管理员的畸形请求得 403 admin_required（旧实现 422）；
     管理员畸形请求仍 422。时序矩阵测试锚定
     （tests/test_auth_lifecycle.py）。
   - **删户与改名**（补齐第 58 轮遗留）：DELETE /v1/auth/users/{id}
     （管理员；唯一管理员 409 last_admin；数据行不级联删除——归属锚点是
     会话而非账户，解绑后其会话退化为匿名，对任何账户 scope 均不可见，
     行留存本机 SQLite）与 POST /v1/auth/profile（自改用户名/显示名；
     重名 409 username_taken；匿名 403 not_authenticated）。
   - **驾驶偏好私有化（解决补记 3，重评触发被用户"完成剩余路线图"指令
     提前）**：preference_state/append_preference 按 session_scope 过滤
     actor_session_id（research.py），零 schema 变更；revision 列保留全局
     单调计数（全表唯一约束），各主体只见自己链条（修订号可跳档，审计序
     连续）。wire 契约 scope 字段 "local_workspace"→"actor"
     （domain-types 扩为 union，向后兼容）。saved-comparisons 仍为工作区
     共享（补记 2 清单不变）。
   - **会话过期清理（解决补记 4）**：login/register 顺带
     sweep_expired_sessions（UPDATE 解绑过期会话；不删行——数据表
     actor_session_id 外键且连接开启 PRAGMA foreign_keys=ON）+
     python -m tire_api.manage expire-sessions 手动通道。session_scope
     聚合范围不再随历史会话无界增长。
   - **维持部署门控**：会话轮换/scrypt 提档/注册策略/治理在线化四项仍
     锚定 docs/DEPLOYMENT-KEY-POLICY.md，无部署目标不实施。

8. **第60轮圆桌裁决（2026-10-04，五角色评审第58/59轮改动）**：
   - **守卫矩阵澄清与补齐（修正 (e) 原文）**：(e) 的"curation 不设门禁"
     在第57轮"治理守卫补齐"裁决中已被推翻但未同步原文，本轮补记修正。
     现行守卫矩阵=16 处全局目录/审批写端点（原 14 处 + lifecycle-events、
     fitment-relations/revisions——revoke 是全局硬阻断、fitment review 全局
     生效，均适用"写全局共享数据=admin"治理边界）；fitment preview 保持
     开放（模拟预览，无全局写副作用）。golden create/revise 无守卫维持
     观察项（生效经 admin review 把关，消费侧评估创建有守卫）。
   - **会话滑动续期（修复 R2 重大发现）**：main.py 中间件对未过期会话在
     剩余 TTL < SESSION_TTL/2 时滑动续期。原"固定 14 天 TTL 无续期 + sweep
     解绑"组合会让活跃用户每 14 天静默丢失会话锚定的个人数据可见性
     （偏好/关注/AI 历史/证据包/规则草稿）；滑动续期后 sweep 只收敛真正
     不活跃的会话，"登录账户内多端共享"的 UI 承诺成立。
   - **会话数据过户语义（如实登记）**：会话锚定数据在"解绑后再登录他人"
     时并入新账户作用域——这是会话聚合设计的自然延伸，适用于删户、口令
     重置、普通登出换号三个入口；共享浏览器场景下前用户的私有数据会暴露
     给下一登录者及其全部会话。本机威胁模型下接受（需持有该浏览器会话
     cookie）；不做 bind 时阻断（保持聚合语义一致性，避免引入数据迁移
     复杂度）。部署形态如需强隔离，须重新设计归属锚点（联动补记8审计项）。
   - **治理动作审计**：set_role/reset_password/delete_user 补 audit 事件
     （user_role_changed/user_password_reset/user_deleted，detail 含目标
     username 快照）。已知残余：AuditEvent 归属仍锚 session_id→当前绑定，
     换人登录后错归因、删户后失归属——**AuditEvent 增加 actor_user_id
     快照列登记为延迟项**，触发=部署轮启动或首次审计追责需求。
   - **杂项修复**：users 列表 session_count 过滤过期绑定（读数即时准确）；
     update_profile 改名走 ingestion 锁 + IntegrityError 兜底（与 register
     同标准）；测试口令全仓运行时随机化（R5 复核唯一实质残留
     test_auth_accounts.py 修复）；Mimosa 报告的 17 处存量命中经独立复核
     全部定性为模式性误报（验收脚本/测试占位素材/受控枚举拼接）。
