# 设备 AI 指纹规范（E4 / 审查 Top4）

状态：**规范成文，未冻结**。本文为五类指纹给出精确的输入集合、排序/序列化规则与
namespace 字符串。其中只有 `projection_sha256` 在服务端已有实现（其定义必须且已经
与代码一致，本文直接引用行号）；其余四类**待实现方按本规范**实现。所有**新增**
namespace 命名均为提案，**待 Root 显式批准**后方可冻结（dto-b-review-handoff.md
"冻结前的硬性前置"第 7 条）。

**批准进展（2026-10-03）**：三个新增 namespace（`device-ai-selection@1`、
`device-ai-context@1`、`device-ai-local-preview@1`）已获 Root 批准（2026-10-03），
由"提案"转为已批准；本文各处"提案/待 Root 批准"字样按原样保留以供追溯，并在
对应位置追加批准标注。

参考实现锚点：`apps/api/tire_api/device_ai_projection.py`（封存，只读引用）、
`apps/api/tire_api/device_ai_value_encoder.py`（`encode_source_bytes` 的 namespace
参数即 `exact_digest` 语义的复用入口）。

---

## 0. 共同原语（所有指纹共用）

### 0.1 canonical 序列化 = `canonical_exact_json` 语义

`device_ai_projection.py` L157-181，逐条规则：

1. 数字：`NumberLexeme` 原 lexeme 输出（`1.2300`、`-0`、`1e16`、1000 位整数原样；
   **绝不**归一化）；宿主侧 bounded 元数据 `int` 原样十进制输出且必须满足
   `|v| <= 9007199254740991`（L167-169，违者 `device_ai_metadata_number_invalid`）。
