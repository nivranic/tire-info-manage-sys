"""Trusted, bounded startup-only material permissions. Never user-supplied URLs."""
from datetime import date
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, StrictBool, field_validator

from .domain import StrictModel, digest


class MaterialPolicyError(Exception):
    """Fixed safe error; never include configuration values or paths."""


def checked_url(value):
    try:
        p = urlsplit(value)
        host = p.hostname or ''
        if (not isinstance(value, str) or len(value) > 2048 or p.scheme != 'https'
                or p.username is not None or p.password is not None or p.query or p.fragment
                or '?' in value or '#' in value or '\\' in value or p.port not in (None, 443)
                or any(ord(c) <= 32 or ord(c) == 127 for c in value)
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+', host)
                or p.netloc not in (host, host + ':443') or host.endswith(('.local', '.localhost', '.internal'))):
            raise ValueError('invalid URL')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError('IP URL')
        # Avoid a distinct spelling becoming a different URL in the HTTP client.
        if '%' in p.netloc or any(segment in ('.', '..') for segment in p.path.split('/')):
            raise ValueError('ambiguous URL')
        value.encode('ascii', errors='strict')
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('来源地址必须是精确的公共 HTTPS 域名地址') from None
    return value


def plain(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('有界文本无效')
    value.encode('utf-8', errors='strict')
    return value


class MaterialRights(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    rights_holder: str = Field(min_length=1, max_length=160)
    basis: str = Field(min_length=1, max_length=500)
    license_url: str | None
    store_original: StrictBool
    workspace_reopen: StrictBool
    quote_identifiers: StrictBool
    provider_use: StrictBool
    export: StrictBool

    _text = field_validator('rights_holder', 'basis')(plain)

    @field_validator('license_url')
    @classmethod
    def license_reference(cls, value):
        return checked_url(value) if value is not None else None


class MaterialPolicy(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    policy_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')
    title: str = Field(min_length=1, max_length=160)
    publisher: str = Field(min_length=1, max_length=160)
    edition: str | None = Field(max_length=80)
    published_at: str | None
    source_reference_url: str
    download_url: str
    redirect_urls: list[str] = Field(max_length=3)
    rights: MaterialRights

    _text = field_validator('title', 'publisher')(plain)
    _urls = field_validator('source_reference_url', 'download_url')(checked_url)

    @field_validator('edition')
    @classmethod
    def optional_text(cls, value):
        return plain(value) if value is not None else None

    @field_validator('published_at')
    @classmethod
    def published_date(cls, value):
        if value is not None and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) or date.fromisoformat(value).isoformat() != value):
            raise ValueError('出版日期须为 ISO 日期')
        return value

    @field_validator('redirect_urls')
    @classmethod
    def redirects(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('重复跳转地址')
        return [checked_url(url) for url in value]


def canonical_policy(value):
    policy = MaterialPolicy.model_validate(value).model_dump()
    rights = policy['rights']
    if not all(rights[key] is True for key in ('store_original', 'workspace_reopen', 'quote_identifiers')) or any(
            rights[key] is not False for key in ('provider_use', 'export')):
        raise ValueError('许可范围不支持')
    if policy['download_url'] in policy['redirect_urls']:
        raise ValueError('重复初始地址')
    return {**policy, 'policy_fingerprint': digest(policy)}


class PolicyCatalog:
    def __init__(self, items):
        # Serialized strings avoid exposing mutable shared snapshots to callers.
        self._items = tuple(json.dumps(row, ensure_ascii=False) for row in items)

    def items(self):
        return [json.loads(row) for row in self._items]

    def get(self, policy_id):
        return next((row for row in self.items() if row['policy_id'] == policy_id), None)


def load_policies():
    path = os.getenv('TI_SOURCE_MATERIAL_POLICIES_FILE')
    if not path:
        return PolicyCatalog([])
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError('duplicate key')
            values[key] = value
        return values
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError('configuration too large')
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        if (not isinstance(data, dict) or set(data) != {'schema', 'policies'}
                or data['schema'] != 'source-material-policies@1' or not isinstance(data['policies'], list)
                or len(data['policies']) > 16):
            raise ValueError('invalid configuration')
        items = [canonical_policy(row) for row in data['policies']]
        if len({row['policy_id'] for row in items}) != len(items):
            raise ValueError('duplicate policy')
        return PolicyCatalog(items)
    except Exception:
        raise MaterialPolicyError('source_material_policy_invalid') from None
