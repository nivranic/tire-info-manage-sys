# OpenAI Responses 冒烟引用校验修复计划

## 目标与依据

首个真实AI接入沿用用户选定的OpenAI Responses。2026-11-12合成探针确认 `scripts/ai_real_provider_smoke.py` 会接受未知fact／evidence引用、自由文本事实及缺失usage，回执为本机 `.artifacts/responses-smoke-20261112/pre-fix-probe.json`。

修复该脚本的成功判定，复用应用现有 `grounded_answer` 和 `safe_usage`。合成输入补齐现行facts／evidence／conflicts／source_state字段，已知事实恢复为服务端提供的文本。两次调用均须产生至少一条已绑定事实和合法用量，流式分片须与最终正文相同。固定错误码及统计计数用于失败输出。

工作使用既有main。调试遵循已应用的debug-pro流程，设计与实施沿用brainstorming及writing-plans的需求核对、最小实现和红绿验证流程。

## 实施顺序

1. 新建 `apps/api/tests/test_ai_provider_smoke.py`，在 `scripts/run_api_worker_regression.py` 登记。用合成回执覆盖引用、事实恢复、用量、上游失败、默认Responses两次调用、首错停止及流式正文不一致。
2. 运行受管红批并保留原始结果。
3. 修改 `scripts/ai_real_provider_smoke.py`，补齐合成信封，复用现行grounding／usage校验，保持环境配置入口、generate→stream顺序及既有成功返回形状。
4. 运行新模块及既有AI、流式回归。核对源码绑定、资源关闭、零真实Provider调用，并更新续作记录和交接卡。

## 验证入口

```powershell
apps/api/.venv/Scripts/python.exe scripts/run_api_worker_regression.py --phase run --output-root .artifacts/rsp-r1 --targets apps/api/tests/test_ai_provider_smoke.py
```

每批使用新槽名。真实模型语义与API→Provider→Web全链验收继续按各自凭据、用途许可及预算条件执行。该脚本验证Provider协议和现行grounding，应用API的同意、持久化、幂等和账本沿用独立验收。

## 执行结果

原始独立探针已证明假通过。前两份受管回执在collection阶段终止，实际执行测试数0，定位为测试入口错误依赖scripts包命名空间。按受管runner既有scripts搜索目录改为直接模块导入后，新增26项及相关五模块122／122通过。

最终回执为 `.artifacts/rsp-r3/result.json`，SHA256 `099eac3593628081ca4f72db79b214a461237d64837f40634192ecf6f2d352b1`。775个输入稳定、资源关闭、零非自检拒绝、零真实Provider调用。Python优化模式独立验证合法回执通过、未知引用／缺失usage／不一致总量拒绝。禁用状态CLI返回exit2，应用数据库参与0。
