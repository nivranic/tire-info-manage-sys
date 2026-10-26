# R77 合同补充

原合同 `2026-10-18-candidate-ai-assistance.md` SHA `69fb6134c85ab659f9f73322f32625c425c01e0b582da5ff7723e066311ff659` 保持冻结；本卡仅记录实现前的 wire 细化，不替代验收报告。

- prepare：`schema=candidate-ai-preparation@1`，`purpose=candidate_spec_assistance@1`。
- 专用 run：`schema=candidate-ai-recommendation@1`，顶层通用账本字段外加 `purpose,current:false,preparation,current_status`。preparation 是冻结预览；`current_status={state:'unchanged'|'stale',blockers:string[]}` 表示重新核对时是否变化，unchanged 也不代表安装/性能结论。
- authorization：`schema=candidate-ai-authorization@1`，返回追加的完整许可声明及 revision 元数据，不自动修改旧准备。来源许可为管理员有依据的声明，系统没有自动认证法律权利。
- reason.reference 包含 variant、relation ID/revision ID/revision、selection 五字段以及 field/status/value。肯定理由只来自有效审核或 match。
- 原始模型 wire：`{decision:'choose'|'abstain',selections:[{variant_id,reason_ids:string[]}],uncertainty_codes:string[]}`。服务器从完整输入候选计算 `not_selected_variant_ids`；不接受模型自报删改资格或不适配。
- C 在本地以既有 PackBuilder 校验身份和字段合同，向 Provider 发送单独白名单；本地 gate evidence 不能泄漏到 Provider body。无 actor 过滤的数据库结构判别继续是强制条件。
- 逐源 fields 为叶级 JSON Pointer 集合；车型投影包括全部实际外发的 check_values，含不在 requirements 对象内的 region，避免派生检查遗漏来源依赖。
- provider 预览补 `endpoint_host`；grant 服务端核当前配置并绑定实际 provider/endpoint/allowed_host 的 recipient 指纹，authorization 响应补 `recipient_fingerprint`。同一接口类型换接收域名，旧来源许可不能用于新准备。revoke 不要求当前 Provider 配置可用。
- require_admin 后允许另一管理员从原准备的精确 dependency 撤销许可；撤销不依赖原准备 owner、TTL、原件当前可读。许可账本记录实际执行管理员，不暴露原准备的私人视图；grant 仍需本人当前准备。

- 撤销请求补为精确六键：`dependency_id,provider,expected_revision,action:'revoke',acknowledged,revocation_note`。grant 仍使用原十一键请求。撤销继承旧 head 许可依据与 recipient；没有旧 head 拒绝，不再要求操作者为撤权重新填写权利人或伪造证明摘要。两形状互斥，旧 full-grant 形状不能夹 action=revoke。
- 三类 SQLite 账本增加 BEFORE INSERT 唯一键冲突检查，阻断 `INSERT OR REPLACE` 绕过仅 UPDATE/DELETE 的保护。PostgreSQL 运行时仍须单独验收。

本补充由后端与前端在实现前对齐，Root 接收。独立反例仍覆盖原合同全部不变量。
