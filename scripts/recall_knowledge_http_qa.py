"""Independent HTTP/SSE acceptance with synthetic recall/model and private storage only."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx
from pypdf import PdfReader

from golden_acceptance import save

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = '23T001000'


def require(value, code):
    if not value:
        raise AssertionError(code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(args.base == 'http://127.0.0.1:8003', 'owned_private_fixture_required')
    output = args.output.resolve()
    require(output.is_relative_to((ROOT / '.artifacts/recall-knowledge').resolve()), 'artifact_scope')
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'synthetic_recall_real_http_sse_reports',
        'normal_database_used': False, 'real_openai_calls': 0, 'checks': [], 'cases': []}
    owner = httpx.Client(base_url=args.base, timeout=20, trust_env=False)
    other = httpx.Client(base_url=args.base, timeout=20, trust_env=False)

    def call(path, body=None, *, status=200, key=None, client=owner):
        response = client.request('GET' if body is None else 'POST', path, json=body,
                                  headers={'Idempotency-Key': key} if key else {})
        allowed = (status,) if isinstance(status, int) else status
        require(response.status_code in allowed,
                f'http_{response.status_code}_{path}_{response.text[:250]}')
        return response.json()

    def check(name):
        report['checks'].append(name)
        save(output / 'report.json', report)
        print(json.dumps({'check': name}), flush=True)

    def configure(**body):
        return call('/fixture/config', body)

    def live(campaign=CAMPAIGN):
        return call('/v1/recalls/live-query', {'query': {'campaign_number': campaign}})

    def history(refs, **kwargs):
        return call('/v1/ai/evidence-packs', {'mode': 'history', 'references': refs}, **kwargs)

    def current(**extra):
        return call('/v1/ai/evidence-packs', {'mode': 'current', 'query_kind': 'recall_by_campaign',
            'source_id': 'nhtsa-us-recalls', 'query': {'campaign_number': CAMPAIGN}, **extra})

    def search(**filters):
        return call('/v1/knowledge/search', {'mode': 'history', 'text': '',
            'filters': {'kind': 'recall', 'campaign_number': CAMPAIGN, **filters}})

    def wait_for(path, predicate):
        deadline = time.monotonic() + 15
        while True:
            result = call(path)
            if predicate(result):
                return result
            require(time.monotonic() < deadline, 'wait_timeout_' + path)
            time.sleep(0.05)

    def detail(request_id):
        return '/v1/ai/analysis-streams/' + request_id + '?mode=history'

    def analyze(pack, *, streaming=False):
        payload = {'pack_id': pack['id'], 'question': '列出所选公告的可引用事实，不评估实物安全。',
                   'allow_external_processing': True}
        path = '/v1/ai/analysis-streams' if streaming else '/v1/ai/analyses'
        result = call(path, payload, key=str(uuid4()), status=(200, 201, 202))
        if streaming:
            request_id = result['analysis']['id']
            result = wait_for(detail(request_id), lambda row: row['execution']['terminal'])
        return result

    def answer_of(result):
        return result.get('analysis', result)

    def exports(saved):
        rows = {}
        for fmt in ('markdown', 'html', 'pdf'):
            value = call('/v1/reports/' + saved['id'] + '/exports', {'revision': 1, 'format': fmt}, status=201)
            value = value.get('export', value)
            response = owner.get(value['content_url'])
            require(response.status_code == 200 and len(response.content) == value['byte_count'], 'export_size')
            require(hashlib.sha256(response.content).hexdigest() == value['sha256'], 'export_hash')
            require(value['renderer_version'] == 'frozen-research-export@4', 'export_renderer')
            if fmt == 'pdf':
                text = '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(response.content)).pages)
            else:
                text = response.text
            require('not_assessed' in text and '首次观察' in text and '空响应' in text, 'export_boundary_' + fmt)
            if fmt == 'html':
                require('<script>window.recallKnowledgeCanary' not in text and '&lt;script&gt;' in text,
                        'export_html_canary_not_escaped')
            suffix = {'markdown': 'md', 'html': 'html', 'pdf': 'pdf'}[fmt]
            (output / ('frozen-report.' + suffix)).write_bytes(response.content)
            rows[fmt] = {'metadata': value, 'sha256': value['sha256']}
        return rows

    try:
        call('/fixture/entry')
        call('/fixture/entry?actor=other', client=other)
        initial = call('/fixture/state')
        require(initial['scope'] == 'synthetic_recall_knowledge_research' and
                not initial['normal_database_used'], 'wrong_fixture')
        report['initial'] = initial
        configure(source_mode='baseline', model_mode='facts')
        first = live()
        ref = first['analysis_reference']
        require(first['data_state'] == 'live' and len(first['records']) == 3 and ref['recall_revision_id'], 'seed')
        history([ref, ref], status=422)
        pack = history([ref])['pack']
        evidence = pack['evidence'][0]
        require(len(pack['evidence']) == 1 and evidence['record_count'] == 3 and len(pack['facts']) == 46,
                'complete_multiset_and_reference_dedup')
        require(len({row['record_key'] for row in evidence['record_scopes']}) == 3, 'duplicate_record_lost')
        require(pack['purpose'] == 'recall_research' and pack['recall_boundary']['applicability'] == 'not_assessed',
                'pack_boundary')
        history([{**ref, 'recall_revision_id': None}], status=409)
        configure(source_mode='same_content_new_raw')
        second = live()
        second_ref = second['analysis_reference']
        require(second_ref['snapshot_id'] != ref['snapshot_id'] and second_ref['recall_revision_id'] == ref['recall_revision_id'],
                'same_revision_new_snapshot')
        later = history([second_ref])['pack']['evidence'][0]
        require(later['revision_snapshot_id'] == evidence['revision_snapshot_id'] and later['snapshot_id'] == second_ref['snapshot_id'] and
                later['verified_at'] == second['verified_at'], 'snapshot_vs_revision_binding')
        call('/fixture/seal', {})
        check('three_records_duplicates_exact_revision_snapshot_and_no_history_refetch')

        all_products = search()
        require(all_products['total'] == 3, 'knowledge_record_count')
        require(search(brand='SYNTHETIC PAIR A', model='SYNTHETIC ALPHA')['total'] == 2, 'duplicate_product_count')
        require(search(brand='SYNTHETIC PAIR A', model='SYNTHETIC BETA')['total'] == 0, 'cross_record_brand_model')
        require(search(size='265/40R20')['total'] == 0 and search(product_code='unknown')['total'] == 0, 'missing_filter_ignored')
        require(search(campaign_number='23T999999')['total'] == 0, 'campaign_filter_ignored')
        idle = call('/fixture/state')
        require(idle['provider_calls'] == idle['sync_provider_calls'] == 0 and idle['counts']['embedding_requests'] == 0,
                'retrieval_triggered_provider')
        check('per_record_filters_multiset_exact_campaign_and_no_automatic_provider')

        configure(source_mode='not_modified')
        refreshed = current()
        require(refreshed['pack'] and refreshed['query_result']['data_state'] == 'live_verified_304', '304_not_online_verified')
        configure(source_mode='offline')
        outage = current()
        require(outage['pack'] is None and outage['query_result']['data_state'] == 'consent_required' and
                outage['query_result']['analysis_reference'] is None, 'outage_read_old_knowledge')
        denied = call('/v1/fallback-consents', {'query_id': outage['query_result']['query_id'],
            'decision': 'deny', 'scope': 'once'}, status=201)
        call('/v1/ai/evidence-packs', {'mode': 'current', 'query_kind': 'recall_by_campaign',
            'source_id': 'nhtsa-us-recalls', 'query': {'campaign_number': CAMPAIGN},
            'consent_id': denied['id']}, status=403)
        outage = current()
        grant = call('/v1/fallback-consents', {'query_id': outage['query_result']['query_id'],
            'decision': 'allow', 'scope': 'once'}, status=201)
        wrong = {'mode': 'current', 'query_kind': 'recall_by_campaign', 'source_id': 'nhtsa-us-recalls',
                 'query': {'campaign_number': '23T999999'}, 'consent_id': grant['id']}
        call('/v1/ai/evidence-packs', wrong, status=403)
        call('/v1/ai/evidence-packs', {**wrong, 'query': {'campaign_number': CAMPAIGN}}, status=403, client=other)
        fallback = current(consent_id=grant['id'])
        require(fallback['pack']['data_state'] == 'local_snapshot', 'once_consent_not_consumed')
        call('/v1/ai/evidence-packs', {**wrong, 'query': {'campaign_number': CAMPAIGN}}, status=409)
        check('online_304_outage_denial_wrong_session_campaign_and_one_use_consent')

        configure(source_mode='baseline', model_mode='facts')
        valid = analyze(pack)
        analysis = answer_of(valid)
        require(analysis['state'] == 'completed' and analysis['answer']['uncertainty'] == '' and
                analysis['answer']['recall_boundary'] == pack['recall_boundary'], 'sync_answer_boundary')
        saved = call('/v1/reports', {'mode': 'history', 'pack_id': pack['id'], 'analysis_id': analysis['id'],
            'title': '合成召回事实冻结验收', 'notes': '非真实召回建议'}, status=201, key=str(uuid4()))
        require(saved['body']['recall_boundary'] == pack['recall_boundary'] and
                saved['body']['evidence'][0]['verification_id'] == evidence['verification_id'], 'frozen_receipt_boundary')
        report['frozen'] = {'id': saved['id'], 'body_hash': saved['body_hash'], 'exports': exports(saved)}
        call('/v1/reports/' + saved['id'] + '?mode=history', status=404, client=other)
        check('explicit_sync_grounding_frozen_receipt_and_three_export_hashes_boundary_html_escape')

        tire = call('/v1/sources/michelin-us/live-query', {'query': {'model': 'Fixture Tire', 'size': '265/40R20'},
                    'fallback_policy': 'never'})
        tire_ref = {'kind': 'tire', 'snapshot_id': tire['provenance'][0]['snapshot_id'], 'variant_id': tire['variants'][0]['id']}
        history([tire_ref, ref], status=422)
        configure(source_mode='compact')
        compact = live()
        mixed = history([tire_ref, compact['analysis_reference']])['pack']
        require(mixed['purpose'] == 'recall_research' and len(mixed['evidence']) == 2, 'mixed_pack_weak_contract')
        for selected in (pack, mixed):
            for mode in ('unsafe_inference', 'unsafe_uncertainty', 'cross_record'):
                configure(model_mode=mode)
                result = analyze(selected)
                require(answer_of(result)['state'] != 'completed' and answer_of(result)['answer'] is None,
                        'unsafe_sync_accepted_' + mode)
                streamed = analyze(selected, streaming=True)
                request_id = streamed['analysis']['id']
                events = call('/v1/ai/analysis-streams/' + request_id + '/events')['items']
                require(streamed['analysis']['state'] != 'completed' and streamed['analysis']['answer'] is None and
                        not streamed['draft_claims'] and streamed['draft_uncertainty'] is None, 'unsafe_stream_accepted_' + mode)
                require('UNSAFE MODEL' not in json.dumps(events) and
                        not any(row['type'] == 'uncertainty_draft' for row in events), 'unsafe_early_text_leak')
                call('/v1/reports', {'mode': 'history', 'pack_id': selected['id'], 'analysis_id': request_id,
                    'title': '必须拒绝非法模型报告'}, status=409, key=str(uuid4()))
                report['cases'].append({'mixed': selected is mixed, 'mode': mode,
                    'error': streamed['analysis']['error_code'], 'events': [row['type'] for row in events]})
        check('sync_stream_uncertainty_first_and_cross_record_rejected_in_pure_and_mixed_packs')

        configure(model_mode='held')
        held_payload = {'pack_id': pack['id'], 'question': '合成流草稿验收', 'allow_external_processing': True}
        held = call('/v1/ai/analysis-streams', held_payload, key=str(uuid4()), status=(200, 202))
        request_id = held['analysis']['id']
        wait_for('/fixture/state', lambda row: row['holding_model'])
        pending = call(detail(request_id))
        require(pending['draft_claims'] and pending['analysis']['answer'] is None and
                pending['analysis']['pack']['recall_boundary'] == pack['recall_boundary'], 'held_draft_boundary')
        call('/fixture/release', {})
        done = wait_for(detail(request_id), lambda row: row['execution']['terminal'])
        require(done['analysis']['state'] == 'completed', 'held_stream_failed')
        configure(model_mode='empty_claims')
        no_claims = answer_of(analyze(pack, streaming=True))['answer']
        require(no_claims['claims'] == [] and no_claims['uncertainty'] == '' and no_claims['recall_boundary'], 'empty_claims_not_fixed_boundary')
        check('unbuffered_fragmented_draft_boundary_and_empty_claims_deterministic_answer')

        configure(source_mode='changed', model_mode='facts')
        changed = live()
        require(changed['analysis_reference']['recall_revision_id'] != ref['recall_revision_id'], 'changed_revision_not_appended')
        history([{**second_ref, 'recall_revision_id': changed['analysis_reference']['recall_revision_id']}], status=409)
        latest_content = search()['items']
        configure(source_mode='empty')
        empty = current()
        empty_pack = empty['pack']
        require(empty['query_result']['records'] == [] and empty_pack['evidence'][0]['recall_revision_id'] is None and
                len(empty_pack['facts']) == 4 and all(row['scope'] == 'observation' for row in empty_pack['facts']),
                'empty_online_reused_old_announcement')
        require('合成公告新修订' not in json.dumps(empty_pack, ensure_ascii=False), 'empty_pack_old_summary')
        newer = search()['items']
        for old_item in latest_content:
            preserved = next(row for row in newer if row['reference'] == old_item['reference'] and
                             row.get('recall', {}).get('record_key') == old_item.get('recall', {}).get('record_key'))
            require(old_item['verified_at'] == preserved['verified_at'], 'empty_refreshed_old_content_time')
        require(any(row.get('recall', {}).get('observation_kind') == 'empty' for row in newer), 'empty_observation_missing')
        unchanged = call('/v1/reports/' + saved['id'] + '?mode=history')
        require(unchanged['body_hash'] == saved['body_hash'] and unchanged['body'] == saved['body'], 'later_source_changed_frozen_report')
        for row in report['frozen']['exports'].values():
            response = owner.get(row['metadata']['content_url'])
            require(hashlib.sha256(response.content).hexdigest() == row['sha256'], 'later_source_changed_export')
        check('new_revision_and_empty_observation_keep_old_report_hash_date_bytes_and_content_time')

        final = call('/fixture/state')
        require(final['sealed_evidence_unchanged'] and final['external_network_attempts'] == final['real_parser_children'] == 0,
                'source_evidence_changed_or_fixture_escaped')
        require(final['counts']['recall_search_snapshots'] == final['counts']['recall_discovery_candidates'] ==
                final['counts']['embedding_requests'] == 0, 'implicit_discovery_or_vector')
        report.update(status='passed', final=final)
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:900])
        raise
    finally:
        save(output / 'report.json', report)
        owner.close()
        other.close()


if __name__ == '__main__':
    main()
