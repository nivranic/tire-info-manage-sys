# R79 合同审查补充

原冻结计划保留。以下为独立审查发现后的明确化，不提升交付范围：

- 游标的owner绑定使用逐Key HMAC commitment，外部不能从可解码payload得到内部user ID；仍每页重验实际owner与Key。
- 来源目录ID支持现有SOURCE_ID规范1–80安全字符；其它五个可空字符串最多500可打印字符。超限目录整体fail closed，不截断身份。凭据和投递ID规范不扩大。
- 管理员HTTP与本机CLI重置密码均在重置事务中撤销目标全部Key；CLI验证用进程内入口，不创建子进程。
- 已安装Next 16.3.6包带AGENTS与README，但`dist/docs`及所指use-client文档不存在。已读两份可用本地规则；本轮只新增现有模式的客户端组件，不改Next路由/配置/API约定，以实际类型及构建检查补证，不伪称读到缺失指南。
