"""Pure cursor/budget boundaries; private ASGI scenarios have a separate fixture."""
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import unittest

from tire_api.external_fact_cursor import CursorError, SCHEMA, ROUTE, commitment, decode, encode
from tire_api.external_fact_page_budget import PageCapacityError, PageReadBudget


class FactPageCoreTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
        self.secret = 'a' * 64
        self.payload = {'schema': SCHEMA, 'key_id': 'b' * 32, 'owner': 'c' * 64, 'route': ROUTE,
            'source_id': 'source', 'query_id': 'query', 'verification_id': 'verification', 'limit': 20,
            'issued': int(self.now.timestamp()), 'expires': int(self.now.timestamp()) + 900,
            'window': 'd' * 64, 'context': 'e' * 64, 'after': 'variant'}

    def decode(self, token, **changes):
        options = {name: self.payload[name] for name in ('key_id', 'owner', 'source_id', 'query_id',
                                                       'verification_id', 'limit')}
        options.update(secret=self.secret, now=self.now)
        options.update(changes)
        return decode(token, **options)

    def sign_raw(self, raw):
        b64 = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
        signature = hmac.new(bytes.fromhex(self.secret), b'external-fact-page-token@1\0' + raw,
                             hashlib.sha256).digest()
        return b64(raw) + '.' + b64(signature)

    def test_01_dedicated_signature_and_repeatable_fixed_expiry(self):
        token = encode(self.payload, secret=self.secret)
        self.assertEqual(self.decode(token), self.payload)
        self.assertEqual(self.decode(token, now=self.now + timedelta(seconds=899)), self.payload)
        with self.assertRaises(CursorError) as error:
            self.decode(token, now=self.now + timedelta(seconds=900))
        self.assertEqual(error.exception.code, 'expired')
        self.assertNotEqual(commitment(self.secret, 'owner', 'same'),
                            commitment(self.secret, 'window', 'same'))

    def test_02_foreign_binding_and_bad_signature_are_invalid_before_expiry(self):
        token = encode(self.payload, secret=self.secret)
        for changes in ({'source_id': 'other'}, {'query_id': 'other'}, {'verification_id': 'other'},
                        {'limit': 1}, {'owner': '0' * 64}, {'key_id': '0' * 32}, {'secret': '0' * 64}):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(CursorError) as error:
                    self.decode(token, now=self.now + timedelta(days=1), **changes)
                self.assertEqual(error.exception.code, 'invalid')

    def test_03_signed_duplicate_noncanonical_and_nested_payloads_rejected(self):
        raw = json.dumps(self.payload, sort_keys=True, separators=(',', ':')).encode()
        for bad in (b'{"schema":"duplicate",' + raw[1:], b' ' + raw,
                    raw.replace(b'"limit":20', b'"limit":true'),
                    raw.replace(b'"after":"variant"', b'"after":[]')):
            with self.subTest(raw_length=len(bad)):
                with self.assertRaises(CursorError):
                    self.decode(self.sign_raw(bad))

    def test_04_future_issued_and_strict_ascii_full_strings(self):
        for name, value in (('after', 'variant\n'), ('source_id', '\uff33ource'), ('limit', True),
                            ('issued', 1.0), ('expires', 2**53)):
            with self.subTest(field=name):
                with self.assertRaises(CursorError):
                    encode(self.payload | {name: value}, secret=self.secret)
        future = self.payload | {'issued': self.payload['issued'] + 1, 'expires': self.payload['expires'] + 1}
        with self.assertRaises(CursorError) as error:
            self.decode(encode(future, secret=self.secret))
        self.assertEqual(error.exception.code, 'invalid')

    def test_05_width_is_rejected_before_child_expansion(self):
        budget = PageReadBudget()
        with self.assertRaises(PageCapacityError):
            budget.json([None] * (budget.MAX_JSON_NODES + 1))
        self.assertEqual(budget.json_nodes, 1)
        with self.assertRaises(PageCapacityError):
            PageReadBudget().json({'value': '\ud800'})

    def test_06_cumulative_depth_nodes_and_projection_work(self):
        budget = PageReadBudget()
        budget.json([None] * (budget.MAX_JSON_NODES - 2))
        budget.json(None)
        with self.assertRaises(PageCapacityError):
            budget.json(None)
        nested = None
        for _ in range(17):
            nested = [nested]
        with self.assertRaises(PageCapacityError):
            PageReadBudget().json(nested)
        budget = PageReadBudget()
        for _ in range(budget.MAX_VALUES):
            budget.projection()
        with self.assertRaises(PageCapacityError):
            budget.projection()

    def test_07_shared_rows_and_storage_have_exact_inclusive_limits(self):
        budget = PageReadBudget()
        budget.reserve_rows(budget.MAX_ROWS)
        budget.storage(budget.MAX_STORAGE_BYTES)
        with self.assertRaises(PageCapacityError):
            budget.reserve_rows(1)
        with self.assertRaises(PageCapacityError):
            budget.storage(1)


if __name__ == '__main__':
    unittest.main()
