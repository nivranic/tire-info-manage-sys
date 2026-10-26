"""One owned fact observation over the existing external HTTP boundary.

The middleware's authentication/rate reservation is preliminary. Only the
injected reader's fresh transaction can authorize and project these facts.
"""
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .external_api import SAFE_HEADERS, SOURCE_ID, _queries, _scope, fail, unauthorized
from .external_fact_reader import ReaderError


MAX_RESPONSE_BYTES = 64 * 1024 + 256
_IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,64}')
_QUERIES = {'source_id', 'query_id', 'verification_id'}
_SERVICE_ERRORS = frozenset({
    'reader_backend_unsupported', 'reader_schema_required', 'reader_clock_invalid',
    'reader_storage_unavailable',
})


def _reader_error(error):
    if error.code == 'reader_unauthorized':
        unauthorized()
    if error.code == 'reader_scope_required':
        fail('external_scope_required', 403)
    if error.code in _SERVICE_ERRORS:
        fail('external_fact_service_unavailable', 503)
    if error.code == 'reader_query_invalid':
        fail('external_query_invalid', 422)
    if error.code == 'reader_cursor_invalid':
        fail('external_cursor_invalid', 422)
    if error.code == 'reader_cursor_expired':
        fail('external_fact_cursor_expired', 409)
    if error.code == 'reader_window_changed':
        fail('external_fact_window_changed', 409)
    # Do not disclose whether a private observation, mapping or grant exists.
    fail('external_fact_not_available', 404)


def register_external_fact_routes(app: FastAPI, reader=None):
    @app.get('/external/v1/tire-facts')
    def tire_facts(request: Request):
        if reader is None:
            fail('external_fact_service_unavailable', 503)
        try:
            credential = reader.capture_credential(request.headers.getlist('authorization'))
            outcome = reader.read_page(credential, query_pairs=tuple(request.query_params.multi_items()))
        except ReaderError as error:
            _reader_error(error)
        return Response(content=outcome.body, media_type='application/json', headers=SAFE_HEADERS)

    @app.get('/external/v1/tire-facts/{variant_id}')
    def tire_fact(variant_id: str, request: Request):
        # An early scope rejection is not the reader's authorization proof.
        _scope(request, 'facts:read')
        params = _queries(request, _QUERIES)
        if (params.keys() != _QUERIES or SOURCE_ID.fullmatch(params['source_id']) is None
                or _IDENTIFIER.fullmatch(variant_id) is None
                or any(_IDENTIFIER.fullmatch(params[key]) is None
                       for key in ('query_id', 'verification_id'))):
            fail('external_query_invalid', 422)
        if reader is None:
            fail('external_fact_service_unavailable', 503)
        try:
            credential = reader.capture_credential(request.headers.getlist('authorization'))
            outcome = reader.read_one(credential, source_id=params['source_id'],
                query_id=params['query_id'], verification_id=params['verification_id'],
                variant_id=variant_id)
        except ReaderError as error:
            _reader_error(error)
        response = JSONResponse(outcome.to_dict(), headers=SAFE_HEADERS)
        if len(response.body) > MAX_RESPONSE_BYTES:
            fail('external_fact_not_available', 404)
        return response
