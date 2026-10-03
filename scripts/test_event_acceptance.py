"""Small manually transcribed ADAC facts observed 2026-09-27; no article mirroring.

This is historical acceptance input, NOT an automatic fetcher or current online data.
Only temporary databases are used. Recheck the cited page before relying on the values.
"""
from pathlib import Path
import tempfile
import json
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tire_api.main import create_app
from tire_api.db import FactVersion, Snapshot, TireVariant

SOURCE_URL = 'https://www.adac.de/rund-ums-fahrzeug/ausstattung-technik-zubehoer/reifen/reifentest/sommerreifen/225-50-r17-2026/'


def sample():
    # Three numeric facts, not the original table; ranks are not inferred from order.
    rows = [('continental', 'Continental', 'PremiumContact 7', '1.9', '1,9'),
            ('pirelli', 'Pirelli', 'Cinturato (C3)', '2.2', '2,2'),
            ('goodyear', 'Goodyear', 'EfficientGrip Performance 2', '2.3', '2,3')]
    return {'event': {'title': 'ADAC 2026 夏季胎 225/50 R17 · 公开评分选录', 'organization': 'ADAC',
        'relationship': 'independent', 'publication_date': '2026-02-24', 'source_url': SOURCE_URL,
        'rights_basis': '公开页面少量数值及短定位，用于本地技术验证；不保存全文/图表。商用转载许可未核实。',
        'tested_size': '225/50R17', 'vehicle': 'Audi A4（原文 Testfahrzeug）', 'surface': None,
        'conditions': '2026 夏季胎横评，16 款；总评包含行驶安全 70% 与环境 30%，还存在降级规则。这里只录 ADAC 总评分，不是制动距离。温度未在本次选录中确认；不迁移到其他尺寸、载重级别或测试场次。',
        'coverage': 'selected_results', 'reported_participants': 16,
        'participants': [{'key': key, 'brand': brand, 'model': model} for key, brand, model, _, _ in rows],
        'metrics': [{'key': 'adac_overall', 'label': 'ADAC Urteil 总评分', 'unit': 'ADAC 评分',
                     'protocol': '来源总评，保留原评分与方法边界，不自行加权或推算名次。', 'direction': 'lower'}],
        'measurements': [{'participant_key': key, 'metric_key': 'adac_overall', 'raw_value': value,
                          'evidence_span': f'{brand} {model}: {original}',
                          'evidence_locator': 'Ergebnisse Sommerreifen 225/50 R17 (2026) → ADAC Urteil'}
                         for key, brand, model, value, original in rows]},
        'operator': 'Codex 来源核对（2026-09-27）', 'reason': '浏览器直接读取官方页后的少量手工转录；仅临时库验收，不代表自动在线来源已接入。'}


def main():
    with tempfile.TemporaryDirectory(prefix='tire-test-events-') as directory:
        url = 'sqlite:///' + (Path(directory) / 'events.db').as_posix()
        app = create_app(url)
        with TestClient(app) as client:
            response = client.post('/v1/test-events', json=sample())
            assert response.status_code == 201
            row = response.json()
            request = {'expected_revision': 1, 'participant_ids': [p['id'] for p in row['participants']], 'metric_keys': ['adac_overall']}
            comparison = client.post(f'/v1/test-events/{row["id"]}/compare?mode=history', json=request).json()
            assert [m['raw_value'] for m in comparison['measurements']] == ['1.9', '2.2', '2.3']
            assert all(m['source_rank'] is None for m in comparison['measurements'])
            assert comparison['verification_status'] == 'unverified' and comparison['verified_at'] is None
            with app.state.database.sessions() as db:
                assert all(db.scalar(select(func.count()).select_from(model)) == 0 for model in (Snapshot, TireVariant, FactVersion))
        with TestClient(create_app(url)) as client:
            restored = client.get(f'/v1/test-events/{row["id"]}?mode=history').json()
            assert restored['fingerprint'] == row['fingerprint'] and restored['event'] == row['event']
        print(json.dumps({'status': 'passed', 'scope': '2026-09-27 manual public-page transcription in temporary DB',
            'source_url': SOURCE_URL, 'fingerprint': row['fingerprint'], 'checks': [
                'three_cited_numeric_facts', 'same_event_comparison', 'no_inferred_ranks',
                'explicit_unverified_history', 'no_product_fact_or_sku_creation', 'restart_preserves_event']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
