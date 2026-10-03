"""Real vehicle source plus explicit simulated garage entries in a temporary DB."""
import json
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.adapters import xiaomi
from tire_api.db import GarageRevision, GarageVehicle
from tire_api.main import create_app
from tire_api.vehicles import VehicleSnapshot


def main():
    with tempfile.TemporaryDirectory(prefix='tire-garage-acceptance-') as directory:
        app = create_app('sqlite:///' + (Path(directory) / 'garage.db').as_posix())
        with TestClient(app) as client:
            live = client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'never'})
            assert live.status_code == 200
            result = live.json()
            assert result['data_state'] == 'live', result.get('reason')
            fitment = next(row for row in result['fitments'] if row['availability'] == 'standard')
            source = result['provenance'][0]
            response = client.post('/v1/garage/from-fitment', json={'snapshot_id': source['snapshot_id'],
                'fitment_id': fitment['id'], 'nickname': '自动验收的模拟车辆，不代表用户实际持有'})
            assert response.status_code == 201
            car = response.json()
            assert car['basis'] == 'copied_fitment' and car['fitment_reference']['raw_hash'] == source['raw_hash']
            assert car['profile']['front']['size'] == fitment['front']['size']
            assert car['profile']['rear']['size'] == fitment['rear']['size']
            trim = next(row for row in result['trims'] if row['id'] == fitment['trim_id'])
            expected_year = trim.get('model_year') if trim.get('model_year') is not None else result['vehicle']['model_year']
            assert car['profile']['model_year'] == expected_year
            assert car['current_tires'] == {'front': None, 'rear': None}
            original_year = car['profile']['model_year']
            edited = client.put('/v1/garage/' + car['id'], json={'expected_revision': 1,
                'profile': {**car['profile'], 'nickname': '模拟编辑后的验收车辆'}})
            assert edited.status_code == 200 and edited.json()['basis'] == 'user_entry'
            for revision, action in [(2, 'archive'), (3, 'restore')]:
                response = client.post(f"/v1/garage/{car['id']}/state", json={'expected_revision': revision, 'action': action})
                assert response.status_code == 200 and response.json()['revision'] == revision + 1
            history = client.get(f"/v1/garage/{car['id']}?mode=history").json()
            assert len(history['history']) == 4
            assert history['fitment_reference']['raw_hash'] == source['raw_hash']
            with app.state.database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(VehicleSnapshot)) == 1
                assert db.scalar(select(func.count()).select_from(GarageVehicle)) == 1
                assert db.scalar(select(func.count()).select_from(GarageRevision)) == 4
            print(json.dumps({'status': 'passed', 'checks': [
                'real_current_vehicle_online_query', 'copy_exact_fitment_with_original_evidence',
                'unknown_year_preserved_no_inferred_current_tire', 'manual_edit_is_personal_record',
                'archive_restore_history_preserved', 'source_snapshot_not_modified'],
                'scope': 'Real official source; simulated personal garage entries only in temporary DB',
                'vehicle_id': result['vehicle_id'], 'front': fitment['front']['size'], 'rear': fitment['rear']['size'],
                'model_year': original_year, 'raw_hash': source['raw_hash']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
