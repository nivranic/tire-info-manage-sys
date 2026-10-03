"""Current identity annotations must not rewrite the old snapshot or user reference."""
from copy import deepcopy

from tire_api.curation import review_state
from tire_api.db import Snapshot, TireVariant
from tire_api.garage import tire_identities
from tire_api.lifecycle import lifecycle_review
from test_identity_migration import apply_current, database, seed_legacy


def test_dynamic_views_update_only_contract_metadata_after_proven_legacy_binding(database):
    with database.sessions() as db:
        seeded = seed_legacy(db, namespace='CAI')
        variant_id = seeded['variant_id']
        profile = {'front': {'current_variant_id': variant_id}, 'rear': {'current_variant_id': None}}
        old_identity = deepcopy(db.get(TireVariant, variant_id).identity)
        old_members = deepcopy(db.get(Snapshot, seeded['snapshot_id']).parsed_variants)
        assert 'product_code_type' not in old_identity
        for value in (lifecycle_review(db, variant_id), review_state(db, variant_id, 'fixture'),
                      tire_identities(db, [profile])[variant_id]):
            assert value['identity_contract']['state'] == 'legacy_unbound'
        apply_current(db)
        for value in (lifecycle_review(db, variant_id), review_state(db, variant_id, 'fixture'),
                      tire_identities(db, [profile])[variant_id]):
            assert value['identity_contract']['state'] == 'current'
            assert value['identity_contract']['current_identity']['product_code_type'] == 'CAI'
        assert db.get(TireVariant, variant_id).identity == old_identity
        assert db.get(Snapshot, seeded['snapshot_id']).parsed_variants == old_members
        assert profile['front']['current_variant_id'] == variant_id
