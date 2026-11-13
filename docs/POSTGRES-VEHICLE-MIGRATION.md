# PostgreSQL 车型 024 维护迁移

普通启动在旧文本车型结构上返回 `vehicle_binary_migration_required`。维护者使用显式 CLI 完成数据库快照备份、016–023 增量步骤和 024 四表变更，随后再部署当前运行合同。

## 执行条件

维护窗口停止 API、Worker 和其他写入方，保全数据库、对象存储、报告与 Parser 资产。准备拥有应用表的维护账户、已安装的 PostgreSQL 17+ 工具，以及[显式连接配置](EXTERNAL-FACT-GOVERNANCE.md)。远端配置采用 verify-full、明确 CA 和 SCRAM，规范回环 IP 可使用 disable。配置文件只保存连接参数。

```text
python -m tire_api.vehicle_binary_postgres_cli --postgres-profile <absolute-maintenance-profile> --pg-bin <absolute-existing-postgres-bin> --backup-file <new-absolute-backup-file> --offline-confirmed
```

入口要求终端隐藏输入一次维护数据库密码。PG 工具进程通过其环境接收密码，密码在该进程退出后释放。请将连接配置和备份放入受控私有目录。备份保留业务数据、数据库对象和对象的所有者／ACL 引用，数据库角色定义由 DBA 备份流程管理。

## 事务与备份

维护事务取得现有 schema 和 ingestion advisory 锁，并对 public 中的既有表取得 SHARE ROW EXCLUSIVE 锁。写入被阻塞后校验旧结构、原件哈希、UTF-8、字节数和逻辑引用。通过后导出该事务快照，使用 pg_dump 生成全新的 custom 备份文件，完成刷盘及 SHA-256 核对，再执行迁移。

备份文件独占创建，成功输出包含格式、字节数及 SHA-256。备份失败会回滚维护事务。部分文件会保留以供排查，复跑应选择全新文件路径。维护事务的锁等待上限为 2 秒，单条语句为 30 秒，备份子进程为 120 秒，事务空闲上限为 180 秒。这些值属于当前维护实现的运行限制。

四张表新增 body_encoding，旧行值为 utf-8。两张车型表的 body 改为可空，并新增可空 raw_capture_id、普通索引、RESTRICT 外键和规定的 CHECK。原有列值、约束、索引、触发器、视图和引用逐项核对，最后追加 024 版本。PG 外键在整个事务中有效。已完成 024 的当前结构返回幂等结果。

## 升级与恢复

024 完成后，部署拥有者继续执行当前增量迁移。再按[运行启动说明](POSTGRES-RUNTIME-SCHEMA.md)从受控空参考库构建、审查并固定匹配最终源码的合同，向 API／Worker 分发运行角色及 verify 配置。

文本枚举 CHECK 在 pg_dump／pg_restore 中可能改变数组转型的表达形式。`postgres-runtime-schema@3` 对已经校验类型的 text／varchar 列，将可解析的字符串成员关系转换为确定形式，继续核对完整成员值。其他结构按现有合同校验。部署需重新构建并批准 @3 合同。

迁移失败后保留固定错误码、备份摘要和原始执行回执，核对事务回滚结果。需要回到旧应用时，在维护窗口将迁移前备份恢复到独立数据库，检查结构、旧行、原件和完整资产后切换。数据库备份的时点早于 024，后续写入的二进制历史需要在部署回退决策中单独处理。

本入口的资产覆盖范围为数据库。对象存储、报告、Parser 文件和生产 IAM 继续由部署流程验收。
