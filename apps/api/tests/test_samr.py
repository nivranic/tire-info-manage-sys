"""Synthetic Chinese recall pages, fixed URLs and pre-parser capture contracts."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tire_api.adapters import samr as source
from tire_api.adapters.robots import RobotsPolicy
from tire_api.captures import CaptureWriteError, validated_observation
from tire_api import parser_runtime

SEARCH = {'operation': 'search', 'keyword': '轮胎', 'page': '1'}
REFERENCE = '/zhxx/jdczh/jdczh/art/2021/art_' + 'a' * 32 + '.html'
NOTICE = {'operation': 'notice', 'reference': REFERENCE}
IDENTITY = {'bundle_id': 'a' * 64, 'parser_digest': 'b' * 64, 'deployment_revision': 1}


def search_body(*, total=1, page=1):
    count = min(15, max(0, total - (page - 1) * 15))
    items = []
    for number in range(count):
        reference = REFERENCE.replace('a' * 32, f'{number + (page - 1) * 15:032x}')
        items.append(f'<li><a href="{reference}" title="合成轮胎公告">合成<em>轮</em><em>胎</em>公告</a>'
            '<a href="/other">召回公告</a><span>2021-07-23</span></li>')
    html = '<div class="page-content"><ul>' + ''.join(items) + '</ul></div>'
    html += f'<div class="pagination" queryData="{{\'rows\':\'15\',\'count\':\'{total} \',\'pageNo\':\'{page}\'}}"></div>'
    return json.dumps({'success': True, 'code': '200', 'data': {'html': html}}, ensure_ascii=False)


def notice_body(reference=REFERENCE):
    metadata = {'SiteName': source.SITE_NAME, 'SiteDomain': 'www.samrdprc.org.cn',
        'SiteID': source.WEB_ID, 'ColId': source.COLUMN_ID, 'ColumnName': '汽车召回',
        'ArticleTitle': '合成轮胎公告', 'PubDate': '2026-06-22 11:48',
        'DeployTime': '2021-07-23 13:53:00', 'ContentSource': '', 'Url': reference, 'server': reference}
    tags = ''.join(f'<meta name="{name}" content="{value}">' for name, value in metadata.items())
    return ('<!DOCTYPE html><html><head>' + tags + '</head><body>'
        '<div class="content_title"><span>合成轮胎公告</span></div>'
        '<div class="gyj_ly"><span>发布时间：2021-07-23</span></div>'
        '<div id="zoom"><p>合成<em>轮胎</em>批次 0121—0221。</p><p>合成处理措施。</p>'
        '<img src="/cms_files/filemanager/1/picture/test.png" alt="合成图片">'
        '<a href="https://other.example/report.pdf">合成外部附件</a>'
        '<script>hidden()</script></div></body></html>')


def test_search_preserves_total_navigation_limit_and_partial_last_page():
    result = source.parse_document(search_body(total=47, page=4), {**SEARCH, 'page': '4'})
    assert result['declared_total'] == 47 and result['source_navigation_pages'] == 4
    assert len(result['notices']) == 2 and result['page'] == 4
    assert result['notices'][0]['title'] == '合成轮胎公告'
    assert result['notices'][0]['applicability'] == 'not_assessed'
    result = source.parse_document(search_body(total=2325), SEARCH)
    assert result['declared_total'] == 2325 and result['source_navigation_pages'] == 60
    assert source.parse_document(search_body(total=0), SEARCH)['notices'] == []


def test_notice_keeps_original_and_page_metadata_dates_and_unfetched_resources():
    result = source.parse_document(notice_body(), NOTICE)['notice']
    assert result['published_date'] == '2021-07-23'
    assert result['deployed_at_raw'] == '2021-07-23 13:53:00'
    assert result['pub_date_raw'] == '2026-06-22 11:48' and result['content_source_raw'] == ''
    assert result['text'] == '合成轮胎批次 0121—0221。\n合成处理措施。\n合成外部附件'
    assert result['assets'][0]['url'] == source.ORIGIN + '/cms_files/filemanager/1/picture/test.png'
    assert result['assets'][1]['url'] is None
    assert all(row['fetch_status'] == 'not_fetched' for row in result['assets'])
    assert result['metadata']['Url'] == REFERENCE and result['applicability'] == 'not_assessed'


@pytest.mark.parametrize('mutation', [
    lambda value: value.replace('www.samrdprc.org.cn', 'other.example'),
    lambda value: value.replace('name="ArticleTitle"', 'name="OtherTitle"'),
    lambda value: value.replace('name="PubDate"', 'name="DeployTime"'),
    lambda value: value.replace('id="zoom"', 'id="other"'),
    lambda value: value.replace('id="zoom"', 'id="zoom" id="other"'),
    lambda value: value.replace('art_' + 'a' * 32, 'art_' + 'b' * 32),
    lambda value: value.replace('发布时间：2021-07-23', '发布时间：2026-06-22'),
    lambda value: value.replace('2026-06-22 11:48', '2026-02-30 11:48'),
    lambda value: value.replace('class="content_title"', 'class="other"'),
    lambda value: value.replace('</body>', '<div id="zoom">other</div></body>'),
    lambda value: value.replace('<div id="zoom">', '<div id="zoom">\x00'),
])
def test_notice_rejects_wrong_page_identity_ambiguous_metadata_and_invalid_body(mutation):
    with pytest.raises(ValueError):
        source.parse_document(mutation(notice_body()), NOTICE)


@pytest.mark.parametrize('mutation', [
    lambda value: value.replace('"success": true', '"success": true, "success": false'),
    lambda value: value.replace('"200"', '200'),
    lambda value: value.replace("'pageNo':'1'", "'pageNo':'2'"),
    lambda value: value.replace("'count':'1 '", "'count':'2 '"),
    lambda value: value.replace("'rows':'15'", "'rows':'10'"),
    lambda value: value.replace('art/' + '2021', 'art/../2021'),
    lambda value: value.replace('2021-07-23', '2021-02-30'),
    lambda value: value.replace('title=\\"合成轮胎公告', 'title=\\"other'),
])
def test_search_rejects_drift_and_wrong_pagination(mutation):
    with pytest.raises(ValueError):
        source.parse_document(mutation(search_body()), SEARCH)


@pytest.mark.parametrize('invalid', ['\x00', '\x1f', '\ud800'])
def test_nested_json_html_rejects_decoded_controls_and_invalid_unicode(invalid):
    value = json.loads(search_body())
    value['data']['html'] = value['data']['html'].replace('合成', '合成' + invalid)
    with pytest.raises(ValueError):
        source.parse_document(json.dumps(value), SEARCH)


@pytest.mark.parametrize('query', [
    {**SEARCH, 'page': 1}, {**SEARCH, 'page': '01'}, {**SEARCH, 'page': '61'},
    {**SEARCH, 'keyword': '轮胎\n'}, {**SEARCH, 'keyword': 'x' * 81}, {**SEARCH, 'extra': '1'},
    {**NOTICE, 'reference': source.ORIGIN + REFERENCE},
    {**NOTICE, 'reference': REFERENCE + '?tracking=1'},
    {**NOTICE, 'reference': REFERENCE.replace('/art/2021/', '/art/../2021/')},
])
def test_query_fields_and_native_references_are_bounded(query):
    with pytest.raises(ValueError):
        source.query_url(query)


def test_observation_mime_and_query_are_bound_to_the_exact_source_resource():
    for query, body, mime in [(SEARCH, search_body(), 'application/json'), (NOTICE, notice_body(), 'text/html')]:
        observation = {'url': source.query_url(query), 'body': body, 'content_type': mime, 'parser_version': source.PARSER_VERSION}
        assert validated_observation(observation, source_id=source.SOURCE_ID, query=query)
        assert validated_observation({**observation, 'url': observation['url'] + '?other=1'}, source_id=source.SOURCE_ID, query=query) is None
        assert validated_observation(observation, source_id=source.SOURCE_ID, query={**query, 'operation': 'other'}) is None
        assert validated_observation({**observation, 'content_type': 'text/plain'}, source_id=source.SOURCE_ID, query=query) is None


def test_isolated_parser_executes_search_and_notice(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    descriptor = parser_runtime.current_parser(source.SOURCE_ID)
    for query, body in [(SEARCH, search_body()), (NOTICE, notice_body())]:
        result = asyncio.run(parser_runtime.parse_isolated(source.SOURCE_ID, body, query,
            descriptor['parser_version'], descriptor['parser_digest']))
        assert result['payload'] == source.parse_document(body, query)
        assert result['receipt']['reaped'] is True and result['receipt']['exit_code'] == 0


def test_old_seventeen_entry_bundle_remains_executable(tmp_path, monkeypatch):
    from test_parser_bundles import execute_bundle, pre_samr_install, trusted_copy
    from tire_api import parser_bundles
    installed = trusted_copy(tmp_path, monkeypatch)
    pre_samr_install(installed)
    catalog = {key: value for key, value in parser_runtime.source_catalog().items() if key in parser_bundles._DUNLOP_SOURCES}
    with monkeypatch.context() as patch:
        patch.setattr(parser_runtime, 'source_catalog', lambda: catalog)
        manifest = parser_bundles.seal_deployed_bundle()
    assert len(manifest['parsers']) == 17
    assert asyncio.run(execute_bundle(manifest))['payload']


@pytest.fixture
def transport(monkeypatch):
    calls, events = [], []
    monkeypatch.setattr(source, '_state', {'last': -float('inf'), 'failures': 0, 'until': 0, 'busy': False, 'interval': 2.0})
    response = SimpleNamespace(status=200, url=source.query_url(SEARCH), body=search_body(),
        content_type='application/json', etag='"synthetic"', last_modified=None)

    class Client:
        def __init__(self, hosts):
            assert hosts == frozenset({'www.samrdprc.org.cn'})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            events.append('closed')

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return response

    async def policy(_client):
        return RobotsPolicy('', 'test')

    async def parse(_source, body, query, *_args, **_kwargs):
        events.append('parsed')
        return {'payload': source.parse_document(body, query), 'receipt': {}}

    from tire_api.adapters import registry
    monkeypatch.setattr(registry, 'pin_parser_selection', lambda *_args: (
        {'parser_version': source.PARSER_VERSION, 'parser_digest': 'b' * 64},
        {'parser_version': source.PARSER_VERSION, 'parser_identity': deepcopy(IDENTITY)}, {}))
    monkeypatch.setattr(source, 'SafeHttpClient', Client)
    monkeypatch.setattr(source, '_policy', policy)
    monkeypatch.setattr(source, 'parse_isolated', parse)
    return calls, events, response


def test_fetch_requests_json_and_records_before_parser_and_releases_client(transport):
    calls, events, _ = transport
    result = asyncio.run(source.fetch(SEARCH, on_observation=lambda _value: events.append('captured')))
    assert result['status'] == 'ok' and events == ['captured', 'parsed', 'closed']
    assert calls[0][1]['headers'] == {'Accept': 'application/json'}
    assert calls[0][1]['max_bytes'] == source.MAX_BYTES
    assert not calls[0][1]['can_follow'](source.ORIGIN + '/index.html')
    assert source._state['busy'] is False


def test_failed_capture_prevents_parse_and_keeps_busy_state_consistent(transport):
    _, events, _ = transport

    def failed(_value):
        raise CaptureWriteError()

    result = asyncio.run(source.fetch(SEARCH, on_observation=failed))
    assert result['reason'] == 'evidence_capture_failed' and events == ['closed']
    assert source._state['busy'] is False


def test_failed_parser_retains_observation_and_receipt(transport, monkeypatch):
    _, events, _ = transport

    async def failed(*_args, **_kwargs):
        raise parser_runtime.ParserRunError('parser_schema_changed', {'reaped': True})

    monkeypatch.setattr(source, 'parse_isolated', failed)
    result = asyncio.run(source.fetch(SEARCH))
    assert result['reason'] == 'parser_schema_changed'
    assert result['rejected_observation']['body'] == search_body()
    assert result['parser_receipt'] == {'reaped': True} and events == ['closed']


def test_conditional_revalidation_requires_matching_parser_identity(transport):
    calls, events, response = transport
    cached = {'url': source.query_url(SEARCH), 'body': search_body(), 'parser_version': source.PARSER_VERSION,
        'parser_identity': deepcopy(IDENTITY), 'etag': '"synthetic"'}
    response.status = 304
    result = asyncio.run(source.fetch(SEARCH, cached))
    assert result['status'] == 'not_modified' and events == ['closed']
    assert calls[0][1]['headers']['If-None-Match'] == '"synthetic"'
    source._state['last'] = -float('inf')
    result = asyncio.run(source.fetch(SEARCH, {**cached, 'parser_identity': {**IDENTITY, 'deployment_revision': 2}}))
    assert result['reason'] == 'unexpected_304'
    assert 'If-None-Match' not in calls[-1][1]['headers']
