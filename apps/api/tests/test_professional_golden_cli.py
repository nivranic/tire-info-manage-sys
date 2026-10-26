"""Pure offline actual-file I/O tests. Never import application or open databases."""
import importlib.util
import json
from pathlib import Path

import pytest

from tire_api.professional_golden_corpus import ProfessionalGoldenCorpusError

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('professional_golden_cli_under_test', ROOT / 'scripts/verify_professional_golden.py')
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)
RUN_SPEC = importlib.util.spec_from_file_location('professional_golden_runner_under_test', ROOT / 'scripts/run_professional_golden.py')
RUNNER = importlib.util.module_from_spec(RUN_SPEC)
RUN_SPEC.loader.exec_module(RUNNER)


def test_cli_binds_exact_input_bytes(tmp_path):
    raw = b'{"case_id":"example","value":false}'
    (tmp_path / 'example.json').write_bytes(raw)
    values, bindings = CLI.load_actuals(tmp_path)
    assert values == [{'case_id': 'example', 'value': False}]
    assert bindings[0]['byte_count'] == len(raw)
    assert len(bindings[0]['sha256']) == 64


@pytest.mark.parametrize('raw', [
    b'{"case_id":"example","value":1,"value":2}',
    b'{"case_id":"example","value":NaN}',
    b'{"case_id":"example","value":Infinity}',
    b'{"case_id":"example","value":1e999}',
    b'{"case_id":"different"}', b'[]', b'null', b'\xff',
    b'{"case_id":"../example"}',
])
def test_cli_rejects_ambiguous_or_mismatched_input_without_echo(tmp_path, raw):
    (tmp_path / 'example.json').write_bytes(raw)
    with pytest.raises(ProfessionalGoldenCorpusError) as caught:
        CLI.load_actuals(tmp_path)
    assert str(caught.value).startswith('professional_golden_')
    assert 'value' not in str(caught.value)
    assert 'example' not in str(caught.value)


@pytest.mark.parametrize('extra', ['secrets.txt', 'another', '.env'])
def test_cli_rejects_unexpected_inventory(tmp_path, extra):
    (tmp_path / 'example.json').write_text('{"case_id":"example"}', encoding='utf-8')
    path = tmp_path / extra
    path.mkdir() if extra == 'another' else path.write_bytes(b'never return this content')
    with pytest.raises(ProfessionalGoldenCorpusError):
        CLI.load_actuals(tmp_path)


def test_cli_rejects_large_file_before_json_parse(tmp_path, monkeypatch):
    (tmp_path / 'example.json').write_bytes(b' ' * 512_001)
    with pytest.raises(ProfessionalGoldenCorpusError):
        CLI.load_actuals(tmp_path)


def test_cli_rejects_empty_directory(tmp_path):
    with pytest.raises(ProfessionalGoldenCorpusError):
        CLI.load_actuals(tmp_path)


def test_cli_bounded_read_detects_growth_after_stat(tmp_path, monkeypatch):
    path = tmp_path / 'example.json'
    path.write_text('{"case_id":"example"}', encoding='utf-8')
    original_open = CLI.os.open

    def changing_open(name, flags, *args, **kwargs):
        # A real file changes between the pathname stat and descriptor open.
        path.write_bytes(b' ' * 512_001)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(CLI.os, 'open', changing_open)
    with pytest.raises(ProfessionalGoldenCorpusError):
        CLI.load_actuals(tmp_path)


def test_runner_writes_exact_budget_bytes_including_newlines(tmp_path):
    import hashlib
    directory = tmp_path / 'actuals'
    directory.mkdir()
    base = {'case_id': 'example', 'value': ''}
    overhead = len((json.dumps(base, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    base['value'] = 'x' * (512_000 - overhead)
    path = directory / 'example.json'
    binding = RUNNER.write(path, base)
    assert binding['byte_count'] == len(path.read_bytes()) == 512_000
    assert binding['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        RUNNER.write(path, base)


def test_runner_refuses_one_byte_over_budget_without_creating_file(tmp_path):
    directory = tmp_path / 'actuals'
    directory.mkdir()
    path = directory / 'example.json'
    with pytest.raises(ValueError, match='professional_golden_actual_too_large'):
        RUNNER.write(path, {'case_id': 'example', 'value': 'x' * 512_000})
    assert not path.exists()
