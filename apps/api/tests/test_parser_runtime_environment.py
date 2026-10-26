"""Windows child machine identity stays bound without inheriting arbitrary environment."""
import pytest

from tire_api import parser_runtime as runtime


def windows_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.sys, 'platform', 'win32')
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    monkeypatch.delenv('PROCESSOR_ARCHITECTURE', raising=False)
    monkeypatch.delenv('PROCESSOR_ARCHITEW6432', raising=False)


def test_windows_child_retains_only_allowlisted_architecture(monkeypatch, tmp_path):
    windows_environment(monkeypatch, tmp_path)
    monkeypatch.setenv('PROCESSOR_ARCHITECTURE', 'x86')
    monkeypatch.setenv('PROCESSOR_ARCHITEW6432', 'AMD64')
    monkeypatch.setenv('TI_SYNTHETIC_ENV_CANARY', 'must-not-reach-child')
    monkeypatch.setenv('PYTHONPATH', 'synthetic-import-path')
    result = runtime._environment(str(tmp_path / 'child'))
    assert result['PROCESSOR_ARCHITECTURE'] == 'x86'
    assert result['PROCESSOR_ARCHITEW6432'] == 'AMD64'
    assert set(result) == {'PYTHONIOENCODING', 'PYTHONUTF8', 'TEMP', 'TMP', 'SystemRoot', 'WINDIR',
                           'PROCESSOR_ARCHITECTURE', 'PROCESSOR_ARCHITEW6432'}


@pytest.mark.parametrize('value', ['', 'AMD64 extra', 'unknown', '$(synthetic)', '../AMD64'])
def test_windows_child_rejects_unrecognized_machine_metadata(monkeypatch, tmp_path, value):
    windows_environment(monkeypatch, tmp_path)
    monkeypatch.setenv('PROCESSOR_ARCHITECTURE', value)
    with pytest.raises(runtime.ParserRunError) as error:
        runtime._environment(str(tmp_path / 'child'))
    assert error.value.code == 'parser_isolation_unavailable'


def test_windows_child_requires_machine_metadata(monkeypatch, tmp_path):
    windows_environment(monkeypatch, tmp_path)
    with pytest.raises(runtime.ParserRunError) as error:
        runtime._environment(str(tmp_path / 'child'))
    assert error.value.code == 'parser_isolation_unavailable'
