"""步骤1 纯单元向量：canonical UUID/字段序同 hash、异义异 hash、trim-once/NFKC。

无 app、无 DB、无归档。trim/计数语义按 Unicode codepoint（Python len()），跨 Host
向量锚定 fingerprint-spec.md 第 5 节禁令（无 namespace、无 JSON 包装、不做 NFKC）。
"""
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tire_api.device_ai import (DeviceAIPrepareRequest, DeviceSelector, DeviceSubmission,
                                ProviderConsent, QuestionText, canonical_request_hash,
                                question_digest)
from tire_api.domain import StrictModel

RECEIPT = '0AB9E6C8-1F2D-4A3E-9C0B-7D6E5F4A3B2C'
RECEIPT_CANONICAL = '0ab9e6c8-1f2d-4a3e-9c0b-7d6e5f4a3b2c'


class Probe(StrictModel):
    """本地探针模型：QuestionText 的 trim-once/计数落点不依赖 submit 侧模型扩展。"""

    question: QuestionText


def base_body(**overrides):
    value = {
        'package_id': 'synthetic-package',
        'expected_sha256': 'a' * 64,
        'expected_byte_count': 100,
        'expected_schema': 'offline-pack@2',
        'expected_owner_scope_id': 'b' * 64,
        'selectors': [{'kind': 'tire', 'member_key': 'c' * 64, 'document_id': 'doc-1',
                       'record_index': None,
                       'reference': {'kind': 'tire', 'snapshot_id': 'snap', 'variant_id': 'var',
                                     'verification_id': 'verif'}}],
        'projection_mode': 'single_observation',
        'expected_projection_sha256': 'd' * 64,
        'question_sha256': 'e' * 64,
        'host_receipt_id': RECEIPT,
        'intent_id': str(uuid4()),
    }
    value.update(overrides)
    return value


def submission_body(**overrides):
    value = {
        'prepare_id': 'prepare-1',
        'host_receipt_id': RECEIPT,
        'device_context_fingerprint': 'f' * 64,
        'provider_consent': {
            'expected_pack_fingerprint': '1' * 64,
            'expected_device_context_fingerprint': '2' * 64,
            'question_sha256': '3' * 64,
            'provider': 'openai_responses',
            'model': 'synthetic-model',
            'expected_provider_policy_fingerprint': '4' * 64,
        },
    }
    value.update(overrides)
    return value


def test_field_order_and_uuid_case_drift_produce_the_same_request_hash():
    body = base_body()
    first = DeviceAIPrepareRequest.model_validate(body)
    reordered = DeviceAIPrepareRequest.model_validate(dict(reversed(list(body.items()))))
    assert canonical_request_hash(first) == canonical_request_hash(reordered)
    assert first.host_receipt_id == RECEIPT_CANONICAL
    # 大写/小写 UUID：同值同 hash（validator 已规范化为 canonical 小写）。
    assert canonical_request_hash(first) == canonical_request_hash(
        DeviceAIPrepareRequest.model_validate(base_body(**{**body, 'host_receipt_id': RECEIPT_CANONICAL})))


@pytest.mark.parametrize('change', [
    {'question_sha256': 'f' * 64},
    {'expected_projection_sha256': 'f' * 64},
    {'package_id': 'another-package'},
    {'expected_byte_count': 101},
    {'host_receipt_id': str(uuid4())},
])
def test_semantically_different_bodies_get_different_hashes(change):
    first = DeviceAIPrepareRequest.model_validate(base_body())
    other = DeviceAIPrepareRequest.model_validate(base_body(**change))
    assert canonical_request_hash(first) != canonical_request_hash(other)


@pytest.mark.parametrize('field,value', [
    ('expected_sha256', 'A' * 64), ('expected_sha256', 'a' * 63),
    ('expected_owner_scope_id', 'g'), ('expected_projection_sha256', ''),
    ('question_sha256', 'E' * 64),
    ('host_receipt_id', 'not-a-uuid'), ('intent_id', 12345),
    ('expected_byte_count', 0), ('expected_byte_count', '100'),
    ('package_id', ''), ('expected_schema', 'offline-pack@3'),
])
def test_closed_schema_rejects_noncanonical_values(field, value):
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(**{field: value}))


