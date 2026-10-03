"""Pure frozen-capability checks; no Responses calls or credentials are used."""
import json

import pytest

from tire_api.ai_rule_contract import source_catalog, validate_draft


class CatalogRegistry:
    def __init__(self, **capability):
        self.capability = capability

    def sources(self):
        return [{'id': 'synthetic-size-source', 'name': 'Synthetic size source', 'region': 'US',
                 'homepage': 'https://fixture.invalid', 'status': 'ready',
                 'supported_models': ['Fixture Tire'], **self.capability}]


def proposal(size=None):
    return json.dumps({'proposal': {'name': 'Synthetic proposal', 'model': 'Fixture Tire',
        'size': size, 'interval_seconds': 21600, 'kinds': ['facts_changed'], 'fields': [],
        'technology': None}, 'summary': 'Synthetic validator input only',
        'unsupported_requirements': [], 'clarifications': []})


def test_required_size_is_frozen_and_only_true_changes_the_legacy_catalog_hash():
    legacy = source_catalog(None, CatalogRegistry(), 'synthetic-size-source')
    optional = source_catalog(None, CatalogRegistry(requires_size=False), 'synthetic-size-source')
    required = source_catalog(None, CatalogRegistry(requires_size=True), 'synthetic-size-source')
    assert optional == legacy and 'requires_size' not in optional['source']
    assert required['source']['requires_size'] is True
    assert required['catalog_hash'] != legacy['catalog_hash']


@pytest.mark.parametrize('size', [None, ''])
def test_required_size_missing_from_proposal_needs_clarification(size):
    pack = {**source_catalog(None, CatalogRegistry(requires_size=True), 'synthetic-size-source'),
            'instruction': '每6小时监控 Fixture Tire 参数变化'}
    draft = validate_draft(proposal(size), pack)
    assert not draft['can_apply'] and any('尺寸' in item for item in draft['clarifications'])
    assert draft['rule']['query']['size'] is None
    corrected = validate_draft(proposal('265/40ZR20'), pack)
    assert corrected['can_apply'] and corrected['clarifications'] == []
    assert corrected['rule']['query']['size'] == '265/40ZR20'


def test_old_frozen_catalog_without_flag_keeps_optional_size_semantics():
    pack = {**source_catalog(None, CatalogRegistry(), 'synthetic-size-source'),
            'instruction': '每6小时监控 Fixture Tire 参数变化'}
    before = json.dumps(pack, sort_keys=True)
    draft = validate_draft(proposal(), pack)
    assert draft['can_apply'] and draft['clarifications'] == []
    assert json.dumps(pack, sort_keys=True) == before
