"""Safety Gate exact alert evidence, shared AI entrypoints and frozen boundaries."""
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from test_safety_gate import context, run


def prepare(client, result, alert_id=None):
    return client.post('/v1/ai/evidence-packs', json={'mode':'history','references':[{
        'kind':'safety_gate','snapshot_id':result['provenance'][0]['snapshot_id'],
        'alert_id':alert_id or result['document']['alerts'][0]['alert_id']}]})


def test_selected_official_alert_enters_pack_with_frozen_scope(context):
    client, _, _ = context
    result = run(client)
    response = prepare(client, result)
    assert response.status_code == 200
    pack = response.json()['pack']
    assert pack['data_state'] == 'local_snapshot'
    assert pack['purpose'] == 'safety_gate_research'
    assert pack['safety_gate_boundary']['applicability'] == 'not_assessed'
    assert len(pack['evidence']) == 1
    evidence = pack['evidence'][0]
    assert evidence['source_id'] == 'eu-safety-gate' and evidence['alert_id'] == '900001'
    assert evidence['raw_hash'] == result['provenance'][0]['raw_hash']
    assert evidence['snapshot_id'] == result['provenance'][0]['snapshot_id']
    assert all(fact['domain'] == 'safety_gate' and fact['record_key'] == '900001' for fact in pack['facts'])
    assert any(fact['value'] is None for fact in pack['facts'])


@pytest.fixture
def ai_case(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_safety_gate import FixtureAdapter, FixtureRegistry
    from tire_api import ai_analysis
    from tire_api.ai_gateway import OpenAIConfig
    from tire_api.main import create_app
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '0')
    monkeypatch.setattr(ai_analysis,'configured_model',lambda:OpenAIConfig(model='synthetic-safety-gate',api_key='synthetic-never-live',allow_private=True))
    class Model:
        calls = 0
        mutate = None
        def answer(self, body):
            self.calls += 1
            payload=json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
            fact=payload['facts'][0]
            result={'claims':[{'type':'fact','text':'','fact_ids':[fact['id']],'evidence_ids':[fact['evidence_id']]}],'uncertainty':''}
            if self.mutate:self.mutate(result,payload)
            return json.dumps(result)
        async def generate(self, config, body):
            return {'text':self.answer(body),'error':None,'usage':{'input_tokens':20,'output_tokens':10,'total_tokens':30},'provider_response_id':'synthetic_sg'}
        async def stream(self, config, body, on_text):
            output=self.answer(body)
            for part in (output[:20],output[20:]):await on_text(part)
            return {'text':output,'error':None,'usage':{'input_tokens':20,'output_tokens':10,'total_tokens':30},'provider_response_id':'synthetic_sg_stream'}
    app = create_app('sqlite:///' + (tmp_path / 'safety-ai.db').as_posix(), FixtureRegistry())
    model, adapter = Model(), FixtureAdapter()
    # Lifespan binds the stream supervisor to this adapter. Install both
    # synthetic adapters before startup so sync and stream use the same model.
    app.state.ai_adapter = model
    app.state.safety_gate_adapter = adapter
    with TestClient(app) as client:
        yield client, adapter, app.state.database, model


def pack_for(client):
    response=prepare(client,run(client))
    assert response.status_code==200
    return response.json()['pack']


def analyze(client, pack, **changes):
    return client.post('/v1/ai/analyses',headers={'Idempotency-Key':str(uuid4())},json={
        'pack_id':pack['id'],'question':'整理所选历史告警的官方原文','allow_external_processing':True,**changes})


def test_current_query_and_single_use_fallback_preserve_ai_audience(ai_case):
    client,adapter,_,model=ai_case
    from test_safety_gate import QUERY
    payload={'mode':'current','query_kind':'safety_gate_report','source_id':'eu-safety-gate','query':QUERY,'alert_ids':['900001']}
    live=client.post('/v1/ai/evidence-packs',json=payload)
    assert live.status_code==200 and live.json()['pack']['data_state']=='live'
    adapter.offline=True
    failed=client.post('/v1/ai/evidence-packs',json=payload).json()
    assert failed['pack'] is None and failed['query_result']['data_state']=='consent_required'
    approval=client.post('/v1/fallback-consents',json={'query_id':failed['query_result']['query_id'],'decision':'allow','scope':'once'}).json()
    recovered=client.post('/v1/ai/evidence-packs',json={**payload,'consent_id':approval['id']})
    assert recovered.status_code==200 and recovered.json()['pack']['data_state']=='local_snapshot'
    assert recovered.json()['pack']['consent_id']==approval['id']
    assert client.post('/v1/ai/evidence-packs',json={**payload,'consent_id':approval['id']}).status_code in {403,409}
    assert model.calls==0