def test_unknown_fields_are_rejected_and_selector_shape_is_closed():
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(origin='device_history'))
    # P1-4a 后 tire/vehicle/recall/recall_search 四域放开；test_event 不进 Literal（N27）。
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(selectors=[
            {'kind': 'test_event', 'member_key': 'c' * 64, 'document_id': None, 'record_index': None,
             'reference': {'kind': 'test_event', 'event_id': 'event', 'event_revision': 1}}]))
    # 引用形状按域封闭：vehicle 引用不收 variant_id 等别域字段。
    with pytest.raises(ValidationError):
        DeviceSelector.model_validate({'kind': 'vehicle', 'member_key': 'c' * 64, 'document_id': None,
                                       'record_index': None,
                                       'reference': {'kind': 'vehicle', 'snapshot_id': 'snap',
                                                     'variant_id': None, 'verification_id': 'verif'}})
    with pytest.raises(ValidationError):
        DeviceSelector.model_validate({'kind': 'tire', 'member_key': 'C' * 64, 'document_id': None,
                                       'record_index': None,
                                       'reference': {'kind': 'tire', 'snapshot_id': 's',
                                                     'variant_id': 'v', 'verification_id': 'w'}})
    with pytest.raises(ValidationError):
        DeviceSelector.model_validate({'kind': 'tire', 'member_key': 'c' * 64, 'document_id': None,
                                       'record_index': 3,
                                       'reference': {'kind': 'tire', 'snapshot_id': 's',
                                                     'variant_id': 'v', 'verification_id': 'w'}})
    with pytest.raises(ValidationError):
        DeviceSelector.model_validate({'kind': 'vehicle', 'member_key': 'c' * 64, 'document_id': 'doc',
                                       'record_index': 1,
                                       'reference': {'kind': 'vehicle', 'snapshot_id': 's',
                                                     'verification_id': 'w'}})


def test_four_domain_selector_references_are_accepted_with_matching_modes():
    """四域 selector 各自合法形态与 projection_mode 组合（mode↔kind 语义校验在投影核）。"""
    vehicle = {'kind': 'vehicle', 'member_key': 'c' * 64, 'document_id': None, 'record_index': None,
               'reference': {'kind': 'vehicle', 'snapshot_id': 'snap', 'verification_id': 'verif'}}
    recall = {'kind': 'recall', 'member_key': 'd' * 64, 'document_id': 'doc', 'record_index': 0,
              'reference': {'kind': 'recall', 'snapshot_id': 'snap',
                            'recall_revision_id': 'rev', 'verification_id': 'verif'}}
    search = {'kind': 'recall_search', 'member_key': 'e' * 64, 'document_id': None, 'record_index': None,
              'reference': {'kind': 'recall_search', 'snapshot_id': 'snap', 'verification_id': 'verif'}}
    for mode, selector in (('complete_observation', vehicle),
                           ('complete_formal_observation', recall),
                           ('candidate_page_context', search)):
        value = DeviceAIPrepareRequest.model_validate(
            base_body(selectors=[selector], projection_mode=mode))
        assert value.selectors[0].kind == selector['kind']
    # recall_revision_id 显式可空（空公告观察）。
    empty = DeviceSelector.model_validate({**recall, 'record_index': None, 'document_id': None,
                                           'reference': {'kind': 'recall', 'snapshot_id': 'snap',
                                                         'recall_revision_id': None,
                                                         'verification_id': 'verif'}})
    assert empty.reference.recall_revision_id is None


def test_duplicate_member_keys_are_rejected():
    selector = base_body()['selectors'][0]
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(selectors=[selector, dict(selector)]))


@pytest.mark.parametrize('closure', [
    {'approved_closure': []},
    {'projection_mode': 'frozen_decision_closure'},
    {'projection_mode': 'frozen_decision_closure', 'approved_closure': None},
])
def test_closure_mode_rules_are_enforced(closure):
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(**closure))


