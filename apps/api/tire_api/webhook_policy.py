"""One-time trusted target catalog. Secrets never enter public views or storage."""
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .domain import digest

NOTICE = ('仅外发通知引用，不包含来源事实或私人条件。轮胎监控为本机共享；召回仅已形成事件的规则通知。'
    '投递至少一次，接收方须去重；超时或取消不证明对端未收到，开始发送后无法撤回。')
BODY_NOTICE = '仅通知引用；不是来源事实、性能结论或安装安全证明。接收方须按delivery_id去重。'
CHANNELS = ('tire_monitor', 'recall_monitor', 'interest')
DOMAINS = ('tire', 'test_event', 'vehicle', 'fitment', 'tire_curation', 'tire_lifecycle',
    'tire_identity', 'tire_catalog', 'tire_curation_validity')


def strict_json(value):
    def pairs(items):
        result = {}
        for key, child in items:
            if key in result:
                raise ValueError('webhook_configuration_invalid')
            result[key] = child
        return result
    def invalid(_value):
        raise ValueError('webhook_configuration_invalid')
    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid)


def endpoint_host(url):
    if type(url) is not str or len(url) > 2048 or any(ord(char) < 33 for char in url) or '\\' in url or '?' in url or '#' in url:
        raise ValueError('webhook_target_invalid')
    parsed = urlsplit(url)
    host = parsed.hostname
    if (parsed.scheme != 'https' or not host or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or host.endswith('.')):
        raise ValueError('webhook_target_invalid')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('webhook_target_invalid')
    # Legacy inet_aton forms must not bypass the connector's resolver.
    if (re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*', host, re.I)
            or not host.isascii() or '.' not in host or len(host) > 253
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part, re.I) for part in host.split('.'))):
        raise ValueError('webhook_target_invalid')
    return host.lower()


@dataclass(frozen=True)
class Target:
    id: str
    title: str
    url: str = field(repr=False)
    signing_key_env: str = field(repr=False)
    key: bytes | None = field(repr=False)
    endpoint_host: str
    policy_fingerprint: str | None

    def public(self):
        ready = self.key is not None
        return {'id': self.id, 'title': self.title, 'endpoint_host': self.endpoint_host,
            'ready': ready, 'state': 'ready' if ready else 'key_unavailable', 'policy_fingerprint': self.policy_fingerprint}


@dataclass(frozen=True)
class Catalog:
    state: str
    targets: dict[str, Target] = field(default_factory=dict, repr=False)

    def public(self):
        return {'schema': 'webhook-targets@1', 'catalog_state': self.state,
            'items': [target.public() for target in self.targets.values()], 'notice': NOTICE}


def load_targets():
    path = os.getenv('TI_WEBHOOK_TARGETS_FILE')
    if not path:
        return Catalog('empty')
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError()
        data = strict_json(raw.decode('utf-8'))
        if (type(data) is not dict or set(data) != {'schema', 'targets'} or data['schema'] != 'webhook-targets@1'
                or type(data['targets']) is not list or len(data['targets']) > 16):
            raise ValueError()
        targets = {}
        for value in data['targets']:
            if (type(value) is not dict or set(value) != {'id', 'title', 'url', 'signing_key_env'}
                    or type(value['id']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value['id'])
                    or value['id'] in targets or type(value['title']) is not str
                    or not value['title'].strip() or len(value['title']) > 120 or not value['title'].isprintable()
                    or type(value['signing_key_env']) is not str
                    or not re.fullmatch(r'TI_WEBHOOK_SIGNING_[A-Z0-9_]+', value['signing_key_env'])):
                raise ValueError()
            host = endpoint_host(value['url'])
            secret = os.getenv(value['signing_key_env'], '')
            key = bytes.fromhex(secret) if re.fullmatch(r'[0-9a-fA-F]{64}', secret) else None
            fingerprint = digest({**value, 'key_commitment': hashlib.sha256(key).hexdigest()}) if key else None
            targets[value['id']] = Target(**value, key=key, endpoint_host=host, policy_fingerprint=fingerprint)
        return Catalog('ready' if targets else 'empty', targets)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, OverflowError):
        return Catalog('invalid')
