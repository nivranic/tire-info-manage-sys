"""Fixed official Safety Gate XML distribution and source-native identities."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import os
import re
import time
import xml.etree.ElementTree as etree

import aiohttp

from .robots import RobotsPolicy
from .transport import SafeHttpClient, SourceAccessError, USER_AGENT
from ..captures import CaptureWriteError, parser_failure_reason
from ..parser_runtime import ParserRunError, parse_isolated

SOURCE_ID = 'eu-safety-gate'
PARSER_VERSION = 'safety-gate-weekly-xml@1.0.0'
ORIGIN = 'https://ec.europa.eu'
BASE = ORIGIN + '/safety-gate-alerts'
INDEX_URL = BASE + '/api/download/weeklyReport/list/xml/en'
METADATA_URL = 'https://data.europa.eu/api/hub/repo/datasets/rapex-rapid-alert-system-non-food.jsonld'
LICENSE = {'distribution_id': 'http://data.europa.eu/88u/distribution/d932935c-3916-4421-a6a4-91efe196ef4b',
           'license_uri': 'http://publications.europa.eu/resource/authority/licence/CC0',
           'metadata_url': METADATA_URL}
ATTRIBUTION = 'European Commission — Safety Gate. © European Union. ' + BASE
supports_parser_deployments = True
_state = {'last': -float('inf'), 'failures': 0, 'until': 0, 'busy': False, 'interval': 2.0}
_robots = None
_robots_last = -float('inf')
_NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'
_TYPE = '{http://www.w3.org/2001/XMLSchema-instance}type'
INDEX_FIELDS = {'report_language', 'reference', 'publicationDate', 'year', 'month', 'day', 'week', 'URL'}
REPORT_FIELDS = {'report_language', 'report_date', 'report_year', 'report_week', 'report_addendum'}
ALERT_FIELDS = {'order', 'caseNumber', 'publicationDate', 'reference', 'category', 'product', 'brand',
    'name', 'type_numberOfModel', 'batchNumber', 'barcode', 'riskType', 'danger', 'measures',
    'URLrecall', 'description', 'notifyingCountry', 'countryOfOrigin', 'type', 'level', 'pictures',
    'onlineTrader', 'companyRecallCode', 'productionDates'}


def source_metadata():
    disabled = SOURCE_ID in {item.strip() for item in os.getenv('TI_DISABLED_SOURCES', '').split(',')}
    return {'id': SOURCE_ID, 'name': 'Safety Gate · 欧盟危险产品预警', 'region': 'EU',
        'source_class': 'regulatory', 'target_kind': 'recall', 'status': 'disabled' if disabled else 'ready',
        'homepage': BASE, 'supported_models': [], 'parser_version': PARSER_VERSION,
        'access_policy': 'reviewed_official_xml_distribution', 'license': dict(LICENSE),
        'description': '查询官方英文周报索引与指定周报，保留告警原生身份、原文和未知适用性。'}


def query_url(query):
    if query == {'operation': 'reports'}:
        return INDEX_URL
    if (not isinstance(query, dict) or set(query) != {'operation', 'report_id', 'reference'}
            or query['operation'] != 'report' or type(query['report_id']) is not str
            or not re.fullmatch(r'[1-9][0-9]{0,11}', query['report_id'], re.ASCII)
            or type(query['reference']) is not str
            or not re.fullmatch(r'Report-[0-9]{4}-[0-9]{1,3}', query['reference'], re.ASCII)
            or not 1 <= int(query['reference'].rsplit('-', 1)[1]) <= 53):
        raise ValueError('unsupported_safety_gate_query')
    identity = query['report_id']
    return BASE + '/api/download/weeklyReport/detail/xml/' + identity + '?language=en&search=WEB_REPORT%7C:%7C' + identity + ','


def permitted_url(url, query):
    try:
        return type(url) is str and url == query_url(query)
    except (ValueError, TypeError, KeyError):
        return False


def _text(node, *, required=False):
    if (len(node) or set(node.attrib) - {_NIL} or node.get(_NIL) not in (None, 'true', 'false')
            or node.get(_NIL) == 'true' and node.text not in (None, '')):
        raise ValueError('safety_gate_scalar_invalid')
    value = None if node.get(_NIL) == 'true' else node.text
    if value is not None and (len(value) > 60000 or '\x00' in value or any(ord(char) < 32 and char not in '\t\r\n' for char in value)):
        raise ValueError('safety_gate_text_invalid')
    if required and (value is None or not value.strip()):
        raise ValueError('safety_gate_required_field_missing')
    return value


def _fields(node, expected):
    values = {child.tag: child for child in node}
    if set(values) != expected or len(values) != len(node):
        raise ValueError('safety_gate_fields_changed')
    return values


def _date(value, fmt):
    result = datetime.strptime(value, fmt).date()
    if result.strftime(fmt) != value:
        raise ValueError('safety_gate_date_invalid')
    return result.isoformat()


def parse_xml(body, query):
    query_url(query)
    if (type(body) is not str or not body or len(body.encode('utf-8')) > 8 * 1024 * 1024
            or '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper()):
        raise ValueError('safety_gate_xml_invalid')
    # Reject DTD/entity declarations before the standard XML parser sees them.
    # ElementTree discards comments and does not resolve external resources.
    root = etree.fromstring(body)
    if (root.tag != 'Safety-Gate' or root.attrib or root.text and root.text.strip()
            or any(row.tail and row.tail.strip() for row in root)):
        raise ValueError('safety_gate_root_invalid')
    if query['operation'] == 'reports':
        if any(row.tag != 'weeklyReport' or row.attrib for row in root) or len(root) > 3000:
            raise ValueError('safety_gate_index_invalid')
        reports, identities, references = [], set(), set()
        for row in root:
            nodes = _fields(row, INDEX_FIELDS)
            values = {key: _text(node, required=True) for key, node in nodes.items()}
            reference = values['reference']
            match = re.fullmatch(re.escape(BASE) + r'/api/download/weeklyReport/detail/xml/([1-9][0-9]{0,11})\?language=en&search=WEB_REPORT%7C:%7C\1,', values['URL'])
            if match is None or values['report_language'] != 'en':
                raise ValueError('safety_gate_index_url_invalid')
            identity = match.group(1)
            selected = {'operation': 'report', 'report_id': identity, 'reference': reference}
            if values['URL'] != query_url(selected) or identity in identities or reference in references:
                raise ValueError('safety_gate_duplicate_report')
            published = _date(values['publicationDate'], '%d/%m/%Y')
            year, month, day = published.split('-')
            if (values['month'] != str(int(month)) or values['day'] != str(int(day))
                    or reference.split('-')[1] != values['year']
                    or int(reference.rsplit('-', 1)[1]) != int(values['week'])):
                raise ValueError('safety_gate_index_date_mismatch')
            identities.add(identity)
            references.add(reference)
            reports.append({'report_id': identity, 'reference': reference, 'published_date': published,
                'publication_date_raw': values['publicationDate'], 'url': values['URL']})
        return {'operation': 'reports', 'reports': reports, 'report': None, 'alerts': []}
    headers = [row for row in root if row.tag != 'notifications']
    values = {row.tag: _text(row) for row in headers}
    if set(values) != REPORT_FIELDS or len(values) != len(headers) or values['report_language'] != 'en':
        raise ValueError('safety_gate_report_header_invalid')
    year, week = query['reference'].removeprefix('Report-').split('-')
    if values['report_year'] != year or values['report_week'] != str(int(week)):
        raise ValueError('safety_gate_report_identity_mismatch')
    published = _date(values['report_date'], '%d/%m/%Y')
    alerts, identities, cases = [], set(), set()
    rows = root.findall('notifications')
    if len(rows) > 1000:
        raise ValueError('safety_gate_report_too_large')
    for position, row in enumerate(rows, 1):
        kind = row.get(_TYPE)
        if set(row.attrib) - {_TYPE} or kind not in (None, 'webReportXmlWeeklyReportDetailMotorVehicleContentDto', 'webReportXmlWeeklyReportDetailContentDto'):
            raise ValueError('safety_gate_alert_type_changed')
        optional = {'pictures'}
        if kind == 'webReportXmlWeeklyReportDetailContentDto':
            optional |= {'companyRecallCode', 'productionDates'}
        nodes = {child.tag: child for child in row}
        if len(nodes) != len(row) or not ALERT_FIELDS - optional <= set(nodes) <= ALERT_FIELDS:
            raise ValueError('safety_gate_fields_changed')
        fields = {key: _text(nodes[key], required=key in {'order', 'caseNumber', 'publicationDate', 'reference'})
            if key in nodes else None for key in sorted(ALERT_FIELDS - {'pictures'})}
        match = re.fullmatch(re.escape(BASE) + r'/screen/webReport/alertDetail/(-?[1-9][0-9]{0,11})', fields['reference'])
        if (match is None or fields['order'] != str(position) or match.group(1) in identities
                or fields['caseNumber'] in cases or len(fields['caseNumber']) > 80):
            raise ValueError('safety_gate_alert_identity_invalid')
        images = nodes.get('pictures')
        if images is not None and (images.attrib or images.text and images.text.strip() or len(images) > 100):
            raise ValueError('safety_gate_pictures_invalid')
        pictures = []
        for image in images if images is not None else ():
            value = _text(image, required=True)
            if image.tag != 'picture' or not re.fullmatch(re.escape(BASE) + r'/public/api/notification/image/-?[1-9][0-9]{0,11}', value):
                raise ValueError('safety_gate_picture_url_invalid')
            pictures.append(value)
        identity = match.group(1)
        identities.add(identity)
        cases.add(fields['caseNumber'])
        alerts.append({'alert_id': identity, 'case_number': fields['caseNumber'],
            'published_date': _date(fields['publicationDate'], '%d-%m-%Y'), 'source_url': fields['reference'],
            'fields': fields, 'pictures': pictures, 'applicability': 'not_assessed'})
    return {'operation': 'report', 'reports': [], 'report': {'report_id': query['report_id'],
        'reference': query['reference'], 'published_date': published, 'publication_date_raw': values['report_date'],
        'url': query_url(query), 'addendum_raw': values['report_addendum']}, 'alerts': alerts}


async def _policy(client):
    global _robots, _robots_last
    now = time.monotonic()
    if _robots is not None and now - _robots[0] < 3600:
        return _robots[1]
    if now - _robots_last < 2:
        raise SourceAccessError('source_rate_limited')
    _robots_last = now
    response = await client.get(ORIGIN + '/robots.txt', allowed_types=('text/plain',),
        allowed_statuses=(200, 404, 410), max_bytes=128 * 1024, can_follow=lambda url: url == ORIGIN + '/robots.txt')
    policy = RobotsPolicy(response.body if response.status == 200 else '', USER_AGENT)
    _robots = (time.monotonic(), policy)
    return policy


async def fetch(query, cached=None, *, on_observation=None, parser_selection=None):
    try:
        url = query_url(query)
    except (ValueError, TypeError, KeyError):
        return {'status': 'unavailable', 'reason': 'unsupported_safety_gate_query'}
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
            async with SafeHttpClient(frozenset({'ec.europa.eu'})) as client:
                policy = await _policy(client)
                if not policy.can_fetch(url):
                    raise SourceAccessError('robots_disallowed')
                _state['interval'] = max(2.0, policy.minimum_interval)
                if time.monotonic() - _state['last'] < _state['interval']:
                    raise SourceAccessError('source_rate_limited')
                _state['last'] = time.monotonic()
                response = await client.get(url, headers={'Accept': 'application/xml', **validators},
                    allowed_types=('application/xml',), max_bytes=8 * 1024 * 1024,
                    can_follow=lambda target: target == url and policy.can_fetch(target))
                if response.url != url:
                    raise SourceAccessError('safety_gate_response_url_mismatch')
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