def test_duplicate_closure_member_keys_are_rejected():
    """D5（decoder-spec 2.6）：approved_closure 条目 member_key 唯一——与 selectors 同围栏。"""
    selector = base_body()['selectors'][0]
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(
            projection_mode='frozen_decision_closure', approved_closure=[selector, dict(selector)]))


def test_selector_capacity_six_is_enforced():
    """M9（decoder-spec 第 3 节）：SELECTOR_CAPACITY=6——第 7 条 selector 在 DTO 层 422。"""
    selector = base_body()['selectors'][0]
    seven = [dict(selector, member_key=format(index, '064x')) for index in range(7)]
    assert len({item['member_key'] for item in seven}) == 7  # 仅触发容量围栏
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(selectors=seven))


def test_include_context_ids_is_absent_from_prepare_wire():
    """M4（decoder-spec 第 3 节）：prepare wire 无 include_context_ids——出现即 extra=forbid 422
    （三 Host 侧"必须为空"gate 的服务端对端：字段不进冻结字段表）。"""
    with pytest.raises(ValidationError):
        DeviceAIPrepareRequest.model_validate(base_body(include_context_ids=['archive-1']))


def test_submission_and_consent_shapes_canonicalize_uuids_and_hash_stably():
    first = DeviceSubmission.model_validate(submission_body())
    upper = DeviceSubmission.model_validate(submission_body(host_receipt_id=RECEIPT))
    assert first.host_receipt_id == upper.host_receipt_id == RECEIPT_CANONICAL
    assert canonical_request_hash(first) == canonical_request_hash(upper)
    assert set(first.provider_consent.model_dump()) == {
        'expected_pack_fingerprint', 'expected_device_context_fingerprint', 'question_sha256',
        'provider', 'model', 'expected_provider_policy_fingerprint'}
    with pytest.raises(ValidationError):
        DeviceSubmission.model_validate(submission_body(actor_session_id='client-supplied-actor'))
    with pytest.raises(ValidationError):
        ProviderConsent.model_validate({'expected_pack_fingerprint': 'A' * 64})


def test_question_trim_once_never_double_trims_and_keeps_internal_whitespace():
    # 模型层 str_strip_whitespace=True 已恰好剥除一次首尾空白；validator 不再 strip。
    assert Probe(question='  历史问题  ').question == '历史问题'
    assert Probe(question='\u3000历史问题\u000b').question == '历史问题'
    # 多重内部空白不折叠；多重首尾空白也只整体剥除一次边界。
    assert Probe(question='问题  内容').question == '问题  内容'
    assert Probe(question='   问题   内容   ').question == '问题   内容'
    assert question_digest('问题  内容') != question_digest('问题 内容')


def test_question_is_never_nfkc_normalized():
    ligature, expanded = 'ﬃ 轮胎历史', 'ffi 轮胎历史'
    assert Probe(question=ligature).question == ligature
    assert question_digest(ligature) != question_digest(expanded)
    fullwidth, ascii_digits = '２０００ 年', '2000 年'
    assert Probe(question=fullwidth).question == fullwidth
    assert question_digest(fullwidth) != question_digest(ascii_digits)


def test_question_digest_is_bare_utf8_sha256_without_wrapping():
    text = 'P225 这条轮胎的历史参数如何解读？'
    assert question_digest(text) == sha256(text.encode('utf-8')).hexdigest()
    assert question_digest(text) != sha256(('"' + text + '"').encode('utf-8')).hexdigest()
    assert question_digest(text) != sha256(text.lower().encode('utf-8')).hexdigest()
    assert question_digest(text) != sha256(('device-ai@1\x00' + text).encode('utf-8')).hexdigest()


@pytest.mark.parametrize('question', ['问题', 'ab', 'x' * 2000, '𐀀' * 2000])
def test_question_codepoint_bounds_are_accepted(question):
    assert Probe(question=question).question == question


@pytest.mark.parametrize('question', ['a', 'x' * 2001, '𐀀' * 2001, '  a  ', '\u3000a\u3000', '\u000ba\u000c'])
def test_question_out_of_bounds_after_single_trim_is_rejected(question):
    with pytest.raises(ValidationError):
        Probe(question=question)
