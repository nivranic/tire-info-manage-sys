# PostgreSQL HNSW 索引维护

HNSW结构由数据库拥有者在维护窗口部署。verify模式的API／Worker依据批准的模型空间声明和索引目录执行只读检查，计划与构建在外发前核对，写入向量后再次检查。默认migrate模式沿用本地按模型空间建索引行为。

## 声明模型空间

清单格式为 `postgres-vector-indexes@1`，最多32项，维度为1至2000的整数。每项精确声明64位小写模型空间摘要和维度，重复项及截断索引名碰撞会被拒绝。

```json
{
  "schema": "postgres-vector-indexes@1",
  "indexes": [
    {"model_space": "<64-character-lowercase-model-space-sha256>", "dimensions": 1536}
  ]
}
```

摘要由现有EmbeddingConfig.model_space计算，绑定Provider、模型、维度及适用的端点范围。配置齐备时可在已安装API的环境执行以下本地代码生成清单。该操作输出模型空间及维度，全程仅读取本机配置。

```python
import json
from tire_api.embedding_gateway import configured_embeddings

config = configured_embeddings()
print(json.dumps({
    "schema": "postgres-vector-indexes@1",
    "indexes": [{"model_space": config.model_space, "dimensions": config.dimensions}],
}, indent=2))
```

多个模型空间合并到同一清单中，文件放在Git忽略的私有部署目录。纯配置构造也可以使用EmbeddingConfig取得model_space，真实Key及调用记录继续通过秘密管理和独立验收处理。

## 建立参考并审查

由DBA准备匹配PG major、locale及扩展版本的空参考库，预先安装public中的pgvector。参考生成器接受上述清单，通过固定DDL创建声明索引，完整定义和状态进入catalog，完整模型空间与维度进入@4合同。

```text
python -m tire_api.postgres_schema_cli --postgres-profile <absolute-reference-profile> --output-file <new-absolute-contract> --empty-reference-confirmed --vector-indexes-file <absolute-index-manifest>
```

省略清单时声明集合为空。@3合同需用当前源码重新构建并批准@4合同和外部固定SHA-256。部署者审查清单及合同，运行端继续使用已批准摘要。

## 拥有者维护

在维护窗口确认实际数据库、业务写入者和备份，完成当前版本的常规迁移。随后以拥有embedding_vectors的维护账户执行，数据库profile沿用[现有连接格式](EXTERNAL-FACT-GOVERNANCE.md)。

```text
python -m tire_api.postgres_vector_indexes --postgres-profile <absolute-owner-profile> --vector-indexes-file <absolute-index-manifest> --schema-contract <absolute-approved-contract> --schema-sha256 <approved-sha256>
```

CLI要求TTY，隐藏读取数据库密码，复用显式目标、TLS／SCRAM、连接隔离及脱敏输出。它在schema advisory锁和固定超时内检查拥有权、声明及完整结构前驱，事务内只创建清单声明且批准合同期待的缺失索引，完整后检查通过才提交。

已有匹配索引幂等返回existing计数。名称相同但定义不同、额外结构漂移、未批准空间、缺少扩展、权限不足或后检查不一致均拒绝。部分创建发生错误时事务回滚，数据库与运行凭据继续依据已批准部署状态配置。

维护成功后，将匹配代码、@4合同、固定摘要和[运行角色](AGENT-HANDOFF-CURRENT.md)部署给API／Worker，以verify启动。运行角色的DDL能力继续由既有权限检查拒绝。

## 运行时与变更

运行Session持有启动时已核对的完整声明及索引目录。每次构建所需配置先检查完整模型空间、维度、实际索引定义和有效状态。未准备好时返回503及 `pgvector_index_maintenance_required`，新的外部请求与预算预留在此之后才发生。

模型、维度或适用端点变更时，更新清单、从空参考库重建批准合同，再执行拥有者维护和verify部署。既有历史空间保留与检索范围仍按内容缓存及当前正式投影核对。当前过滤检索继续使用实际pgvector cosine精确扫描及原有RRF。

回退沿用匹配代码、schema、声明与合同的部署组合，依据维护备份和实际恢复验收执行。CLI结果证明相应结构操作，真实模型质量、生产容量和SLO继续由对应验收确认。
