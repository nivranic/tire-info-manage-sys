# PostgreSQL 参考合同与运行启动

API 和 Worker 支持显式 `verify` 启动：比对已批准的参考 schema，不创建表、运行迁移或修复差异。原本地 `migrate` 行为保留。本能力用于分离迁移凭据和运行凭据，尚不代表完整生产部署、OIDC、RLS 或 DML 最小权限验收。

## 参考合同从哪里来

由 DBA 在受控环境准备空的独立 PostgreSQL 17+ 参考数据库。其 PG major、数据库 locale、扩展及版本应与目标部署匹配。可选 pgvector 必须在建合同前单独安装；工具不会安装扩展或创建数据库／角色。

使用[显式 PG 配置](EXTERNAL-FACT-GOVERNANCE.md)指向该空库，并以有权迁移 public 的账户执行：

```text
python -m tire_api.postgres_schema_cli --postgres-profile <absolute-reference-profile> --output-file <new-absolute-contract-file> --empty-reference-confirmed
```

该入口只隐藏读取一次**参考数据库密码**；空参考库还没有应用管理员。它要求 TTY、显式空库确认和全新输出文件。连接参数、TLS／SCRAM 要求和 PG 环境覆盖拒绝沿用已有 PG 配置规则。配置文件不含密码，放在 Git 忽略的私有目录。

工具在 schema advisory 锁内检查 public 无已有业务表、视图、序列、非扩展函数或自定义类型，运行与正常迁移相同的模型注册／迁移／索引逻辑，再捕获合同。已有库即使完全正常也拒绝签发，防止把运行库漂移自动认作期望；不覆盖已有输出文件。

迁移未限定 schema 的 DDL 在 public 优先的事务局部查询路径下执行；捕获恢复 pg_catalog、public 的固定顺序。运行校验也使用后一顺序。这里没有授予对 pg_catalog 的创建权限。

成功 JSON 返回合同 SHA-256、PG major、关系数和包内 Python 源码摘要。合同只含结构、迁移版本和环境信息，没有业务行、密码、数据库名／所有者名或本机路径。输出大小最多 8 MiB；失败后可能保留未通过交付的参考库或部分文件，不能据“文件存在”认定合同有效。

## 配置 API 与 Worker

部署者独立审查并固定合同和输出摘要。把合同作为受控只读部署文件分发，设置以下三个变量；路径和摘要不得在运行启动时从待验数据库或文件自动推导：

```text
TI_DATABASE_SCHEMA_MODE=verify
TI_DATABASE_SCHEMA_CONTRACT=<absolute-approved-contract-file>
TI_DATABASE_SCHEMA_SHA256=<approved-64-character-lowercase-sha256>
```

数据库连接继续使用现有 TIRE_DATABASE_URL／DATABASE_URL，并改为合适的非拥有者运行账户；口令由部署秘密管理提供，不写入仓库或部署脚本。运行账户应有业务所需的 DML／锁权限，但无需 schema CREATE、表拥有权或迁移凭据。原[许可操作员角色](POSTGRES-GOVERNANCE-ROLE.md)用途不同，不能拿来充当整个 API／Worker 的运行角色。

API lifespan、Worker 正常入口都通过 Database.initialize 分派到校验；不需要新增 Web 接口或另一个 Worker 实现。显式 verify 仅支持 PG，缺少路径／摘要、配置无效、摘要／源码／PG major／结构不匹配均拒绝启动，不转回 migrate 或 SQLite。设置了合同却忘记 verify 也会拒绝，避免意外执行 DDL。已有依赖 Database.initialize 的辅助工具同样遵守该进程的配置。

verify 连接固定 search_path 为 pg_catalog、public，并使用 READ COMMITTED；校验事务设置 READ ONLY、锁等待 2 秒、单条语句 5 秒和事务空闲 15 秒。该连接的 URL options 会被固定 search_path 覆盖，不应再用 URL options 注入查询路径；其他 TLS 连接参数仍需按部署要求明确配置。这些超时不是端到端启动 SLO。

## 校验范围

