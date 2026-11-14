"""Official Chinese recall search and article evidence with source-native identity."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
import json
import os
import re
import time
from urllib.parse import urlencode, urljoin

import aiohttp
from yarl import URL

from .robots import RobotsPolicy
from .transport import SafeHttpClient, SourceAccessError, USER_AGENT
from ..captures import CaptureWriteError, parser_failure_reason
from ..parser_runtime import ParserRunError, parse_isolated

SOURCE_ID = 'samr-cn-recalls'
PARSER_VERSION = 'samr-cn-recall-pages@1.0.0'
ORIGIN = 'https://www.samrdprc.org.cn'
INDEX_URL = ORIGIN + '/zhxx/jdczh/jdczh/index.html'
API_PATH = '/api-gateway/jpaas-publish-server/front/page/build/unit'
WEB_ID = 'VCswhVy4jx8aJOSwL9vnk'
COLUMN_ID = 'NsQ28ZyGzCeIEovTNfLkj'
SITE_NAME = '国家市场监督管理总局缺陷产品召回技术中心'
PAGE_SIZE = 15
NAVIGATION_PAGE_LIMIT = 60
MAX_BYTES = 2 * 1024 * 1024
ACCESS_BASIS = {'kind': 'official_public_recall_pages', 'homepage': INDEX_URL,
    'redistribution_license': 'unverified', 'ai_provider_use': 'requires_separate_authorization'}
ATTRIBUTION = SITE_NAME + ' · ' + INDEX_URL
supports_parser_deployments = True
_REFERENCE = re.compile(r'/zhxx/jdczh/jdczh/art/(20[0-9]{2})/art_([a-f0-9]{32})\.html(?:\?type=nFZcuWzfh2c41ylKrWj7k)?', re.ASCII)
_VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'})
_BLOCK = frozenset({'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'br', 'hr'})
_HIDDEN = frozenset({'script', 'style', 'template', 'noscript'})
_state = {'last': -float('inf'), 'failures': 0, 'until': 0, 'busy': False, 'interval': 2.0}
_robots = None
_robots_last = -float('inf')


def source_metadata():
    disabled = SOURCE_ID in {item.strip() for item in os.getenv('TI_DISABLED_SOURCES', '').split(',')}
    return {'id': SOURCE_ID, 'name': '市场监管召回 · 中国', 'region': 'CN',
        'source_class': 'regulatory', 'target_kind': 'recall', 'status': 'disabled' if disabled else 'ready',
        'homepage': INDEX_URL, 'supported_models': [], 'parser_version': PARSER_VERSION,
        'access_policy': 'reviewed_official_public_pages', 'access_basis': dict(ACCESS_BASIS),
        'description': '查询官方汽车召回栏目及公告，保留文章身份、批次原文与独立日期字段，具体适用性待核对。'}


def query_url(query):
    if not isinstance(query, dict):
        raise ValueError('unsupported_samr_query')
    if set(query) == {'operation', 'reference'} and query.get('operation') == 'notice':
        reference = query['reference']
        if type(reference) is not str or _REFERENCE.fullmatch(reference) is None:
            raise ValueError('unsupported_samr_query')
        return ORIGIN + reference
    if (set(query) != {'operation', 'keyword', 'page'} or query.get('operation') != 'search'
            or type(query['keyword']) is not str or len(query['keyword']) > 80
            or query['keyword'] != query['keyword'].strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in query['keyword'])
            or type(query['page']) is not str or re.fullmatch(r'[1-9][0-9]?', query['page'], re.ASCII) is None
            or int(query['page']) > NAVIGATION_PAGE_LIMIT):
        raise ValueError('unsupported_samr_query')
    query['keyword'].encode('utf-8', errors='strict')
    params = {'webId': WEB_ID, 'pageId': COLUMN_ID, 'parseType': 'bulidstatic', 'pageType': 'column',
        'tagId': '分页列表', 'tplSetId': 'EUiBCTIffX3miw82HR5TP', 'unitUrl': API_PATH,
        'paramJson': json.dumps({'pageNo': int(query['page']), 'loadEnabled': True,
            'search': json.dumps({'infoContent': query['keyword'], 'deployTime': '', 'orderWhere': ''},
                ensure_ascii=False, separators=(',', ':')), 'pageSize': str(PAGE_SIZE)},
            ensure_ascii=False, separators=(',', ':'))}
    # Match the URL normalization used by the actual aiohttp connector.
    return str(URL(ORIGIN + API_PATH + '?' + urlencode(params)))


def permitted_url(url, query):
    try:
        return type(url) is str and url == query_url(query)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return False


def _error():
    return ValueError('samr_schema_changed')


def _json(value):
    def pairs(items):
        result = dict(items)
        if len(result) != len(items):
            raise _error()
        return result

    def invalid(_value):
        raise _error()

    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid)


@dataclass
class _Node:
    tag: str
    attrs: dict
    children: list = field(default_factory=list)

    def find(self, tag=None, *, class_name=None, element_id=None):
        found = []
        for child in self.children:
            if isinstance(child, _Node):
                if ((tag is None or child.tag == tag)
                        and (class_name is None or class_name in (child.attrs.get('class') or '').split())
                        and (element_id is None or child.attrs.get('id') == element_id)):
                    found.append(child)
                found.extend(child.find(tag, class_name=class_name, element_id=element_id))
        return found


class _Markup(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        body.encode('utf-8', errors='strict')
        if any(ord(char) < 32 and char not in '\t\r\n' for char in body):
            raise _error()
        self.root = _Node('root', {})
        self.stack = [self.root]
        self.nodes = 0
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            raise _error()
        node = _Node(tag, attributes)
        self.stack[-1].children.append(node)
        self.nodes += 1
        if self.nodes > 50000 or len(self.stack) > 80:
            raise _error()
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _one(nodes):
    if len(nodes) != 1:
        raise _error()
    return nodes[0]


def _render(node):
    if isinstance(node, str):
        return node
    if node.tag in _HIDDEN:
        return ''
    value = ''.join(_render(child) for child in node.children)
    return '\n' + value + '\n' if node.tag in _BLOCK else value


def _text(node):
    return ' '.join(_render(node).split())


def _date(value, fmt):
    if type(value) is not str:
        raise _error()
    result = datetime.strptime(value, fmt)
    if result.strftime(fmt) != value:
        raise _error()
    return result.date().isoformat()


def _notice_reference(value):
    if type(value) is not str:
        raise _error()
    reference = value.removeprefix(ORIGIN)
    if _REFERENCE.fullmatch(reference) is None:
        raise _error()
    return reference


def _search(body, query):
    value = _json(body)
    if (not isinstance(value, dict) or value.get('success') is not True or value.get('code') != '200'
            or not isinstance(value.get('data'), dict) or type(value['data'].get('html')) is not str):
        raise _error()
    root = _Markup(value['data']['html']).root
    pagination = _one(root.find(class_name='pagination')).attrs.get('querydata')
    if type(pagination) is not str or len(pagination) > 256:
        raise _error()
    counts = _json(pagination.replace("'", '"'))
    if (not isinstance(counts, dict) or set(counts) != {'rows', 'count', 'pageNo'}
            or any(type(item) is not str or re.fullmatch(r'[0-9]{1,9}\s*', item, re.ASCII) is None for item in counts.values())
            or counts['rows'] != str(PAGE_SIZE) or counts['pageNo'] != query['page']):
        raise _error()
    total, page = int(counts['count']), int(counts['pageNo'])
    rows = _one(root.find(class_name='page-content')).find('li')
    if len(rows) != min(PAGE_SIZE, max(0, total - (page - 1) * PAGE_SIZE)):
        raise _error()
    notices, seen = [], set()
    for row in rows:
        anchors = row.find('a')
        if not anchors:
            raise _error()
        primary = anchors[0]
        reference = _notice_reference(primary.attrs.get('href'))
        title = _text(primary)
        if not title or len(title) > 500 or primary.attrs.get('title') != title or reference in seen:
            raise _error()
        seen.add(reference)
        displayed = _text(_one(row.find('span')))
        notices.append({'article_id': _REFERENCE.fullmatch(reference)[2], 'reference': reference,
            'source_url': ORIGIN + reference, 'title': title,
            'published_date': _date(displayed, '%Y-%m-%d'), 'publication_date_raw': displayed,
            'applicability': 'not_assessed'})
    return {'operation': 'search', 'keyword': query['keyword'], 'page': page, 'page_size': PAGE_SIZE,
        'declared_total': total, 'source_navigation_page_limit': NAVIGATION_PAGE_LIMIT,
        'source_navigation_pages': min(NAVIGATION_PAGE_LIMIT, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        'notices': notices, 'notice': None}


def resource_url(raw):
    if type(raw) is not str or not 1 <= len(raw) <= 2048 or any(ord(char) < 32 for char in raw):
        raise _error()
    # Retain original declarations. Only reviewed same-site file paths become links.
    path = raw.removeprefix(ORIGIN)
    safe = (re.fullmatch(r'/cms_files/filemanager/[A-Za-z0-9_./-]+', path, re.ASCII) is not None
        and '..' not in path and '//' not in path)
    return urljoin(ORIGIN, path) if safe else None


def _asset(node):
    raw = node.attrs.get('src' if node.tag == 'img' else 'href')
    url = resource_url(raw)
    label = node.attrs.get('alt') or _text(node)
    if len(label) > 1000:
        raise _error()
    return {'kind': 'image' if node.tag == 'img' else 'link', 'source_reference': raw,
        'url': url, 'label': label,
        'fetch_status': 'not_fetched'}


def _notice(body, query):
    root = _Markup(body).root
    meta = {}
    names = {'SiteName', 'SiteDomain', 'SiteID', 'ColId', 'ColumnName', 'ArticleTitle',
        'PubDate', 'DeployTime', 'ContentSource', 'Url', 'server'}
    for node in root.find('meta'):
        name = node.attrs.get('name')
        if name in names:
            if name in meta or type(node.attrs.get('content')) is not str:
                raise _error()
            meta[name] = node.attrs['content']
    if (set(meta) != names or meta['SiteName'] != SITE_NAME or meta['SiteDomain'] != 'www.samrdprc.org.cn'
            or meta['SiteID'] != WEB_ID or meta['ColId'] != COLUMN_ID or meta['ColumnName'] != '汽车召回'
            or meta['Url'] != query['reference'] or meta['server'] != query['reference']):
        raise _error()
    title = _text(_one(root.find(class_name='content_title')))
    if not title or len(title) > 500 or title != meta['ArticleTitle']:
        raise _error()
    dates = re.findall(r'发布时间：\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', _text(_one(root.find(class_name='gyj_ly'))))
    if len(dates) != 1 or _date(dates[0], '%Y-%m-%d') != _date(meta['DeployTime'], '%Y-%m-%d %H:%M:%S'):
        raise _error()
    _date(meta['PubDate'], '%Y-%m-%d %H:%M')
    content = _one(root.find('div', element_id='zoom'))
    text = '\n'.join(' '.join(line.split()) for line in _render(content).splitlines() if line.strip())
    assets = [_asset(node) for node in content.find() if node.tag in {'img', 'a'}]
    if not text or len(text) > 100000 or len(assets) > 100:
        raise _error()
    notice = {'article_id': _REFERENCE.fullmatch(query['reference'])[2], 'reference': query['reference'],
        'source_url': query_url(query), 'title': title, 'published_date': dates[0],
        'publication_date_raw': dates[0], 'deployed_at_raw': meta['DeployTime'], 'pub_date_raw': meta['PubDate'],
        'content_source_raw': meta['ContentSource'], 'text': text, 'assets': assets,
        'metadata': meta, 'applicability': 'not_assessed'}
    return {'operation': 'notice', 'notices': [], 'notice': notice}


def parse_document(body, query):
    query_url(query)
    if (type(body) is not str or not 1 <= len(body.encode('utf-8')) <= MAX_BYTES
            or any(ord(char) < 32 and char not in '\t\r\n' for char in body)):
        raise _error()
    return _search(body, query) if query['operation'] == 'search' else _notice(body, query)


async def _policy(client):
    global _robots, _robots_last
    now = time.monotonic()
    if _robots is not None and now - _robots[0] < 3600:
        return _robots[1]
    if now - _robots_last < 2:
        raise SourceAccessError('source_rate_limited')
    _robots_last = now
    url = ORIGIN + '/robots.txt'
    response = await client.get(url, allowed_types=('text/plain',), allowed_statuses=(200, 404, 410),
        max_bytes=128 * 1024, can_follow=lambda target: target == url)
    policy = RobotsPolicy(response.body if response.status == 200 else '', USER_AGENT)
    _robots = (time.monotonic(), policy)
    return policy


async def fetch(query, cached=None, *, on_observation=None, parser_selection=None):
    try:
        url = query_url(query)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return {'status': 'unavailable', 'reason': 'unsupported_samr_query'}
    if source_metadata()['status'] != 'ready':
        return {'status': 'unavailable', 'reason': 'source_disabled'}
    from .registry import pin_parser_selection
    try:
        descriptor, metadata, options = pin_parser_selection(SOURCE_ID, 'recall', parser_selection)
    except ParserRunError as error:
        reason = parser_failure_reason(error.code)
        return {'status': 'unavailable', 'reason': reason, 'parser_error': reason, 'parser_receipt': error.receipt}
    now = time.monotonic()
    if now < _state['until']:
        return {'status': 'unavailable', 'reason': 'circuit_open', **metadata}
    if _state['busy'] or now - _state['last'] < _state['interval']:
        return {'status': 'unavailable', 'reason': 'source_rate_limited', **metadata}
    _state['busy'] = True
    observation, parser_failure = None, None
    try:
        headers = {'Accept': 'application/json' if query['operation'] == 'search' else 'text/html'}
        validators = {}
        if (cached and cached.get('url') == url and cached.get('body')
                and cached.get('parser_version') == descriptor['parser_version']
                and metadata['parser_identity']['deployment_revision'] is not None
                and cached.get('parser_identity') == metadata['parser_identity']):
            if cached.get('etag'):
                validators['If-None-Match'] = cached['etag']
            elif cached.get('last_modified'):
                validators['If-Modified-Since'] = cached['last_modified']
        async with asyncio.timeout(15):
            async with SafeHttpClient(frozenset({'www.samrdprc.org.cn'})) as client:
                policy = await _policy(client)
                if not policy.can_fetch(url):
                    raise SourceAccessError('robots_disallowed')
                _state['interval'] = max(2.0, policy.minimum_interval)
                if time.monotonic() - _state['last'] < _state['interval']:
                    raise SourceAccessError('source_rate_limited')
                _state['last'] = time.monotonic()
                response = await client.get(url, headers={**headers, **validators},
                    allowed_types=(headers['Accept'],), max_bytes=MAX_BYTES,
                    can_follow=lambda target: target == url and policy.can_fetch(target))
                if response.url != url:
                    raise SourceAccessError('samr_response_url_mismatch')
                if response.status == 304:
                    if not validators or not cached:
                        raise SourceAccessError('unexpected_304')
                    _state.update(failures=0, until=0)
                    return {'status': 'not_modified', 'url': url, 'etag': response.etag,
                        'last_modified': response.last_modified, **metadata}
                observation = {'url': url, 'body': response.body, 'content_type': response.content_type, **deepcopy(metadata)}
                if on_observation is not None:
                    on_observation(observation)
                parsed = await parse_isolated(SOURCE_ID, response.body, query, descriptor['parser_version'], descriptor['parser_digest'], **options)
                _state.update(failures=0, until=0)
                return {'status': 'ok', **observation, 'etag': response.etag,
                    'last_modified': response.last_modified, 'document': parsed['payload'], 'parser_receipt': parsed['receipt']}
    except CaptureWriteError:
        return {'status': 'unavailable', 'reason': 'evidence_capture_failed', **metadata}
    except ParserRunError as error:
        reason, parser_failure = parser_failure_reason(error.code), error
    except TimeoutError:
        reason = 'upstream_timeout'
    except SourceAccessError as error:
        reason = str(error)
    except (aiohttp.ClientError, OSError):
        reason = 'upstream_network_error'
    except Exception:
        reason = 'parser_schema_changed' if observation is not None else 'source_fetch_failed'
    finally:
        _state['busy'] = False
    if reason not in {'robots_disallowed', 'source_rate_limited'}:
        _state['failures'] += 1
        if _state['failures'] >= 3:
            _state['until'] = time.monotonic() + 60
    if observation is not None and parser_failure is not None:
        observation = {**observation, 'parser_error': reason}
    return {'status': 'unavailable', 'reason': reason, **metadata,
        **({'rejected_observation': observation} if observation is not None else {}),
        **({'parser_error': reason, 'parser_receipt': parser_failure.receipt} if parser_failure else {})}
