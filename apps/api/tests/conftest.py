"""测试套件密闭性：清空宿主环境里的 TI_* 配置。

宿主可能配置了真实供应商变量（如 TI_AI_PROVIDER/TI_ANTHROPIC_*）；
不清空会让测试走到真实 Provider 路径而非合成 fixture 路径
（第56轮全量回归实测：ai_grounding_validation_failed 一族失败的根因）。
各测试需要的环境变量由自身的 monkeypatch.setenv 显式设置。
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _hermetic_ti_env(monkeypatch):
    for name in [key for key in os.environ if key.startswith('TI_')]:
        monkeypatch.delenv(name, raising=False)
