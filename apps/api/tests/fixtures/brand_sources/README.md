# 官方响应最小节选

这些文件来自 2026-09-26 的真实公开 HTTPS 响应，用于在无网络的 CI 中回放解析器。来源 URL、UTC 观察时间、完整响应 SHA-256、节选 SHA-256 和裁剪方式记录于 `provenance.json`。它们是少量真实 SKU 回归样本，不是完整 Golden Set；不代表后端集成、业务库入库或长期来源稳定性已验收。

- `toyo-proxes-sport-excerpt.json`：从产品页公开引用的官方规格 JSON 中，保留原表头和产品码 `136130`、`132860` 两个完整记录；仅裁剪其他记录并格式化 JSON，原字段值不变。
- `hankook-runflat-pair-excerpt.html`：逐字保留 `205/45R17 XL` 的产品码 `1022631`、`1022632` 两个完整规格卡，保留原型号标签及容器起始标签，补齐最小闭合结构。两者均为 `88W`、OEM `BMW`，但 `Run Flat` 分别为 `Y`、`N`，重量和胎纹深度也不同。

Hankook 的 `OEM=BMW` 只表示来源列出的适用厂商品牌，不能推导胎侧 `*` 等 OE 认证标识；未出现的字段保持未知。测试不得把这些节选或合成 fixture 写入实际业务库。

2026-09-30 增加 Pirelli 美国 P ZERO (PZ4) 两份尺寸页节选：

- `pirelli-pz4-265-40-r20-excerpt.html`：保留公开尺寸页内嵌的全部三条 SKU（2524000 / 4080500 / 4159300）、实际区域/型号/查询范围及 Product JSON-LD；第三条实际尺寸为 `265/40ZR20`，搜索字段的 R 不覆盖 ZR。
- `pirelli-pz4-265-40-r21-excerpt.html`：保留内嵌的全部八条 SKU，覆盖 `(105Y)`、B/BL/MO-S/MGT1/BH/LTS/KRM，以及规格文本相同但产品码不同的两条 MO-S 记录。

节选从真实 Flight 数据解码，裁剪无关内容后重新序列化为严格 JSON 字面量，保留的原字段值不变。PNCS/ELECT/run-flat 使用逐 SKU 声明。UTQG 原字段 `temperature="AA"` 不符合标准温度枚举；测试保留原串和异常，不擅自互换牵引/温度，也不输出非法标准温度。未访问 robots 禁止的产品码查询或 sheet/details 接口。这些节选仅供本机个人 PoC/解析回归，不代表商业抓取或再分发许可；不是正常业务库、浏览器或真实后端验收。
