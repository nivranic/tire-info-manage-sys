"""第50轮设备AI桥接：prepare 侧内部 DTO 与 canonical 化（圆桌纪要步骤1）。

内部接口不冻结 wire（device_ai_projection.py:10-11 原则；纪要 D15）：本模块只
定义 closed StrictModel、规范化 validator 与 canonical 请求摘要，冻结时仅替换
序列化层。无路由、无数据库、无网络、无归档访问。

三禁令落点（encoder-spec.md §7）：payload 组装禁止把 as_token_dto()/token_dto()
输出当 DeviceAIValue——本模块不产生任何 token 形状；业务值编码只在路由层经
device_ai_value_encoder.encode_value 完成。
"""
from hashlib import sha256
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, StrictInt, model_validator

from .domain import StrictModel, digest
from .object_store import MAX_OBJECT_BYTES

_HASH64 = re.compile(r"[0-9a-f]{64}\Z")
QUESTION_MIN_CODEPOINTS = 2
QUESTION_MAX_CODEPOINTS = 2000
SELECTOR_CAPACITY = 6


def canonical_uuid(value: str) -> str:
    """UUID canonical 小写规范化（纪要 D3/D6）。

    接受大写、花括号等输入拼写，输出恒为 str(UUID(...)) 的 canonical 小写连字符
    形态，使 request_hash 不受 UUID 大小写漂移影响（与 ai_analysis.py 的
    str(UUID(key)) 幂等键惯例同构）。
    """
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('必须是 UUID（服务端统一规范化为 canonical 小写）') from None


def require_hash64(value: str) -> str:
    """64 位小写十六进制摘要（fingerprint-spec：canonical 小写，拒绝大写/异长）。"""
    if type(value) is not str or _HASH64.fullmatch(value) is None:
        raise ValueError('必须是小写 64 位十六进制摘要')
    return value


def validate_question(value: str) -> str:
    """question 的 trim-once 与 2..2000 codepoint 计数的唯一落点（纪要 D3）。

    与既有 strip 的叠加关系（禁止双重 trim）：StrictModel（domain.py:48）配置
    str_strip_whitespace=True，pydantic 已在字段层按 Python str.strip() 的空白
    字符集恰好剥除一次首尾空白；本 validator 不再执行任何 strip，只对已剥除后
    的值按 Unicode codepoint（Python len() 即 codepoint 数，非 UTF-16 码元）计数
    校验 2..2000。内部空白保持原样（不折叠多重空白）；NFKC 等归一化被禁止，
    文本以剥除后的原样字节进入摘要（fingerprint-spec.md 第 5 节禁令）。
    """
    if not QUESTION_MIN_CODEPOINTS <= len(value) <= QUESTION_MAX_CODEPOINTS:
        raise ValueError(f'问题长度须在 {QUESTION_MIN_CODEPOINTS}..{QUESTION_MAX_CODEPOINTS}'
                         ' 个 Unicode codepoint 内（剥除首尾空白后计数）')
    return value


CanonicalUUID = Annotated[str, Field(max_length=64), AfterValidator(canonical_uuid)]
Hash64 = Annotated[str, AfterValidator(require_hash64)]
QuestionText = Annotated[str, AfterValidator(validate_question)]


def question_digest(text: str) -> str:
    """fingerprint-spec 第 5 节：裸 sha256(UTF-8 字节)，无 namespace、无 JSON 包装、不做 NFKC。

    输入必须已过 validate_question 所在模型层的 trim-once；submit 侧三重绑定
    digest(trim_once(question)) == preparation.question_sha256 == consent.question_sha256
    的摘要即此函数（本轮只定义语义，不实现 submit 校验）。
    """
    return sha256(text.encode('utf-8')).hexdigest()


class DeviceTireReference(StrictModel):
    """tire 域归档引用（P1-4a 前唯一开放域）。"""

    kind: Literal['tire']
    snapshot_id: str = Field(min_length=1, max_length=64)
    variant_id: str = Field(min_length=1, max_length=64)
    verification_id: str = Field(min_length=1, max_length=64)


class DeviceVehicleReference(StrictModel):
    """vehicle 域归档引用；形状=投影核 _reference 的 vehicle 消费集（无 variant_id）。"""

    kind: Literal['vehicle']
    snapshot_id: str = Field(min_length=1, max_length=64)
    verification_id: str = Field(min_length=1, max_length=64)


class DeviceRecallReference(StrictModel):
    """recall 域归档引用；recall_revision_id 显式可空（正式公告观察的冻结修订）。"""

    kind: Literal['recall']
    snapshot_id: str = Field(min_length=1, max_length=64)
    recall_revision_id: str | None = Field(default=None, min_length=1, max_length=64)
    verification_id: str = Field(min_length=1, max_length=64)


class DeviceRecallSearchReference(StrictModel):
    """recall_search 域归档引用（仅 offline-pack@2；schema 校验在投影核内）。"""

    kind: Literal['recall_search']
    snapshot_id: str = Field(min_length=1, max_length=64)
    verification_id: str = Field(min_length=1, max_length=64)


# 域判别并集（P1-4a）：tire/vehicle/recall/recall_search 四域放开；test_event 不进
# Literal——DTO 层即 422（N27 封闭集合），投影核对 test_event 亦恒拒（双保险）。
DeviceReference = Annotated[DeviceTireReference | DeviceVehicleReference | DeviceRecallReference
                            | DeviceRecallSearchReference, Field(discriminator='kind')]


