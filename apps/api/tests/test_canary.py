"""Offline CLI contract tests; every source fetch is mocked, with no Parser runs."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def canary(monkeypatch):
    path = Path(__file__).resolve().parents[3] / 'scripts/canary.py'
    spec = importlib.util.spec_from_file_location('offline_canary', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    specs = {source_id: SimpleNamespace(model_urls={model: 'https://fixture.example/product'},
                                      origin='https://fixture.example')
             for source_id, model in [('synthetic-new-brand-eu', 'Synthetic EU Model'),
                                     ('synthetic-other-brand-us', 'Synthetic US Model'),
                                     ('synthetic-disabled', 'Synthetic Disabled Model')]}
    sources = [{'id': source_id, 'status': 'disabled' if source_id == 'synthetic-disabled' else 'ready'}
               for source_id in specs]
    sources += [{'id': 'synthetic-recall', 'status': 'ready'},
                {'id': 'synthetic-vehicle', 'status': 'ready'},
                {'id': 'synthetic-pending', 'status': 'configuration_required'}]
    calls = []

    async def fetch(source_id, query, cached=None):
        calls.append((source_id, dict(query), cached))
        if source_id not in specs:
            known = any(row['id'] == source_id for row in sources)
            return {'status': 'unavailable', 'reason': 'unsupported_query_type' if known else 'source_not_found'}
        if next(row['status'] for row in sources if row['id'] == source_id) != 'ready':
            return {'status': 'unavailable', 'reason': 'disabled'}
        return {'status': 'ok', 'body': 'synthetic official source body', 'variants': [],
                'url': 'https://fixture.example/product', 'parser_version': 'synthetic@1'}

    monkeypatch.setattr(module.registry, 'SPECS', specs)
    monkeypatch.setattr(module.registry, 'sources', lambda: sources)
    monkeypatch.setattr(module.registry, 'fetch', fetch)
    return module, sources, specs, calls


def invoke(canary, monkeypatch, capsys, *arguments):
    module = canary[0]
    monkeypatch.setattr(sys, 'argv', ['canary.py', *arguments])
    status = asyncio.run(module.run())
    return status, json.loads(capsys.readouterr().out)


def test_all_sources_selects_only_ready_registered_tire_adapters(canary, monkeypatch, capsys):
    status, reports = invoke(canary, monkeypatch, capsys, '--all-sources', '--size', '')
    assert [call[0] for call in canary[3]] == ['synthetic-new-brand-eu', 'synthetic-other-brand-us']
    assert status == 0
    assert [report['source_id'] for report in reports] == ['synthetic-new-brand-eu', 'synthetic-other-brand-us']
    assert [report['query'] for report in reports] == [
        {'model': 'Synthetic EU Model'}, {'model': 'Synthetic US Model'}]
    assert all(report['execution_scope'] == 'installed_tire_source_code_without_database_deployment'
               for report in reports)


@pytest.mark.parametrize('source_id,reason', [
    ('nonexistent-source', 'source_not_found'),
    ('synthetic-recall', 'unsupported_query_type'),
    ('synthetic-vehicle', 'unsupported_query_type'),
    ('synthetic-pending', 'configuration_required'),
])
def test_explicit_unsupported_source_is_explained_without_fetch(canary, monkeypatch, capsys, source_id, reason):
    status, report = invoke(canary, monkeypatch, capsys, '--source', source_id, '--revalidate')
    assert status == 1 and not canary[3]
    assert report['source_id'] == source_id and report['status'] == 'unavailable'
    assert report['reason'] == reason and report['variant_count'] == 0
    assert report['parser_receipt'] is None and report['raw_hash'] is None
    assert 'model' not in report['query'] and 'revalidation' not in report


def test_explicit_tire_retains_model_size_and_disabled_failure(canary, monkeypatch, capsys):
    status, report = invoke(canary, monkeypatch, capsys, '--source', 'synthetic-disabled',
                            '--model', 'Explicit Model', '--size', '225/45R18')
    assert status == 1 and report['reason'] == 'disabled'
    assert canary[3] == [('synthetic-disabled', {'model': 'Explicit Model', 'size': '225/45R18'}, None)]


def test_explicit_tire_revalidation_keeps_unconditional_scope(canary, monkeypatch, capsys):
    module = canary[0]
    sleeps = []

    async def no_wait(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(module.asyncio, 'sleep', no_wait)
    monkeypatch.setattr(module.registry, '_states', {'https://fixture.example': {'interval': 2.0}})
    status, report = invoke(canary, monkeypatch, capsys, '--source', 'synthetic-new-brand-eu', '--revalidate')
    assert status == 0 and len(canary[3]) == 2 and sleeps == [2.1]
    assert canary[3][1][2]['body'] == 'synthetic official source body'
    assert report['revalidation'] == {'status': 'ok', 'reason': None,
                                      'strategy': 'unconditional_without_deployment_pin'}
    assert report['conditional_validation_available'] is False


@pytest.mark.parametrize('second_status', ['unavailable', 'not_modified'])
@pytest.mark.parametrize('all_sources', [False, True])
def test_failed_revalidation_cannot_report_success(canary, monkeypatch, capsys, second_status, all_sources):
    module = canary[0]
    initial_fetch = module.registry.fetch

    async def no_wait(_seconds):
        pass

    async def fetch(source_id, query, cached=None):
        result = await initial_fetch(source_id, query, cached)
        if cached and source_id == 'synthetic-new-brand-eu':
            return {'status': second_status, 'reason': 'upstream_network_error' if second_status == 'unavailable' else None}
        return result

    monkeypatch.setattr(module.asyncio, 'sleep', no_wait)
    monkeypatch.setattr(module.registry, '_states', {'https://fixture.example': {'interval': 2.0}})
    monkeypatch.setattr(module.registry, 'fetch', fetch)
    arguments = ['--all-sources'] if all_sources else ['--source', 'synthetic-new-brand-eu']
    status, result = invoke(canary, monkeypatch, capsys, *arguments, '--revalidate')
    report = result[0] if all_sources else result
    assert len(canary[3]) == (4 if all_sources else 2)
    assert report['status'] == 'ok' and report['revalidation']['status'] == second_status
    if second_status == 'unavailable':
        assert report['revalidation']['reason'] == 'upstream_network_error'
    if all_sources:
        assert result[1]['status'] == result[1]['revalidation']['status'] == 'ok'
    assert status == 1


def test_no_ready_tire_sources_is_not_a_success(canary, monkeypatch, capsys):
    for source in canary[1]:
        if source['id'] in canary[2]:
            source['status'] = 'disabled'
    monkeypatch.setattr(sys, 'argv', ['canary.py', '--all-sources'])
    status = asyncio.run(canary[0].run())
    output = capsys.readouterr()
    assert status == 1 and json.loads(output.out) == [] and not canary[3]
    assert '未执行来源检查' in output.err


def test_help_states_tire_only_non_deployed_scope(canary, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['canary.py', '--help'])
    with pytest.raises(SystemExit) as result:
        asyncio.run(canary[0].run())
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert 'ready' in help_text and 'SourceSpec' in help_text
    assert '召回或车型' in help_text and '无数据库部署绑定' in help_text
    assert not canary[3]
