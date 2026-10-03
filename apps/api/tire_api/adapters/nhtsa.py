"""Official tire-campaign lookup. A returned product is never an exact-SKU verdict."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import os
import re
import time
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

import aiohttp

from .robots import RobotsPolicy
from .transport import SafeHttpClient, SourceAccessError, USER_AGENT
from ..captures import CaptureWriteError, parser_failure_reason
from ..domain import stable_json
from ..parser_runtime import ParserRunError, parse_isolated, strict_json

SOURCE_ID = 'nhtsa-us-recalls'
HOST = 'api.nhtsa.gov'
ORIGIN = f'https://{HOST}'
API_PATH = '/recalls/campaignNumber'
PARSER_VERSION = 'nhtsa-campaign@1.0.0'
supports_parser_deployments = True
supports_response_limits = True
_CAMPAIGN = re.compile(r'\d{2}T\d{6}', re.ASCII)
_state = {'last': -float('inf'), 'failures': 0, 'until': 0, 'busy': False, 'interval': 2.0}
_robots = None
_robots_last = -float('inf')


def campaign_number(value: str) -> str:
    if not isinstance(value, str) or not _CAMPAIGN.fullmatch(value.strip().upper()):
        raise ValueError('须提供轮胎类召回编号，例如 23T001000')
    return value.strip().upper()


def source_metadata() -> dict:
    disabled = SOURCE_ID in {value.strip() for value in os.getenv('TI_DISABLED_SOURCES', '').split(',')}
    return {'id': SOURCE_ID, 'name': 'NHTSA · 美国轮胎召回', 'region': 'US',
            'source_class': 'regulatory', 'target_kind': 'recall',
            'access_policy': 'reviewed_public_api_robots_rfc9309',
            'status': 'disabled' if disabled else 'ready', 'homepage': 'https://www.nhtsa.gov/recalls',
            'supported_models': [], 'parser_version': PARSER_VERSION,
            'description': '按轮胎召回公告编号在线核验；候选公告不证明某个精确SKU或实物轮胎受影响。'}


def query_url(query: dict) -> str:
    if isinstance(query, dict) and set(query) == {'search', 'offset'}:
        search, offset = query['search'], query['offset']
        if (not isinstance(search, str) or not 1 <= len(search) <= 120 or search != ' '.join(search.split())
                or any(ord(char) < 32 for char in search) or not isinstance(offset, str)
                or not re.fullmatch(r'0|[1-9][0-9]{0,4}', offset, re.ASCII)
                or int(offset) > 10000 or int(offset) % 10):
            raise ValueError('unsupported_recall_search')
        return ORIGIN + '/tires/bySearch?' + urlencode({'query': search, 'dataSet': 'safetyIssues',
            'data': 'recalls', 'max': '10', 'offset': offset, 'order': 'asc', 'sort': 'productName'})
    if not isinstance(query, dict) or set(query) != {'campaign_number'}:
        raise ValueError('unsupported_recall_query')
    return f'{ORIGIN}{API_PATH}?campaignNumber={campaign_number(query["campaign_number"])}'


def permitted_url(url: str) -> bool:
    """No caller-controlled host/path, extra keys, encoding, duplicates or fragments."""
    if not isinstance(url, str):
        return False
    prefix = f'{ORIGIN}{API_PATH}?campaignNumber='
    if url.startswith(prefix) and bool(_CAMPAIGN.fullmatch(url[len(prefix):])):
        return True
    try:
        parsed = urlsplit(url)
        parameters = dict(parse_qsl(parsed.query, strict_parsing=True))
        return url == query_url({'search': parameters['query'], 'offset': parameters['offset']})
    except (ValueError, KeyError, TypeError):
        return False


def parse_json(body: str, query: dict) -> list[dict] | dict:
    if 'search' in query:
        return parse_search(body, query)
    expected = campaign_number(query['campaign_number'])
    query_url(query)
    value = strict_json(body)
    if not isinstance(value, dict) or not {'Count', 'Message', 'results'} <= set(value):
        raise ValueError('recall_envelope_invalid')
    count, rows = value['Count'], value['results']
    if (type(count) is not int or not 0 <= count <= 1000 or not isinstance(rows, list)
            or len(rows) != count or value['Message'] != 'Results returned successfully'):
        raise ValueError('recall_incomplete_or_failed_result')
    # This endpoint has no pagination contract. Never accept an introduced page
    # cursor/total as if the bounded result were the complete official response.
    if set(value) - {'Count', 'Message', 'results'}:
        raise ValueError('recall_envelope_changed')
    fields = {'Manufacturer': 'manufacturer', 'Component': 'component', 'Summary': 'summary',
              'Consequence': 'consequence', 'Remedy': 'remedy', 'Notes': 'notes',
              'Make': 'make', 'Model': 'model', 'ModelYear': 'model_year_raw'}
    required = {'Manufacturer', 'Component', 'Summary', 'Consequence', 'Remedy', 'Make', 'Model'}
    parsed = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('NHTSACampaignNumber') != expected:
            raise ValueError('recall_campaign_mismatch')
        normalized = {'campaign_number': expected}
        for key, name in fields.items():
            if key in required and key not in row:
                raise ValueError('recall_required_field_missing')
            item = row.get(key)
            if (item is not None and (not isinstance(item, str) or len(item) > 60000 or '\x00' in item)
                    or key in required and (not isinstance(item, str) or not item.strip())):
                raise ValueError('recall_field_invalid')
            normalized[name] = item
        received = row.get('ReportReceivedDate')
        if not isinstance(received, str) or not re.fullmatch(r'\d{2}/\d{2}/\d{4}', received, re.ASCII):
            raise ValueError('recall_date_invalid')
        # Verified against NHTSA's ISO tire API and YYYYMMDD bulk RCDATE;
        # this legacy endpoint uses DD/MM/YYYY despite its US origin.
        normalized['report_received_date'] = datetime.strptime(received, '%d/%m/%Y').date().isoformat()
        normalized['report_received_date_raw'] = received
        units = row.get('PotentialNumberofUnitsAffected')
        if units is not None and (type(units) is not int or not 0 <= units <= 2**53):
            raise ValueError('recall_units_invalid')
        normalized['potential_units'] = units
        # ModelYear 9999 is Unknown/Not Applicable in NHTSA's own data layout,
        # not a tire production year. Scope remains in the official source text.
        normalized['applicability'] = 'not_assessed'
        fingerprint = stable_json(normalized)
        if fingerprint in seen:
            raise ValueError('recall_duplicate_product_record')
        seen.add(fingerprint)
        parsed.append(normalized)
    return sorted(parsed, key=stable_json)


def parse_search(body: str, query: dict) -> dict:
    query_url(query)
    value = strict_json(body)
    if not isinstance(value, dict) or not isinstance(value.get('meta'), dict) or not isinstance(value.get('results'), list):
        raise ValueError('recall_search_envelope_invalid')
    meta, rows = value['meta'], value['results']
    if type(meta.get('status')) is not int or meta['status'] != 200 or meta.get('messages') != []:
        raise ValueError('recall_search_failed')
    page = meta.get('pagination')
    if (not isinstance(page, dict) or any(type(page.get(key)) is not int for key in ('count', 'max', 'offset', 'total'))
            or page['offset'] != int(query['offset']) or page['max'] != 10 or not 0 <= page['count'] <= 10
            or len(rows) != page['count'] or not 0 <= page['total'] <= 10000000
            or page['count'] != min(10, max(0, page['total'] - page['offset']))
            or page.get('sort') != 'productName' or page.get('order') != 'asc'):
        raise ValueError('recall_search_pagination_invalid')

    def page_url(url, offset):
        if not isinstance(url, str):
            return False
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, strict_parsing=True)
        params = dict(pairs)
        expected = dict(parse_qsl(urlsplit(query_url({**query, 'offset': str(offset)})).query))
        return (parts.scheme == 'https' and parts.netloc == HOST and parts.path == '/tires/bySearch'
                and not parts.fragment and len(pairs) == len(params) and params == expected)

    has_next = page['offset'] + page['count'] < page['total']
    has_previous = page['offset'] > 0
    if not page_url(page.get('currentUrl'), page['offset']):
        raise ValueError('recall_search_page_identity_mismatch')
    if ((has_next and not page_url(page.get('nextUrl'), page['offset'] + 10))
            or (not has_next and page.get('nextUrl') is not None)
            or (has_previous and not page_url(page.get('previousUrl'), max(0, page['offset'] - 10)))
            or (not has_previous and page.get('previousUrl') is not None)):
        raise ValueError('recall_search_page_links_invalid')

    def text(row, key, *, required=False):
        item = row.get(key)
        if (item is not None and (not isinstance(item, str) or len(item) > 60000 or '\x00' in item)
                or required and (not isinstance(item, str) or not item.strip())):
            raise ValueError('recall_search_field_invalid')
        return item

    products, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('id')) is not int or type(row.get('artemisId')) is not int
                or row['id'] <= 0 or row['artemisId'] <= 0 or row['id'] in seen
                or type(row.get('recallsCount')) is not int or not 0 <= row['recallsCount'] <= 1000
                or not isinstance(row.get('safetyIssues'), dict)):
            raise ValueError('recall_search_product_invalid')
        seen.add(row['id'])
        recalls = row['safetyIssues'].get('recalls')
        if not isinstance(recalls, list) or len(recalls) != row['recallsCount']:
            raise ValueError('recall_search_recalls_incomplete')
        campaigns, numbers = [], set()
        for recall in recalls:
            if not isinstance(recall, dict):
                raise ValueError('recall_search_campaign_invalid')
            number = campaign_number(recall.get('nhtsaCampaignNumber'))
            if number != recall['nhtsaCampaignNumber'] or number in numbers:
                raise ValueError('recall_search_campaign_invalid')
            numbers.add(number)
            received = text(recall, 'reportReceivedDate', required=True)
            if not received.endswith('Z') or datetime.fromisoformat(received.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('recall_search_date_invalid')
            documents = recall.get('associatedDocuments')
            associated = recall.get('associatedProducts')
            if (not isinstance(documents, list) or len(documents) > 1000 or not isinstance(associated, list)
                    or len(associated) > 1000 or any(not isinstance(item, dict) for item in associated)):
                raise ValueError('recall_search_scope_invalid')
            if (type(recall.get('associatedDocumentsCount')) is not int
                    or recall['associatedDocumentsCount'] != len(documents)
                    or type(recall.get('associatedProductsCount')) is not int
                    or recall['associatedProductsCount'] != len(associated)):
                raise ValueError('recall_search_scope_incomplete')
            links = []
            for document in documents:
                if not isinstance(document, dict):
                    raise ValueError('recall_search_document_invalid')
                url = text(document, 'url', required=True)
                parts = urlsplit(url)
                if (parts.scheme != 'https' or parts.netloc != 'static.nhtsa.gov' or parts.query or parts.fragment
                        or not re.fullmatch(r'/odi/rcl/\d{4}/[A-Za-z0-9_-]+\.(?:pdf|PDF)', parts.path, re.ASCII)):
                    raise ValueError('recall_search_document_url_invalid')
                links.append({'url': url, 'title': text(document, 'summary') or text(document, 'fileName') or '官方文件'})
            campaigns.append({'campaign_number': number, 'subject': text(recall, 'subject', required=True),
                'report_received_at': received, 'manufacturer': text(recall, 'manufacturer', required=True),
                'summary': text(recall, 'summary', required=True), 'consequence': text(recall, 'consequence', required=True),
                'remedy': text(recall, 'correctiveAction', required=True), 'notes': text(recall, 'notes'),
                'documents': links, 'associated_products': associated})
        products.append({'id': row['id'], 'artemis_id': row['artemisId'], 'brand': text(row, 'brand', required=True),
            'tireline': text(row, 'tireline', required=True), 'size': text(row, 'size'), 'recalls_count': row['recallsCount'],
            'campaigns': campaigns, 'applicability': 'not_assessed'})
    return {'products': products, 'pagination': {**{key: page[key] for key in ('offset', 'max', 'count', 'total')},
                                               'has_next': has_next, 'has_previous': has_previous}}


async def _policy(client):
    global _robots, _robots_last
    now = time.monotonic()
    if _robots is not None and now - _robots[0] < 3600:
        return _robots[1]
    if now - _robots_last < 2:
        raise SourceAccessError('source_rate_limited')
    url = ORIGIN + '/robots.txt'
    _robots_last = now
    # These are fixed, reviewed public API endpoints, not an open crawler.
    # NHTSA's robots resource returns 403 while its API returns 200. RFC 9309
    # 2.3.1.3 treats an unavailable 4xx robots resource as no published rules.
    # Keep 429, network/5xx errors and every API-resource 403 fail-closed;
    # successful robots responses are always parsed and their rules obeyed.
    result = await client.get(url, allowed_types=('text/plain',), allowed_statuses=(200, 403, 404, 410),
                              max_bytes=128 * 1024, can_follow=lambda target: target == url)
    policy = RobotsPolicy(result.body if result.status == 200 else '', USER_AGENT)
    _robots = (time.monotonic(), policy)
    return policy


async def fetch(query: dict, cached: dict | None = None, *,
                on_observation: Callable[[dict], None] | None = None,
                parser_selection: dict | None = None, max_response_bytes: int = 8 * 1024 * 1024) -> dict:
    if type(max_response_bytes) is not int or not 0 < max_response_bytes <= 8 * 1024 * 1024:
        return {'status': 'unavailable', 'reason': 'invalid_response_limit'}
    if source_metadata()['status'] != 'ready':
        return {'status': 'unavailable', 'reason': 'source_disabled'}
    try:
        url = query_url(query)
    except (ValueError, TypeError, KeyError):
        return {'status': 'unavailable', 'reason': 'unsupported_recall_query'}
    from .registry import pin_parser_selection
    try:
        descriptor, metadata, options = pin_parser_selection(SOURCE_ID, 'recall', parser_selection)
    except ParserRunError as error:
        reason = parser_failure_reason(error.code)
        return {'status': 'unavailable', 'reason': reason, 'parser_error': reason,
                'parser_receipt': error.receipt}
    now = time.monotonic()
    if now < _state['until']:
        return {'status': 'unavailable', 'reason': 'circuit_open', **metadata}
    if _state['busy'] or now - _state['last'] < _state['interval']:
        return {'status': 'unavailable', 'reason': 'source_rate_limited', **metadata}
    _state['busy'] = True
    observation = None
    parser_failure = None
    try:
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
            async with SafeHttpClient(frozenset({HOST})) as client:
                policy = await _policy(client)
                if not policy.can_fetch(url):
                    raise SourceAccessError('robots_disallowed')
                _state['interval'] = max(2.0, policy.minimum_interval)
                if time.monotonic() - _state['last'] < _state['interval']:
                    raise SourceAccessError('source_rate_limited')
                for attempt in range(2):
                    _state['last'] = time.monotonic()
                    try:
                        result = await client.get(url, headers={'Accept': 'application/json', **validators}, allowed_types=('application/json',),
                            max_bytes=max_response_bytes, can_follow=lambda target: target == url and policy.can_fetch(target))
                        break
                    except SourceAccessError as error:
                        if str(error) not in {'upstream_http_502', 'upstream_http_503', 'upstream_http_504'} or attempt or _state['interval'] > 3:
                            raise
                        await asyncio.sleep(_state['interval'])
                if result.url != url:
                    raise SourceAccessError('recall_response_url_mismatch')
                if result.status == 304:
                    if not validators or not cached:
                        raise SourceAccessError('unexpected_304')
                    _state.update(failures=0, until=0)
                    return {'status': 'not_modified', 'url': url, 'etag': result.etag,
                            'last_modified': result.last_modified, **metadata}
                observation = {'url': url, 'body': result.body, 'content_type': result.content_type,
                               **deepcopy(metadata)}
                if on_observation is not None:
                    on_observation(observation)
                parsed = await parse_isolated(SOURCE_ID, result.body, query, descriptor['parser_version'],
                                               descriptor['parser_digest'], **options)
                _state.update(failures=0, until=0)
                return {'status': 'ok', **observation, 'etag': result.etag,
                        'last_modified': result.last_modified,
                        ('discovery' if 'search' in query else 'records'): parsed['payload'],
                        'parser_receipt': parsed['receipt']}
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