class DeviceSelector(StrictModel):
    """请求 selector；形状与投影核 _select 消费集一致（成员级语义校验仍在核内）。"""

    kind: Literal['tire', 'vehicle', 'recall', 'recall_search']
    member_key: Hash64
    document_id: str | None = Field(default=None, min_length=1, max_length=200)
    record_index: StrictInt | None = Field(default=None, ge=0, le=3999)
    reference: DeviceReference

    @model_validator(mode='after')
    def selector_shape(self):
        if self.kind != self.reference.kind:
            raise ValueError('selector kind 与引用 kind 必须一致')
        if self.document_id is None and self.record_index is not None:
            raise ValueError('缺少 document_id 时不能携带 record_index')
        # 投影核 _select 对 tire/vehicle 恒要求 record_index 为 None（整观察域），
        # 在 DTO 层前置同规则使违规形状 fail-closed 422 而非进入重算。
        if self.kind in ('tire', 'vehicle') and self.record_index is not None:
            raise ValueError(f'{self.kind} selector 不携带 record_index（投影核恒要求 None）')
        return self


class DeviceAIPrepareRequest(StrictModel):
    """metadata-only prepare 请求（纪要路由清单 #1）。

    只携带归档定位期望值、selector、期望投影摘要与问题摘要：question 明文只在
    submit 出现（proposal L158），prepare 仅存 question_sha256。业务数值不出现在
    本 DTO（bounded 元数据整数除外），canonical_request_hash 因此不受数值形状漂移
    影响。
    """

    package_id: str = Field(min_length=1, max_length=64)
    expected_sha256: Hash64
    expected_byte_count: StrictInt = Field(ge=1, le=MAX_OBJECT_BYTES)
    expected_schema: Literal['offline-pack@1', 'offline-pack@2']
    expected_owner_scope_id: Hash64
    selectors: list[DeviceSelector] = Field(min_length=1, max_length=SELECTOR_CAPACITY)
    # P1-4a：模式集合与投影核 SUPPORTED 模式对齐（test_event 的
    # complete_event_context 不进 Literal——test_event 域未开放，N27）。
    projection_mode: Literal['single_observation', 'frozen_decision_closure', 'complete_observation',
                             'complete_formal_observation', 'candidate_page_context'] = 'single_observation'
    approved_closure: list[DeviceSelector] | None = Field(default=None, max_length=SELECTOR_CAPACITY)
    expected_projection_sha256: Hash64
    question_sha256: Hash64
    host_receipt_id: CanonicalUUID
    intent_id: CanonicalUUID

    @model_validator(mode='after')
    def closure_shape(self):
        keys = [item.member_key for item in self.selectors]
        if len(set(keys)) != len(keys):
            raise ValueError('selector 不能重复指向同一成员')
        if self.projection_mode == 'frozen_decision_closure':
            if not self.approved_closure:
                raise ValueError('frozen_decision_closure 模式必须显式提供 approved_closure（精确相等清单）')
            # D5（decoder-spec 2.6）：闭包清单 member_key 唯一——与 selectors 同一
            # 围栏，四端 decoder 层同语义（Rust assert 同构）。
            closure_keys = [item.member_key for item in self.approved_closure]
            if len(set(closure_keys)) != len(closure_keys):
                raise ValueError('approved_closure 不能重复指向同一成员')
        elif self.approved_closure is not None:
            raise ValueError('仅 frozen_decision_closure 模式允许 approved_closure')
        return self


class ProviderConsent(StrictModel):
    """submit 侧 Provider 同意回显的六元组（纪要 D2；本轮仅定义形状，不实现复算）。

    全部字段只是幂等比对材料与审计输入，绝不构成授权依据：submit 事务内必须用
    DB/config 权威值（pack.fingerprint、preparation.device_context_fingerprint、
    preparation.question_sha256、configured_model() 当前值与服务端重算的 sanitized
    policy 指纹）复算并比对六元组。provider_consent_hash 列同理。
    """

    expected_pack_fingerprint: Hash64
    expected_device_context_fingerprint: Hash64
    question_sha256: Hash64
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=120)
    expected_provider_policy_fingerprint: Hash64


class DeviceSubmission(StrictModel):
    """AnalysisRequest 的 device_submission 子对象（纪要 D8；本轮仅定义形状）。

    prepare_id/host_receipt_id/device_context_fingerprint 三字段在 submit 事务内
    与按 ai_pack_id 反查所得 preparation 逐字段等值比对（回显等值断言）；actor 一律
    取 request.state.session_id，任何 DTO 不得携带 actor 字段。
    """

    prepare_id: str = Field(min_length=1, max_length=64)
    host_receipt_id: CanonicalUUID
    device_context_fingerprint: Hash64
    provider_consent: ProviderConsent


def canonical_request_hash(payload: StrictModel) -> str:
    """closed DTO 规范化形态的 canonical 请求摘要（纪要 D6）。

    stable_json 语义（sort_keys 消除字段序漂移）；UUID 已由 validator 强制
    canonical 小写；DTO 中不出现业务数值——三者共同杜绝字段序/大小写/数值形状
    漂移导致的误 409 或异义命中重放。replay 命中只比对摘要，绝不改写行。
    """
    return digest(payload.model_dump())