@pytest.mark.parametrize('mutation',[
    lambda p:p['facts'][0].update(text='Unbound prose'),
    lambda p:p['facts'].pop(),
    lambda p:p['facts'][0].update(record_key='other'),
    lambda p:p['evidence'][0].update(source_id='nhtsa-us-recalls'),
    lambda p:p['evidence'][0].update(region='US'),
    lambda p:p['evidence'][0].update(alert_id='0'),
    lambda p:p['evidence'][0].update(parser_identity={'bad':True}),
    lambda p:p['safety_gate_boundary'].update(applicability='safe'),
])
def test_frozen_contract_rejects_tampered_material(context, mutation):
    from tire_api.ai_safety_gate_contract import validate_payload
    client,_,_=context
    pack=pack_for(client)
    mutation(pack)
    with pytest.raises(ValueError):validate_payload(pack)


def test_no_model_call_without_explicit_external_consent_or_for_current_question(ai_case):
    client,_,_,model=ai_case
    pack=pack_for(client)
    assert analyze(client,pack,allow_external_processing=False).status_code==422
    assert analyze(client,pack,question='当前最新是否还有风险').status_code==409
    assert model.calls==0


def test_normal_sync_and_stream_render_server_facts_only(ai_case):
    from test_ai_stream_api import accept,until
    client,_,_,model=ai_case
    pack=pack_for(client)
    value=analyze(client,pack)
    assert value.status_code==200 and value.json()['state']=='completed'
    answer=value.json()['answer']
    assert answer['claims'][0]['text']==pack['facts'][0]['text']
    assert answer['safety_gate_boundary']['applicability']=='not_assessed'
    accepted=accept(client,pack)
    assert accepted.status_code==202
    done=until(client,accepted.json()['analysis']['id'],lambda row:row['execution']['terminal'])
    assert done['analysis']['state']=='completed'
    assert done['analysis']['answer']['claims'][0]['text']==pack['facts'][0]['text']
    assert model.calls==2


@pytest.mark.parametrize('change',['inference','whitespace','uncertainty'])
def test_model_cannot_write_prose_or_infer_safety(ai_case, change):
    client,_,_,model=ai_case
    pack=pack_for(client)
    def mutate(answer,_payload):
        if change=='inference':answer['claims'][0].update(type='inference',text='safe')
        elif change=='whitespace':answer['claims'][0]['text']=' '
        else:answer['uncertainty']=' '
    model.mutate=mutate
    result=analyze(client,pack).json()
    assert result['state']=='failed' and result['error_code']=='ai_grounding_validation_failed'
    assert result['answer'] is None


def test_dispatch_rechecks_original_after_pack_creation(ai_case):
    client,_,database,model=ai_case
    pack=pack_for(client)
    with database.engine.begin() as db:
        db.execute(text('UPDATE safety_gate_snapshots SET body=:body'),{'body':'tampered'})
    result=analyze(client,pack).json()
    assert result['state']=='failed' and result['error_code']=='ai_grounding_validation_failed'
    assert model.calls==0 and result['usage']['total_tokens']==0


def test_report_exports_frozen_contract_after_original_changes(ai_case):
    from test_reports import save,export
    client,_,database,_=ai_case
    pack=pack_for(client);analysis=analyze(client,pack).json()
    saved=save(client,pack,analysis['id'])
    assert saved.status_code==201
    report=saved.json()
    first,body=export(client,report)
    assert first['renderer_version']=='frozen-research-export@6'
    assert 'Safety Gate' in body.decode() and '适用性' in body.decode()
    with database.engine.begin() as db:
        db.execute(text('UPDATE safety_gate_snapshots SET body=:body'),{'body':'changed after frozen report'})
    second,restored=export(client,report)
    assert second['sha256']==first['sha256'] and restored==body
    assert export(client,report,'html')[1].startswith(b'<!doctype html>')


def test_two_alert_scopes_cannot_be_combined_into_one_claim(context):
    from tire_api.ai_analysis import grounded_answer
    from tire_api.ai_safety_gate_contract import validate_payload
    from tire_api.safety_gate_ai_evidence import canonical_facts
    from tire_api.domain import digest
    client,_,_=context
    payload=pack_for(client)
    second=deepcopy(payload['evidence'][0]);second.update(id='e2',alert_id='900002',case_number='SR/00002/26',
        alert_source_url='https://ec.europa.eu/safety-gate-alerts/screen/webReport/alertDetail/900002')
    second['label']='Safety Gate '+second['report_reference']+' · '+second['case_number']
    second['alert_values'].update(alert_id=second['alert_id'],case_number=second['case_number'])
    second['content_hash']=digest(second['alert_values'])
    facts=[{'id':'second_'+str(i),'evidence_id':'e2',**f} for i,f in enumerate(canonical_facts(second))]
    payload['evidence'].append(second);payload['facts'].extend(facts)
    assert validate_payload(payload)
    answer={'claims':[{'type':'fact','text':'','fact_ids':[payload['facts'][0]['id'],facts[0]['id']],'evidence_ids':['e1','e2']}],'uncertainty':''}
    with pytest.raises(ValueError,match='cross_safety_gate_scope_not_allowed'):
        grounded_answer(json.dumps(answer),SimpleNamespace(payload=payload,data_state='local_snapshot'))
