"""Official recorded body plus explicit synthetic failures; no test calls to NHTSA."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from tire_api.adapters import nhtsa
from tire_api.adapters.transport import FetchResult, SourceAccessError
from tire_api.captures import CaptureWriteError, validated_observation
from tire_api import parser_bundles as bundles, parser_runtime as runtime

BODY = (Path(__file__).parent / 'fixtures/recalls/campaign-23t001000.json').read_text(encoding='utf-8')
QUERY = {'campaign_number': '23T001000'}


def test_official_campaign_date_and_scope_are_preserved():
    row = nhtsa.parse_json(BODY, QUERY)[0]
    assert row['report_received_date'] == '2023-03-02'
    assert row['report_received_date_raw'] == '02/03/2023'
    assert row['model_year_raw'] == '9999' and row['applicability'] == 'not_assessed'
    assert row['make'] == 'GENERAL TIRE' and row['model'] == 'ALTIMAX RT43'
    assert '175/65R14 82T' in row['summary'] and row['potential_units'] == 3
    assert not {'safe', 'affected', 'variant_id', 'production_start'} & row.keys()


@pytest.mark.parametrize('bad', ['23V001000', '23T001000&secret=x', '23T001000#x', '２３T001000', '', None])
def test_campaign_identity_input_is_closed(bad):
    with pytest.raises(ValueError):
        nhtsa.query_url({'campaign_number': bad})


@pytest.mark.parametrize('mutation', ['count_bool', 'count_wrong', 'campaign', 'missing_summary', 'null_remedy',
                                     'units_bool', 'date', 'error_message', 'paging', 'duplicate'])
def test_malformed_or_incomplete_campaign_is_not_empty_success(mutation):
    value = json.loads(BODY)
    row = value['results'][0]
    if mutation == 'count_bool': value['Count'] = True
    elif mutation == 'count_wrong': value['Count'] = 2
    elif mutation == 'campaign': row['NHTSACampaignNumber'] = '26T008000'
    elif mutation == 'missing_summary': del row['Summary']
    elif mutation == 'null_remedy': row['Remedy'] = None
    elif mutation == 'units_bool': row['PotentialNumberofUnitsAffected'] = True
    elif mutation == 'date': row['ReportReceivedDate'] = '30/02/2023'
    elif mutation == 'error_message': value['Message'] = 'Service failed'
    elif mutation == 'paging': value['next'] = 'another page'
    elif mutation == 'duplicate': value['results'].append(deepcopy(row)); value['Count'] = 2
    with pytest.raises(ValueError):
        nhtsa.parse_json(json.dumps(value), QUERY)


def test_empty_and_duplicate_json_are_distinguished():
    assert nhtsa.parse_json('{"Count":0,"Message":"Results returned successfully","results":[]}', QUERY) == []
    with pytest.raises(ValueError):
        nhtsa.parse_json('{"Count":1,"Count":0,"Message":"Results returned successfully","results":[]}', QUERY)


def test_official_search_scopes_keep_raw_products_and_document_provenance():
    path = Path(__file__).parent / 'fixtures/recalls/search-xcellent.json'
    result = nhtsa.parse_json(path.read_text(encoding='utf-8'), {'search': 'XCELLENT ROADBREAKER', 'offset': '0'})
    assert result['pagination'] == {'offset': 0, 'max': 10, 'count': 1, 'total': 1, 'has_next': False, 'has_previous': False}
    campaign = result['products'][0]['campaigns'][0]
    assert campaign['campaign_number'] == '26T008000' and campaign['report_received_at'].startswith('2026-02-11')
    assert '4324' in campaign['summary']
    assert campaign['associated_products'][0]['productionDates'] == '10/21/2024 - 10/27/2024'
    assert len(campaign['documents']) == 5
    assert result['products'][0]['applicability'] == 'not_assessed'


@pytest.mark.parametrize('mutation', ['truncated_page', 'missing_recall', 'foreign_next', 'wrong_query', 'fake_zero', 'unsafe_document', 'invalid_product', 'missing_scope', 'missing_document'])
def test_search_partial_or_unbound_results_fail_closed(mutation):
    value = json.loads((Path(__file__).parent / 'fixtures/recalls/search-xcellent.json').read_text(encoding='utf-8'))
    row, page = value['results'][0], value['meta']['pagination']
    if mutation == 'truncated_page': page['count'] = 2
    elif mutation == 'missing_recall': row['safetyIssues']['recalls'] = []
    elif mutation == 'foreign_next': page['nextUrl'] = 'https://evil.example/page'
    elif mutation == 'wrong_query': page['currentUrl'] = page['currentUrl'].replace('XCELLENT', 'SOMETHING')
    elif mutation == 'fake_zero': page['total'] = 0
    elif mutation == 'unsafe_document': row['safetyIssues']['recalls'][0]['associatedDocuments'][0]['url'] = 'javascript:alert(1)'
    elif mutation == 'invalid_product': row['id'] = True
    elif mutation == 'missing_scope': row['safetyIssues']['recalls'][0]['associatedProducts'] = []
    elif mutation == 'missing_document': row['safetyIssues']['recalls'][0]['associatedDocuments'] = []
    with pytest.raises(ValueError):
        nhtsa.parse_json(json.dumps(value), {'search': 'XCELLENT ROADBREAKER', 'offset': '0'})


def test_official_uppercase_pdf_paths_are_preserved():
    value = json.loads((Path(__file__).parent / 'fixtures/recalls/search-xcellent.json').read_text(encoding='utf-8'))
    document = value['results'][0]['safetyIssues']['recalls'][0]['associatedDocuments'][0]
    document['url'] = document['url'][:-4] + '.PDF'
    result = nhtsa.parse_json(json.dumps(value), {'search': 'XCELLENT ROADBREAKER', 'offset': '0'})
    assert result['products'][0]['campaigns'][0]['documents'][0]['url'] == document['url']


@pytest.mark.parametrize('url', [
    nhtsa.query_url(QUERY) + '&token=secret', nhtsa.query_url(QUERY) + '&campaignNumber=26T008000',
    nhtsa.query_url(QUERY) + '#fragment', 'https://api.nhtsa.gov/recalls/campaignNumber?campaignNumber=%32%33T001000',
    'https://evil.example/recalls/campaignNumber?campaignNumber=23T001000',
    'https://api.nhtsa.gov:443/recalls/campaignNumber?campaignNumber=23T001000',
    'https://api.nhtsa.gov/recalls/campaignNumber?campaignNumber=12V176000'])
def test_raw_capture_query_exception_is_only_the_fixed_recall_contract(url):
    assert not nhtsa.permitted_url(url)
    assert validated_observation({'url': url, 'body': BODY, 'content_type': 'application/json',
                                  'parser_version': nhtsa.PARSER_VERSION}) is None


def test_recall_capture_permitted_and_arbitrary_query_still_rejected():
    values = {'url': nhtsa.query_url(QUERY), 'body': BODY, 'content_type': 'application/json',
              'parser_version': nhtsa.PARSER_VERSION}
    assert validated_observation(values)['raw_body'] == BODY.encode()
    assert validated_observation({**values, 'url': 'https://www.example.org/path?foo=bar'}) is None


@pytest.fixture
def adapter(monkeypatch):
    from tire_api.adapters import registry
    identity = {'bundle_id': 'a' * 64, 'parser_digest': 'b' * 64, 'deployment_revision': 1}
    metadata = {'parser_version': nhtsa.PARSER_VERSION, 'parser_identity': identity}
    descriptor = {'parser_version': nhtsa.PARSER_VERSION, 'parser_digest': 'b' * 64}
    monkeypatch.setattr(registry, 'pin_parser_selection', lambda *args: (descriptor, metadata, {}))
    monkeypatch.setattr(nhtsa, '_state', {'last': -float('inf'), 'failures': 0, 'until': 0, 'busy': False, 'interval': 2})
    monkeypatch.setattr(nhtsa, '_robots', None)
    monkeypatch.setattr(nhtsa, '_robots_last', -float('inf'))
    monkeypatch.delenv('TI_DISABLED_SOURCES', raising=False)
    calls = []
    reply = {'value': FetchResult(200, nhtsa.query_url(QUERY), BODY, 'application/json', 'etag-1', None)}

    class Client:
        def __init__(self, hosts): assert hosts == frozenset({nhtsa.HOST})
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith('/robots.txt'):
                if isinstance(reply.get('robots'), Exception): raise reply['robots']
                if reply.get('robots') is not None: return reply['robots']
                return FetchResult(404, url, '', '', None, None)
            if isinstance(reply['value'], Exception): raise reply['value']
            return reply['value']

    async def child(*_args, **_kwargs):
        calls.append(('parse', {}))
        return {'payload': nhtsa.parse_json(BODY, QUERY), 'receipt': {'reaped': True}}
    monkeypatch.setattr(nhtsa, 'SafeHttpClient', Client)
    monkeypatch.setattr(nhtsa, 'parse_isolated', child)
    return calls, reply, metadata


def test_receipt_precedes_parser_and_failure_stops_parser(adapter):
    calls, _, _ = adapter
    def refuse(_observation):
        calls.append(('receipt', {}))
        raise CaptureWriteError('simulated')
    result = asyncio.run(nhtsa.fetch(QUERY, on_observation=refuse))
    assert result['reason'] == 'evidence_capture_failed'
    assert calls[-1][0] == 'receipt' and not any(call[0] == 'parse' for call in calls)


def test_conditional_request_only_uses_matching_parser_identity(adapter):
    calls, reply, metadata = adapter
    reply['value'] = FetchResult(304, nhtsa.query_url(QUERY), '', '', None, None)
    cached = {'url': nhtsa.query_url(QUERY), 'body': BODY, 'etag': 'etag-1', **metadata}
    result = asyncio.run(nhtsa.fetch(QUERY, cached=cached))
    assert result['status'] == 'not_modified' and calls[-1][1]['headers'] == {'Accept': 'application/json', 'If-None-Match': 'etag-1'}
    nhtsa._state['last'] = -float('inf')
    cached['parser_identity'] = {**metadata['parser_identity'], 'deployment_revision': 2}
    result = asyncio.run(nhtsa.fetch(QUERY, cached=cached))
    assert result['reason'] == 'unexpected_304' and calls[-1][1]['headers'] == {'Accept': 'application/json'}


def test_transport_failure_never_falls_back_or_exposes_message(adapter):
    _, reply, _ = adapter
    reply['value'] = SourceAccessError('upstream_http_403')
    result = asyncio.run(nhtsa.fetch(QUERY, cached={'body': BODY}))
    assert result['status'] == 'unavailable' and result['reason'] == 'upstream_http_403'
    assert 'records' not in result and 'body' not in result


@pytest.mark.parametrize('code,expected', [
    ('parser_timeout', 'parser_timeout'), ('parser_cancelled', 'parser_cancelled'),
    ('parser_schema_changed', 'parser_schema_changed'),
    ('parser_isolation_unavailable', 'parser_isolation_unavailable'),
    ('unclassified-private-detail', 'parser_failed'),
])
def test_parser_failure_reason_matches_retained_observation(adapter, monkeypatch, code, expected):
    calls, _, metadata = adapter
    receipt = {'run_id': 'synthetic-parser-failure', 'reaped': True, 'exit_code': 71}

    async def failed(*_args, **_kwargs):
        calls.append(('parse', {}))
        raise runtime.ParserRunError(code, receipt)

    monkeypatch.setattr(nhtsa, 'parse_isolated', failed)
    result = asyncio.run(nhtsa.fetch(QUERY))
    assert result['status'] == 'unavailable' and result['reason'] == result['parser_error'] == expected
    assert result['parser_receipt'] == receipt and result['parser_identity'] == metadata['parser_identity']
    assert result['rejected_observation']['parser_error'] == expected
    assert result['rejected_observation']['body'] == BODY
    assert validated_observation(result['rejected_observation']) is not None
    assert sum(call[0] == 'parse' for call in calls) == 1
    assert 'records' not in result and 'discovery' not in result


def test_reviewed_api_robots_unavailable_is_distinct_from_resource_denial(adapter):
    calls, reply, _ = adapter
    reply['robots'] = FetchResult(403, nhtsa.ORIGIN + '/robots.txt', '', '', None, None)
    result = asyncio.run(nhtsa.fetch(QUERY))
    assert result['status'] == 'ok' and calls[-2][1]['headers']['Accept'] == 'application/json'


@pytest.mark.parametrize('policy', ['disallow', 'unreachable', 'rate_limited'])
def test_robots_actual_rules_and_unreachable_policy_remain_closed(adapter, policy):
    calls, reply, _ = adapter
    reply['robots'] = (FetchResult(200, nhtsa.ORIGIN + '/robots.txt', 'User-agent: *\nDisallow: /\n', 'text/plain', None, None)
        if policy == 'disallow' else SourceAccessError('upstream_http_503' if policy == 'unreachable' else 'upstream_http_429'))
    result = asyncio.run(nhtsa.fetch(QUERY))
    assert result['status'] == 'unavailable' and len(calls) == 1 and 'records' not in result


def test_real_recall_child_and_legacy_eight_source_bundle_still_execute(tmp_path, monkeypatch):
    source = tmp_path / 'trusted' / 'tire_api'
    for path in Path(runtime.__file__).parent.rglob('*.py'):
        target = source / path.relative_to(Path(runtime.__file__).parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    monkeypatch.setattr(runtime, '_ROOT', source)
    monkeypatch.setattr(bundles, '_ROOT', source)
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'sealed'))
    current_catalog = runtime.source_catalog()
    new = bundles.seal_deployed_bundle()
    descriptor = bundles.bundle_descriptor(new, nhtsa.SOURCE_ID)
    result = asyncio.run(runtime.parse_isolated(nhtsa.SOURCE_ID, BODY, QUERY, descriptor['parser_version'],
        descriptor['parser_digest'], bundle_manifest=new, deployment_revision=1))
    assert result['payload'][0]['report_received_date'] == '2023-03-02'
    assert result['receipt']['reaped'] and result['receipt']['exit_code'] == 0
    # Simulate an installed package sealed before recall was in the catalog.
    from test_parser_bundles import historical_install
    historical_install(source, 8)
    legacy_catalog = {key: value for key, value in current_catalog.items() if key in bundles._LEGACY_SOURCES}
    monkeypatch.setattr(runtime, 'source_catalog', lambda: legacy_catalog)
    old = bundles.seal_deployed_bundle()
    assert set(old['parsers']) == set(bundles._LEGACY_SOURCES)
    assert 'adapters/nhtsa.py' not in old['files'] and 'adapters/pirelli.py' not in old['files']
    monkeypatch.setattr(runtime, 'source_catalog', lambda: current_catalog)
    descriptor = bundles.bundle_descriptor(old, 'hankook-us')
    html = (Path(__file__).parent / 'fixtures/brand_sources/hankook-runflat-pair-excerpt.html').read_text(encoding='utf-8')
    result = asyncio.run(runtime.parse_isolated('hankook-us', html, {'model': 'Ventus S1 evo3', 'size': '205/45R17'},
        descriptor['parser_version'], descriptor['parser_digest'], bundle_manifest=old, deployment_revision=2))
    assert len(result['payload']) == 2 and result['receipt']['reaped']
    bad = deepcopy(old)
    del bad['parsers']['hankook-us']
    bad['bundle_id'] = bundles.digest({key: value for key, value in bad.items() if key != 'bundle_id'})
    with pytest.raises(bundles.BundleError):
        bundles.checked_manifest(bad, protocol=runtime.PROTOCOL, limits=runtime.limits())