合同绑定当前包内所有 Python 源文件的相对路径与规范换行摘要；任何 Python 源码变化都要求重新构建、审查合同。需要部署可读的 Python 源文件，不支持仅含 pyc 的制品。这不是依赖二进制或整个容器镜像的签名证明。

当前合同格式为 `postgres-runtime-schema@3`。列按表名与列名排序，消除 ADD COLUMN 导致的物理列顺序差异；类型、可空性、默认值、identity／generated 与 collation 仍完整比较。文本枚举 CHECK 在 pg_dump／pg_restore 后可改变数组转型表示，@3 对已经核对类型的 text／varchar 列规范化可解析的字符串成员关系，成员值仍完整核对。@1／@2 合同需从受控空参考库重新生成并批准合同及 SHA-256。

public 的表／列／类型／默认值、主外键与 CHECK／NOT NULL、索引及有效状态、用户触发器及 FK 内部触发器状态、应用函数定义、迁移版本、扩展版本和数据库 locale 都参与精确比较。内部触发器的数据库局部 OID 名称不参与比较，约束身份与保护状态仍保留。引用业务数据、索引统计、序列当前值和迁移时间戳不参与比较。

当前合同版本明确拒绝 RLS／策略、非扩展自定义类型、继承以及尚未支持的聚合／窗口例程；不能静默忽略未覆盖语义。pgvector 扩展对象按扩展版本处理，派生 embedding_vectors 表仍完整比对。扩展二进制和 PG 服务端属于受信部署基础，不由此合同验证。

运行角色阶段增加了两个固定 SHARE 锁函数，由迁移账户安装，PUBLIC EXECUTE 已撤去，完整定义参与合同。部署升级需要重新生成并批准空参考合同。新的 DML 运行策略及只读检查见[2026-11-14 交接卡](AGENT-HANDOFF-2026-11-14.md)。正常向量构建仍动态创建 HNSW 索引，当前非拥有者综合验收在该入口失败。索引维护、模型空间、参考构建与恢复的衔接仍待完成，完整运行角色业务验收继续跟踪。

参考是空库构建的确定结构。本轮已覆盖现有 core 使用的合成 001–004 缺列前驱：升级后列顺序规范化匹配，旧行不变，新增历史字段保持 NULL，重复迁移稳定。此范围不代表任意部署旧库兼容；默认值、类型、约束等差异仍会拒绝，不能将运行库重新签名来绕过差异。启动校验是维护窗口中的快照，不能阻止管理员之后的 DDL 或代替业务数据完整性检查。

## 发布与回退

升级前停止相关运行进程，备份数据库及证据／报告／Parser 资产；独立验证新迁移和回退，再用匹配源码、major、locale、扩展的空参考库生成新合同。迁移凭据只用于明确的维护步骤，运行服务分发新代码／合同／固定摘要并使用运行账户启动。现有本地自动迁移路径不是完整生产迁移编排工具，仍需完善。

校验失败先保留错误码与原合同，核对可信制品和实际 schema。不要通过切换 migrate、移除检查或扩大运行账户权限来消除失败。回退时恢复匹配的一组代码、schema 和合同，并按实际备份恢复验收；不能只换合同摘要。

本轮 141 项受管回归和 22 项真实 PG 验收见[验收记录](assurance/evidence/postgres-runtime-schema-2026-11-14.md)。实际 PG 角色采用较宽 DML 权限验证无拥有者启动；完整业务 DML 最小权限、旧 PG 库兼容、真实远端、操作系统终端及生产 IAM／RLS 继续待验。

后续[升级合同验收](assurance/evidence/postgres-upgrade-contract-2026-11-14.md)取得 141 项回归和 29 项真实 PG 检查通过。正式历史 035 代码建库后升级亦匹配，154 张旧表的 38 行及版本时间保持。后续已提供[PG 024 显式维护入口](POSTGRES-VEHICLE-MIGRATION.md)，完成历史 015 合成车型证据的升级、独立恢复与当前 API 读取。部署旧库继续按实际环境验收。