2. 字符串：Python `json.dumps(s, ensure_ascii=False)` 语义 —— 转义集合为
   `"`、`\`、`\b \f \n \r \t` 及其它控制字符的 `\uXXXX`；**不转义 `/`；非 ASCII
   原样输出**。该转义集合与 ECMAScript `JSON.stringify` 一致（TS 实现可直接用；
   Rust/Java 需按此集合手写或选等价模式）。
3. 对象：键按 **codepoint 升序**（Python `sorted`，L178）；不允许重复键（parser 已拒）。
4. 数组：保源序。
5. 布尔/null：`true`/`false`/`null`。
6. 紧凑无空白：`{"a":1,"b":[2,3]}`（L173-178 的 join 无空格）。
7. 深度上限 32（L160）；不支持的类型 fail-closed（L179）。

**排序陷阱（三 Host 必须显式处理）**：codepoint 序 ≠ UTF-16 码元序。TS 不能用
默认 `sort()`（须如 `device-criteria.ts` L60-63 的 `compareCodepoints`）；Java 不能用
`String.compareTo`（须按 `codePointAt` 比较）；Rust `&str` 字节序与 codepoint 序一致。

### 0.2 摘要原语 = `exact_digest` 的 namespace 约定

`device_ai_projection.py` L184-186：

```
exact_digest(value, namespace) = sha256( namespace.encode("utf-8") + b"\x00" + canonical_exact_json(value) ).hexdigest()
```

namespace 必须非空且不含 `\x00`。已有测试见证此约定
（`apps/api/tests/test_device_ai_projection.py` 的 literal-vector 测试：
`exact_digest(value, namespace="literal-vector@1") ==
sha256(b"literal-vector@1\x00" + expected)`）。

**例外**：`projection_sha256` 与 `question_sha256` 按既有语义**不带** namespace 前缀
（见下）；其余三类指纹按 0.2 带 namespace。

### 0.3 一致性总则

- 指纹输入中的任何数字，若来自归档业务值，必须以 `NumberLexeme`/token lexeme 形态
  进入 canonical（编码规则见 encoder-spec.md）；只有 bounded 元数据整数可作为裸整数
  进入。**任何指纹都不允许从 token DTO 形状反推数字或哈希 DTO JSON 当作源**
  （草案 b L70-72）。
- 三 Host 计算同一指纹必须逐字节同输入、同 canonical、同摘要；差异即实现缺陷。
  冻结前置：E1 跨 Host 字面向量全绿。

---

## 1. `projection_sha256`（已实现，规范=代码）

| 项 | 定义 |
| --- | --- |
| 状态 | **服务端已实现**（`project_offline_pack`，`device_ai_projection.py` L777-780） |
| 输入集合 | 投影结果对象 `result`（L773-776：schema/data_state/source_refresh_performed/privacy_class/projection_mode/archive{package_id,package_schema,sha256}/observations[]，含每个 observation 的 selector/selection_reason/source/material 全量 canonical 内容） |
| 序列化 | `canonical = canonical_exact_json(result)`（0.1 全部规则） |
| 摘要 | `sha256(canonical).hexdigest()`，**无 namespace 前缀**（L780 原式） |
| 容量 | `len(canonical) <= max_projection_bytes`（默认 44000，L778、L25） |

硬性约束：`token_dto_bytes`（L779）是与 canonical 并行的另一条产物，
**绝不参与哈希**；Host 若本地重算，必须完整复刻 parser+canonical+闭包算法
（dto-b-review-handoff.md D.1），向量对齐前不得宣称等价。

## 2. `selection_sha256`（待实现方按本规范）

绑定目标：**完整 resolved 选择闭包**（requested + decision_dependency），
"新增一个依赖或范围变化均使 fingerprint 变化"（proposal-a.json L105）。

| 项 | 定义 |
| --- | --- |
| 输入集合 | resolved selector 数组，每项为 canonical 对象 `{kind, member_key, document_id, record_index, reference}`（selector 形状与 core `_select` 返回一致，L396-397；reference 为 closed 五类引用之一，L253-272） |
| 排序 | 数组按 `member_key`（64-hex，字典序 = codepoint 序）升序；对象键按 0.1 codepoint 序 |
| 摘要 | `exact_digest(数组, namespace="device-ai-selection@1")`（0.2 式）——namespace 为提案，**已批准（Root，2026-10-03）** |

服务端一致性：服务端从自有源字节重投影得到同一 resolved 集合并重算此值；与 Host
上报值必须相等。闭包集合的**精确相等**判定沿用 core L744-749 的 canonical 集合相等
gate 语义（多余/缺失任一 selector、document、index 或回执即不等）。服务器重算闭包
是范围 gate，独立于 SHA 相等（草案 b L133-138 注释语义）。

## 3. `device_context_fingerprint`（待实现方按本规范）

绑定目标：`DeviceAIContext`（草案 b L313-328）的**内容身份**。由服务端从自有投影
权威计算并返回（proposal-a.json L194："转换各域 authoritative facts、exact token
values、source boundaries、device citation wrappers；计算 device_context_fingerprint"）；
Host 只读取/转发，不需重算，但 Decoder 必须能按本规范独立验证。

输入 canonical 对象（字段逐项，**排除易变实例标识**）：

```
{
  "schema": "device-ai-context@1",
  "package_id": <str>, "package_schema": <"offline-pack@1"|"offline-pack@2">,
  "package_sha256": <64hex>,
  "projection_mode": <六模式之一>,
  "projection_sha256": <64hex>,          // 第 1 节的值，原样嵌入
  "selection_sha256": <64hex>,           // 第 2 节的值，原样嵌入
  "receipt_sources": [ {"selector": <resolved selector canonical>, "selection_reason": <str>,
                        "source": <回执源 canonical，数字以 lexeme 形态>} ... ],  // 按 selector.member_key 排序
  "device_citations": [ <DeviceAICitation canonical> ... ],  // 按 citation 对象 canonical 字节升序排序
  "domain_boundaries": [ <DeviceAIDomainBoundary canonical> ... ],  // 先按 kind 再按 canonical 字节排序
  "numeric_encoding": "device-number-token@1"
}
```

| 项 | 定义 |
| --- | --- |
| 排序 | 上述各数组排序规则如注；对象键 0.1 codepoint 序 |
| 摘要 | `exact_digest(上述对象, namespace="device-ai-context@1")`（提案；已批准（Root，2026-10-03）） |

排除字段及理由：`prepare_id`（服务端随机实例 ID；本指纹绑定**内容**而非实例——
同一内容重新 prepare 得到相同指纹，使 `DeviceAIProviderConsent.
expected_device_context_fingerprint`（草案 b L415）可跨 prepare 稳定核验）。
`binding_verification:"client_provided"`（B01：恒定声明，无区分度）不在指纹输入中，
仍留在 DTO 展示层。

## 4. `local_preview_fingerprint`（待实现方按本规范）

绑定目标（proposal-a.json L141）："SHA256 exact canonical frozen intent + origin +
complete selection closure + projection digest"。此指纹必须可被服务端从 prepare
请求的字段子集**独立重算**，因此输入只取可从 `DeviceAIPrepareRequest`（草案 b
L273-286）与 Host 本地闭包导出的确定性字段。

输入 canonical 对象：

```
{
  "intent": {
    "purpose": "device_history_analysis",
    "policy_version": "device-ai-projection@1",
    "question_sha256": <64hex>,          // 第 5 节的值
    "include_context_ids": [<str>, ...]  // 当前必须为 []，保序进入
  },
  "projection_mode": <六模式之一>,
  "query_context": <canonical 查询上下文，filters_exact_json 以其精确文本字符串进入> | null,
  "origin": <DeviceAIOriginBinding canonical（草案 b L73-85），expected_* 期望字段原样>,
  "selected": [<请求 selector canonical>, ...],     // 保请求顺序（顺序是用户输入的一部分）
  "resolved_closure": [<与 selection_sha256 相同的有序 resolved selector 数组>],
  "state": "ready" | "blocked",
  "projection_sha256": <64hex> | null    // blocked 时为 null；ready 时为第 1 节的值
}
```

| 项 | 定义 |
| --- | --- |
| 排序 | `selected` 保请求序；`resolved_closure` 按 member_key 排序（与第 2 节同数组）；对象键 0.1 codepoint 序 |
| 摘要 | `exact_digest(上述对象, namespace="device-ai-local-preview@1")`（提案；已批准（Root，2026-10-03）） |

排除字段及理由：`id`/`created_at`/`expires_at`（随机与时钟，不可重算）、`notices`
（展示性文本）、`field_preview`（大体积展示数据，其内容已由 `projection_sha256` 绑定）、
`resolved[].required_by_member_keys`（派生调试信息）。`state` 与可空
`projection_sha256` **保留在输入中**：blocked 与 ready 是不同的授权对象，不得同指纹。

`query_context` 中 `filters_exact_json` 进入指纹的是**精确文本本身**（序列化规则见
filters-exact-json-spec.md；文本已 canonical/dedup/sort，故同语义筛选唯一确定文本）。

## 5. `question_sha256`（待实现方按本规范）

绑定目标：问题文本（prepare 不携带明文，只携带此摘要；proposal-a.json L145
"SHA256 exact UTF8 question"）。

| 项 | 定义 |
| --- | --- |
| 输入 | trim-once 后的问题文本（2..2000 Unicode codepoints，草案 b L32；trim/计数的精确算法属 decoder 规范 E5，须先裁定 UTF-16 vs codepoint 计数） |
| 序列化 | 无 canonical JSON 包装：直接对文本的 UTF-8 字节摘要 |
| 摘要 | `sha256(question.encode("utf-8")).hexdigest()`，**无 namespace 前缀** |

这是五类中最简单的定义；正因为简单，各 Host 不得自行加前缀、加 JSON 引号包装或
先 NFKC 归一化——文本以 Host 收到的 trim-once 后原样字节进入。

## 6. 汇总表

| 指纹 | 输入集合 | 排序核心 | namespace | 状态 |
| --- | --- | --- | --- | --- |
| `projection_sha256` | 投影结果全量 canonical | 对象键 codepoint；observations 按 member_key（core L755 `sorted(resolved)`） | 无（裸 sha256(canonical)） | **已实现**（core L777-780） |
| `selection_sha256` | resolved 闭包 selector 数组 | member_key 升序 | `"device-ai-selection@1"`（提案；已批准（Root，2026-10-03）） | 待实现方按本规范 |
| `device_context_fingerprint` | DeviceAIContext 内容身份（排 prepare_id） | 各数组如第 3 节 | `"device-ai-context@1"`（提案；已批准（Root，2026-10-03）） | 待实现方按本规范 |
| `local_preview_fingerprint` | frozen intent + origin + closure + projection digest（第 4 节对象） | selected 保序；closure 按 member_key | `"device-ai-local-preview@1"`（提案；已批准（Root，2026-10-03）） | 待实现方按本规范 |
| `question_sha256` | trim-once 问题 UTF-8 字节 | 无 | 无（裸 sha256） | 待实现方按本规范 |

## 7. 三 Host 一致性要求与验证义务

1. 任一 Host 实现任一指纹，必须同时提交与 Python 参考语义一致的向量测试
   （projection_sha256 可直接对拍 core；其余四类在服务端实现落地后补对拍）。
2. 向量必须覆盖：依赖集变化 → selection/closure 类指纹变化；`1.2300` vs `1.23`
   lexeme 差异 → 含数值的 canonical 输入指纹变化；非 BMP 键排序；blocked vs ready；
   空/最大 `include_context_ids`。
3. 所有新 namespace（`device-ai-selection@1`、`device-ai-context@1`、
   `device-ai-local-preview@1`）在 Root 批准前均为提案；实现可以先行，但冻结声明
   必须等待批准（dto-b-review-handoff.md"冻结前的硬性前置"第 4/7 条）。
   **该批准已于 2026-10-03 由 Root 完成：三个 namespace 全部按建议批准
   （已批准（Root，2026-10-03）），冻结前置第 7 条就此满足。**
