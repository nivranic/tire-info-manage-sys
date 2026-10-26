# 便携设备 AI 合成合同向量

本目录供四端已有合同测试读取，不依赖被 Git 忽略的 `.artifacts/`。127 个输入文件原字节复制自封存样本：projection 向量的 123 个 SHA/size 绑定文件、该组 manifest，以及 E1、closed decoder、Host fingerprint 各一份。schema、expected、数字 lexeme、历史时间和封存 SHA 均未重新生成或改写。

`provenance.json` 为每个复制文件记录本目录相对路径、原 `.artifacts/device-ai50/` 相对路径、字节数和 SHA-256。四端测试 loader 固定 provenance 自身的 SHA，并在回放时核对实际读取的字节；原路径仅是来源记录，测试不回读旧 artifacts。若需改变合同，必须审查所有输入和 expected，并同步更新 provenance 及 loader 的 pin，不能通过更新一端期望绕过差异。

本目录 `.gitattributes` 禁止 Git 文本换行转换，防止 Windows 与其他平台 clone 后的字节 SHA 分歧。

E1 还对 `apps/api/tire_api/device_ai_projection.py` 和 `device_ai_value_encoder.py` 的原字节做来源绑定；仓库根 `.gitattributes` 将这两精确路径固定为 LF。移交时须保留根属性，不能改 sealed source SHA 来适配 CRLF。第64轮以 `core.autocrlf=true` 的只读 Git checkout 过滤及73项E1测试核对，未改这两份源码或向量预期。

原 producer manifest 声明 `synthetic_private_only=true`、正常库读取和外部来源/模型/Parser 调用均为 0，三包的 garage/watch/recent-query 条目均为 0；捕获脚本使用全新私有临时库和注入的合成 Adapter。E1 为人工定义的 JSON 语法/数值样本，decoder 与 fingerprint 使用显式假 ID。`private` / `restricted` 是测试策略输入，不表示正常用户资料。没有复制数据库、cookie、密钥、Keystore 或真实验收输出；生成脚本未在本次迁移中执行。

入口：Node 使用 `npm run test --workspace @tire/api-client`；Python 使用 `apps/api/tests/test_device_ai_fixture_corpus.py`、`test_e1_vectors.py`、`test_device_ai_decoder_fixtures.py`、`test_device_ai_projection.py` 与 `test_device_ai_archive.py`；Rust/Java 使用既有 E1、Host 和 decoder 测试。Node 需支持现有 `registerHooks` / `--experimental-transform-types`，其余使用项目已有测试依赖。

本次仅迁移输入并增加完整性门，没有新增 8MiB、多成员闭包、物理设备、真实模型或端到端验收覆盖。原 manifest 中的历史范围及限制继续有效。
