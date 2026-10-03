"""Real Xiaomi baseline plus explicit parser-loss injection in a temporary DB."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from tire_api.adapters import xiaomi
from tire_api.main import create_app
from tire_api.vehicles import register_vehicle_routes


class ControlledAdapter:
    candidates = staticmethod(xiaomi.candidates)
    original = None
    inject = False

    async def fetch(self, vehicle_id, *, on_observation=None):
        if not self.inject:
            result = await xiaomi.fetch(vehicle_id, on_observation=on_observation)
            self.original = deepcopy(result)
            return result
        # Replay the real raw body, but deliberately drop one parsed trim.
        # This is a parser regression simulation, not a claimed upstream failure.
        result = deepcopy(self.original)
        removed = result['payload']['trims'].pop()
        result['payload']['fitments'] = [row for row in result['payload']['fitments'] if row['trim_id'] != removed['id']]
        result['parser_version'] += '+quality-injection'
        if on_observation:
            on_observation(result)
        return result


def main():
    with tempfile.TemporaryDirectory(prefix='tire-vehicle-quality-') as directory:
        app = create_app('sqlite:///' + (Path(directory) / 'quality.db').as_posix())
        adapter = ControlledAdapter()
        register_vehicle_routes(app, adapter)
        with TestClient(app) as client:
            path = f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments'
            accepted = client.post(path, json={'fallback_policy': 'never'}).json()
            assert accepted['data_state'] == 'live' and len(accepted['trims']) >= 2, accepted.get('reason')
            snapshot_id = accepted['provenance'][0]['snapshot_id']
            original = client.get('/v1/vehicle-evidence/' + snapshot_id).json()
            adapter.inject = True
            rejected = client.post(path, json={'fallback_policy': 'ask'}).json()
            assert rejected['reason'] == 'source_quality_quarantined' and rejected['vehicle'] is None and not rejected['fitments']
            row = client.get('/v1/quarantines?source_id=' + xiaomi.SOURCE_ID).json()['items'][0]
            evidence = client.get(row['evidence_path']).json()
            assert evidence['accepted'] is False and evidence['previous_snapshot_id'] == snapshot_id
            assert evidence['quality']['groups']['trims']['row_loss_ratio'] >= .3
            assert hashlib.sha256(evidence['body'].encode()).hexdigest() == evidence['raw_hash'] == original['raw_hash']
            consent = client.post('/v1/fallback-consents', json={'query_id': rejected['query_id'], 'decision': 'allow', 'scope': 'once'}).json()
            fallback = client.post(path, json={'fallback_policy': 'ask', 'consent_id': consent['id']}).json()
            assert fallback['data_state'] == 'local_snapshot' and fallback['fitments'] == accepted['fitments']
            assert fallback['provenance'] == accepted['provenance']
            assert client.get('/v1/vehicle-evidence/' + snapshot_id).json() == original
            source = next(row for row in client.get('/v1/source-health').json()['sources'] if row['source_id'] == xiaomi.SOURCE_ID)
            assert source['status'] == 'quarantined' and source['successes'] == 1 and source['quarantined_count'] == 1
            print(json.dumps({'status': 'passed', 'scope': 'Real Xiaomi baseline; explicit parser-loss replay in temporary DB',
                'trims': len(accepted['trims']), 'fitments': len(accepted['fitments']), 'raw_hash': original['raw_hash'],
                'checks': ['real_vehicle_baseline', 'injected_trim_loss_quarantined', 'raw_evidence_hash_preserved',
                           'no_unconsented_fitment_fallback', 'consent_uses_only_accepted_snapshot', 'vehicle_health_includes_quarantine']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
