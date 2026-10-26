# 专业测试 PDF 来源策略与原件捕获

该通道用于保存有明确依据的专业测试 PDF 原件，并记录实际取得的 HTTP identity body 字节。默认来源目录为空，不自动访问任何专业媒体，也不购买或绕过登录取得内容。

它是来源传输凭证：PDF 内容、引用页与 PDF 的关系、许可真实性和精确 SKU 身份仍需人工核对。传输成功不能代替专业 Golden 或性能推荐验收。

## 配置方式

从[空配置示例](source-material-policies.example.json)复制一份可信的本地 JSON，完成实际 URL 和许可核对后，设置 `TI_SOURCE_MATERIAL_POLICIES_FILE` 指向它。API 在创建时读取一次；修改或撤销策略需重启 API。重启不会自动恢复此前状态未确认的捕获。

文件最多256KiB、16项。以下仅说明字段；`.invalid` 是不可用的示例域名，不能据此声称接入真实来源。

```json
{
  "schema": "source-material-policies@1",
  "policies": [
    {
      "policy_id": "reviewed-test-material",
      "title": "需要填写实际出版物名称",
      "publisher": "需要填写出版者",
      "edition": null,
      "published_at": null,
      "source_reference_url": "https://tests.example.invalid/test-page",
      "download_url": "https://tests.example.invalid/test.pdf",
      "redirect_urls": [],
      "rights": {
        "rights_holder": "需要填写权利人",
        "basis": "需要填写允许保存原件、工作区重开和短引文的实际许可依据",
        "license_url": null,
        "store_original": true,
        "workspace_reopen": true,
        "quote_identifiers": true,
        "provider_use": false,
        "export": false
      }
    }
  ]
}
```

引用页可以不同于实际下载地址。`source_reference_url` 写入原件说明，便于与 TestEvent 的原出处核对；它与 PDF 的关联来自配置声明。系统只把实际请求过的初始/最终 PDF 地址和跳转链列为传输观察。

初始和所有允许跳转地址必须精确列出，最多3个跳转目标；不支持任意 URL、域名通配、请求头、Cookie、账号、密钥、查询参数或片段。许可引用仅作记录，不额外抓取。未知版本和日期用 `null`，不要猜填。

布尔许可字段必须为上述值。完整原件保存与工作区重开需要实际许可依据；默认仅可用元数据、数值或短引文的站点，不能因页面公开可访问就填写全部许可为 true。该通道不授予模型使用或导出许可，也不新增相应出口。

## 在工作台使用

在原件面板选择已经配置的来源，核对出版者、版本/日期、引用页、PDF地址和许可依据。管理员确认后预览并发起一次捕获。成功原件进入现有文档列表，可校验 SHA-256/大小后下载，并从对应文档重开冻结的来源凭证。

每次操作用独立 UUID。网络响应丢失时保留原请求，先查询旧 UUID。状态为未确认时，只能说明还没有可靠终态，不能推断后台仍在下载。相同 UUID 不会再次联网；明确发起另一次捕获才产生新请求和新原件记录。失败也不会自动重抓。

捕获来源只关联本次新建的 document ID。同字节的旧手工上传文档不会被追认为来源捕获。所有历史读取均校验对应对象与冻结记录；损坏会明确报错，不退回当前文档或旧数据库副本。

## 网络与证据边界

捕获使用公网 DNS 和正常 TLS 验证，尊重各实际来源的 robots 策略，限制跳转、并发、逐主机间隔与总时间。不继承环境代理或 Cookie；没有自动重试、断点下载或缓存304复用。只接受完整200、PDF类型和标记、最多8MiB；编码压缩、超限或中断都不会发布部分原件。

保存字节经过 HTTP transfer decoding，但未进行内容解压或文字重编码；不包含 TLS 数据包、HTTP 头帧或 chunk framing。`%PDF-` 只说明文件标记，不能证明页码、可读性、出版者真伪或测试质量。

真实专业材料与许可仍须按来源逐项核对；没有真实样本时，合成PDF/受控响应只能验证工程流程。R71人工桥的未核验等级和R70含测试AI包的事实摘录限制不因捕获成功而解除。

新增020迁移的正常库保全/升级、PG运行与新原生设备验收，均须依据各自现场证据判断。本文不是已完成这些验收的声明。
