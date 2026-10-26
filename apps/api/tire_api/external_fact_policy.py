"""Bounded structure and applicability checks, with no I/O or authentication.

Unkeyed SHA-256 checks self-consistency only. ``expected_head`` is required input,
not proof of a holder, evidence, reviewer, latest revision, or genuine permission.
A future controlled store must supply the current head; clients must not select it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re


SCHEMA = "external-fact-policy@1"
PURPOSE = "external_structured_fact_read"
REASON_CODES = frozenset({
    "applicable", "chain_shape_invalid", "chain_length_invalid",
    "expected_head_invalid", "record_shape_invalid", "schema_invalid",
    "purpose_invalid", "identifier_invalid", "revision_invalid",
    "previous_digest_invalid", "state_invalid", "coverage_invalid",
    "observations_invalid", "observation_invalid", "field_keys_invalid",
    "rights_invalid", "review_invalid", "validity_invalid", "timestamp_invalid",
    "digest_invalid", "digest_mismatch", "chain_identity_mismatch",
    "revision_sequence_invalid", "previous_digest_mismatch", "review_order_invalid",
    "head_mismatch", "policy_invalid", "now_invalid", "state_not_approved",
    "not_yet_valid", "expired", "review_in_future", "review_outside_validity",
    "source_not_covered", "observation_not_covered", "fields_not_covered",
})
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_SNAPSHOT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HASH = re.compile(r"[0-9a-f]{64}")
_FIELD = re.compile(r"(?:identity|facts|evidence)\.[a-z][a-z0-9_]{0,79}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_RECORD_KEYS = frozenset({
    "schema", "purpose", "grant_id", "source_id", "revision", "previous_digest",
    "state", "coverage", "rights", "review", "validity", "digest",
})


class PolicyValidationError(ValueError):
    """Only a fixed safe reason code; never echo records or evidence references."""

    def __init__(self, reason: str):
        self.reason = reason if type(reason) is str and reason in REASON_CODES else "policy_invalid"
        super().__init__(self.reason)


@dataclass(frozen=True, slots=True)
class _Observation:
    snapshot_id: str
    raw_hash: str
    parser_version: str


@dataclass(frozen=True, slots=True)
class _Coverage:
    observations: tuple[_Observation, ...]
    field_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Rights:
    holder: str
    basis: str
    evidence_reference: str
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class _Review:
    reviewer: str
    reviewed_at: str


@dataclass(frozen=True, slots=True)
class _Validity:
    not_before: str
    not_after: str | None


@dataclass(frozen=True, slots=True)
class _Revision:
    schema: str
    purpose: str
    grant_id: str
    source_id: str
    revision: int
    previous_digest: str | None
    state: str
    coverage: _Coverage
    rights: _Rights
    review: _Review
    validity: _Validity
    digest: str


@dataclass(frozen=True, slots=True)
class ValidatedPolicy:
    """Immutable latest revision and selected head, without a trust assertion."""

    latest: _Revision
    head: str


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    status: str
    reason: str


def _fail(reason):
    raise PolicyValidationError(reason)


def _closed(value, keys, reason):
    if (type(value) is not dict or len(value) != len(keys)
            or any(type(key) is not str for key in value) or value.keys() != keys):
        _fail(reason)


def _text(value, maximum, reason):
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or value != value.strip() or not value.isprintable()):
        _fail(reason)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        _fail(reason)
    return value


def _pattern(value, pattern, reason):
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(reason)
    return value


def _timestamp(value):
    _pattern(value, _TIMESTAMP, "timestamp_invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("timestamp_invalid")


def _observation(value):
    _closed(value, {"snapshot_id", "raw_hash", "parser_version"}, "observation_invalid")
    return _Observation(
        _pattern(value["snapshot_id"], _SNAPSHOT_ID, "observation_invalid"),
        _pattern(value["raw_hash"], _HASH, "observation_invalid"),
        _text(value["parser_version"], 100, "observation_invalid"),
    )


def _fields(value):
    if type(value) is not list or not 1 <= len(value) <= 128:
        _fail("field_keys_invalid")
    for field in value:
        _pattern(field, _FIELD, "field_keys_invalid")
    if len(set(value)) != len(value):
        _fail("field_keys_invalid")
    return tuple(value)


def _record(value):
    """Check every shape and bound before canonical serialization."""
    _closed(value, _RECORD_KEYS, "record_shape_invalid")
    if type(value["schema"]) is not str or value["schema"] != SCHEMA:
        _fail("schema_invalid")
    if type(value["purpose"]) is not str or value["purpose"] != PURPOSE:
        _fail("purpose_invalid")
    grant = _pattern(value["grant_id"], _ID, "identifier_invalid")
    source = _pattern(value["source_id"], _ID, "identifier_invalid")
    revision = value["revision"]
    if type(revision) is not int or not 1 <= revision <= 256:
        _fail("revision_invalid")
    previous = value["previous_digest"]
    if revision == 1:
        if previous is not None:
            _fail("previous_digest_invalid")
    else:
        _pattern(previous, _HASH, "previous_digest_invalid")
    state = value["state"]
    if type(state) is not str or state not in {"pending", "approved", "restricted", "withdrawn"}:
        _fail("state_invalid")
    coverage = value["coverage"]
    _closed(coverage, {"observations", "field_keys"}, "coverage_invalid")
    observations = coverage["observations"]
    if type(observations) is not list or not 1 <= len(observations) <= 256:
        _fail("observations_invalid")
    observations = tuple(_observation(item) for item in observations)
    if len(set(observations)) != len(observations):
        _fail("observations_invalid")
    coverage = _Coverage(observations, _fields(coverage["field_keys"]))
    rights = value["rights"]
    _closed(rights, {"holder", "basis", "evidence_reference", "evidence_sha256"}, "rights_invalid")
    rights = _Rights(
        _text(rights["holder"], 160, "rights_invalid"),
        _text(rights["basis"], 1000, "rights_invalid"),
        _text(rights["evidence_reference"], 512, "rights_invalid"),
        _pattern(rights["evidence_sha256"], _HASH, "rights_invalid"),
    )
    review = value["review"]
    _closed(review, {"reviewer", "reviewed_at"}, "review_invalid")
    reviewer = _text(review["reviewer"], 160, "review_invalid")
    _timestamp(review["reviewed_at"])
    review = _Review(reviewer, review["reviewed_at"])
    validity = value["validity"]
    _closed(validity, {"not_before", "not_after"}, "validity_invalid")
    before = _timestamp(validity["not_before"])
    after = validity["not_after"]
    if after is not None and _timestamp(after) <= before:
        _fail("validity_invalid")
    validity = _Validity(validity["not_before"], after)
    digest = _pattern(value["digest"], _HASH, "digest_invalid")
    payload = {key: item for key, item in value.items() if key != "digest"}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != digest:
        _fail("digest_mismatch")
    return _Revision(SCHEMA, PURPOSE, grant, source, revision, previous, state,
                     coverage, rights, review, validity, digest)


def validate_revision_chain(records, *, expected_head) -> ValidatedPolicy:
    """Validate a complete bounded chain. The supplied head is not authentication.

    Inputs are exact built-in dict/list/string/int values; there is no coercion.
    Raises PolicyValidationError containing only a fixed reason code.
    """
    if type(records) is not list:
        _fail("chain_shape_invalid")
    if not 1 <= len(records) <= 256:
        _fail("chain_length_invalid")
    _pattern(expected_head, _HASH, "expected_head_invalid")
    previous = None
    for index, value in enumerate(records, 1):
        current = _record(value)
        if current.revision != index:
            _fail("revision_sequence_invalid")
        if previous is not None:
            if (current.grant_id, current.source_id) != (previous.grant_id, previous.source_id):
                _fail("chain_identity_mismatch")
            if current.previous_digest != previous.digest:
                _fail("previous_digest_mismatch")
            if current.review.reviewed_at < previous.review.reviewed_at:
                _fail("review_order_invalid")
        previous = current
    if previous.digest != expected_head:
        _fail("head_mismatch")
    return ValidatedPolicy(previous, expected_head)


def _checked_latest(policy):
    # Frozen dataclasses prevent ordinary mutation, but are not authenticity seals.
    # Recheck exact nested types and self-consistency if an object was forged or
    # damaged with object.__setattr__, without accepting mutable container aliases.
    if type(policy) is not ValidatedPolicy or type(policy.latest) is not _Revision:
        _fail("policy_invalid")
    latest = policy.latest
    if (type(latest.coverage) is not _Coverage
            or type(latest.coverage.observations) is not tuple
            or type(latest.coverage.field_keys) is not tuple
            or not 1 <= len(latest.coverage.observations) <= 256
            or not 1 <= len(latest.coverage.field_keys) <= 128
            or any(type(item) is not _Observation for item in latest.coverage.observations)
            or type(latest.rights) is not _Rights or type(latest.review) is not _Review
            or type(latest.validity) is not _Validity):
        _fail("policy_invalid")
    payload = {
        "schema": latest.schema, "purpose": latest.purpose,
        "grant_id": latest.grant_id, "source_id": latest.source_id,
        "revision": latest.revision, "previous_digest": latest.previous_digest,
        "state": latest.state,
        "coverage": {
            "observations": [{"snapshot_id": item.snapshot_id, "raw_hash": item.raw_hash,
                              "parser_version": item.parser_version}
                             for item in latest.coverage.observations],
            "field_keys": list(latest.coverage.field_keys),
        },
        "rights": {"holder": latest.rights.holder, "basis": latest.rights.basis,
                   "evidence_reference": latest.rights.evidence_reference,
                   "evidence_sha256": latest.rights.evidence_sha256},
        "review": {"reviewer": latest.review.reviewer, "reviewed_at": latest.review.reviewed_at},
        "validity": {"not_before": latest.validity.not_before, "not_after": latest.validity.not_after},
        "digest": latest.digest,
    }
    checked = _record(payload)
    _pattern(policy.head, _HASH, "policy_invalid")
    if policy.head != checked.digest:
        _fail("policy_invalid")
    return checked


def evaluate_applicability(policy, observation, requested_field_keys, *, now) -> PolicyDecision:
    """Return applicable/not_applicable/invalid, never actual legal approval.

    ``now`` must be an exact datetime with a standard UTC timezone. No clock is
    read. Opaque evidence references are neither opened nor verified here.
    """
    try:
        try:
            latest = _checked_latest(policy)
        except (PolicyValidationError, AttributeError, TypeError, ValueError):
            _fail("policy_invalid")
        _closed(observation, {"source_id", "snapshot_id", "raw_hash", "parser_version"},
                "observation_invalid")
        source = _pattern(observation["source_id"], _ID, "observation_invalid")
        selected = _observation({key: value for key, value in observation.items() if key != "source_id"})
        fields = _fields(requested_field_keys)
        if (type(now) is not datetime or type(now.tzinfo) is not timezone
                or now.utcoffset() != timedelta(0)):
            _fail("now_invalid")
        if latest.state != "approved":
            return PolicyDecision("not_applicable", "state_not_approved")
        if now < _timestamp(latest.review.reviewed_at):
            return PolicyDecision("not_applicable", "review_in_future")
        after = latest.validity.not_after
        if after is not None and _timestamp(latest.review.reviewed_at) > _timestamp(after):
            return PolicyDecision("not_applicable", "review_outside_validity")
        if now < _timestamp(latest.validity.not_before):
            return PolicyDecision("not_applicable", "not_yet_valid")
        if after is not None and now >= _timestamp(after):
            return PolicyDecision("not_applicable", "expired")
        if source != latest.source_id:
            return PolicyDecision("not_applicable", "source_not_covered")
        if selected not in latest.coverage.observations:
            return PolicyDecision("not_applicable", "observation_not_covered")
        if not set(fields).issubset(latest.coverage.field_keys):
            return PolicyDecision("not_applicable", "fields_not_covered")
        return PolicyDecision("applicable", "applicable")
    except PolicyValidationError as error:
        return PolicyDecision("invalid", error.reason)
