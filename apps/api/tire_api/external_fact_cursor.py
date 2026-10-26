"""Dedicated stateless fact-page tokens; never an authorization cache."""
import base64
import binascii
import hashlib
import hmac
import json
import re

from .domain import stable_json

SCHEMA = 'external-tire-facts-cursor@1'
ROUTE = '/external/v1/tire-facts'
MAX_TOKEN_BYTES = 2048
MAX_PAYLOAD_BYTES = 1500
_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
_SOURCE = re.compile(r'[A-Za-z0-9_-]{1,80}')
_HASH = re.compile(r'[0-9a-f]{64}')
_KEY = re.compile(r'[0-9a-f]{32}')
_BASE64 = re.compile(r'[A-Za-z0-9_-]+')
_KEYS = frozenset({'schema', 'key_id', 'owner', 'route', 'source_id', 'query_id',
                   'verification_id', 'limit', 'issued', 'expires', 'window', 'context', 'after'})


class CursorError(ValueError):
    def __init__(self, code='invalid'):
        self.code = code
        super().__init__('fact_cursor_' + code)


def _key(secret):
    if type(secret) is not str or _HASH.fullmatch(secret) is None:
        raise CursorError()
    return bytes.fromhex(secret)


def commitment(secret, tag, value):
    return hmac.new(_key(secret), tag.encode('ascii') + b'\0' +
                    stable_json(value).encode('utf-8'), hashlib.sha256).hexdigest()


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _unb64(value):
    if _BASE64.fullmatch(value) is None:
        raise CursorError()
    raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    if _b64(raw) != value:
        raise CursorError()
    return raw


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CursorError()
        result[key] = value
    return result


def _shape(payload):
    if type(payload) is not dict or payload.keys() != _KEYS:
        raise CursorError()
    if payload['schema'] != SCHEMA or payload['route'] != ROUTE:
        raise CursorError()
    for name, pattern in (('key_id', _KEY), ('source_id', _SOURCE), ('query_id', _ID),
                          ('verification_id', _ID), ('after', _ID), ('owner', _HASH),
                          ('window', _HASH), ('context', _HASH)):
        if type(payload[name]) is not str or pattern.fullmatch(payload[name]) is None:
            raise CursorError()
    if type(payload['limit']) is not int or not 1 <= payload['limit'] <= 20:
        raise CursorError()
    if any(type(payload[name]) is not int or not 0 <= payload[name] <= 2**53 - 1
           for name in ('issued', 'expires')):
        raise CursorError()
    if not 0 < payload['expires'] - payload['issued'] <= 900:
        raise CursorError()


def encode(payload, *, secret):
    _shape(payload)
    raw = stable_json(payload).encode('utf-8')
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise CursorError()
    signature = hmac.new(_key(secret), b'external-fact-page-token@1\0' + raw,
                         hashlib.sha256).digest()
    token = _b64(raw) + '.' + _b64(signature)
    if len(token) > MAX_TOKEN_BYTES:
        raise CursorError()
    return token


def decode(token, *, secret, key_id, owner, source_id, query_id, verification_id, limit, now):
    try:
        if type(token) is not str or not 1 <= len(token) <= MAX_TOKEN_BYTES or not token.isascii():
            raise CursorError()
        parts = token.split('.')
        if len(parts) != 2:
            raise CursorError()
        raw, signature = _unb64(parts[0]), _unb64(parts[1])
        if len(raw) > MAX_PAYLOAD_BYTES or len(signature) != 32:
            raise CursorError()
        expected = hmac.new(_key(secret), b'external-fact-page-token@1\0' + raw,
                            hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise CursorError()
        payload = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(CursorError()))
        _shape(payload)
        if stable_json(payload).encode('utf-8') != raw:
            raise CursorError()
        expected_binding = {'key_id': key_id, 'owner': owner, 'source_id': source_id,
                            'query_id': query_id, 'verification_id': verification_id, 'limit': limit}
        if any(payload[name] != value for name, value in expected_binding.items()):
            raise CursorError()
        epoch = int(now.timestamp())
        if payload['issued'] > epoch:
            raise CursorError()
        if epoch >= payload['expires']:
            raise CursorError('expired')
        return payload
    except CursorError:
        raise
    except (ValueError, TypeError, OverflowError, UnicodeError, binascii.Error, RecursionError):
        raise CursorError() from None
