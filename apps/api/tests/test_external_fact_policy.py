"""Synthetic stdlib-only vectors; never evidence of genuine permission.

Load exactly the sibling source file, bypassing application/test initialization.
"""

import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


_TARGET = Path(__file__).resolve().parents[1] / "tire_api" / "external_fact_policy.py"
_SPEC = importlib.util.spec_from_file_location("_external_fact_policy_core_under_test", _TARGET)
policy_core = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = policy_core
exec(compile(_TARGET.read_bytes(), str(_TARGET), "exec"), vars(policy_core))

# Manually frozen canonical bytes; SHA-256 also computed independently with .NET
# SHA256.HashData in PowerShell 7. No product serializer/hash helper is imported.
CANONICAL_BYTES = (
    b'{"coverage":{"field_keys":["facts.load","identity.code"],"observations":['
    b'{"parser_version":"parser-1","raw_hash":"11111111111111111111111111111111'
    b'11111111111111111111111111111111","snapshot_id":"snap-1"}]},'
    b'"grant_id":"grant-1","previous_digest":null,"purpose":"external_structured_fact_read",'
    b'"review":{"reviewed_at":"2026-10-20T00:00:00Z","reviewer":"Fixture reviewer"},'
    b'"revision":1,"rights":{"basis":"Synthetic test basis","evidence_reference":"opaque:fixture",'
    b'"evidence_sha256":"2222222222222222222222222222222222222222222222222222222222222222",'
    b'"holder":"Fixture holder"},"schema":"external-fact-policy@1","source_id":"source-1",'
    b'"state":"approved","validity":{"not_after":"2026-10-22T00:00:00Z",'
    b'"not_before":"2026-10-20T00:00:00Z"}}'
)
EXPECTED_DIGEST = "1584e5a35a43027ed66d5d0e382b3f5dcba5ef12b3aeb0bf28fd50de26ea39c5"
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
OBSERVATION = {
    "source_id": "source-1", "snapshot_id": "snap-1",
    "raw_hash": "1" * 64, "parser_version": "parser-1",
}
OBSERVED_REASON_COUNTS = {reason: 0 for reason in policy_core.REASON_CODES}


def _base():
    value = json.loads(CANONICAL_BYTES)
    value["digest"] = EXPECTED_DIGEST
    return value


def _seal(value):
    """Independent input-vector builder, deliberately separate from product code."""
    payload = {key: item for key, item in value.items() if key != "digest"}
    value["digest"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return value


def _chain(states):
    result = []
    for index, state in enumerate(states, 1):
        value = _base()
        value["revision"] = index
        value["previous_digest"] = result[-1]["digest"] if result else None
        value["state"] = state
        result.append(_seal(value))
    return result


class ExternalFactPolicyTests(unittest.TestCase):
    def _policy(self, value=None):
        value = _base() if value is None else value
        return policy_core.validate_revision_chain([value], expected_head=value["digest"])

    def _invalid(self, records, reason, *, head=None):
        if head is None:
            head = records[-1]["digest"] if type(records) is list and records else EXPECTED_DIGEST
        with self.assertRaises(policy_core.PolicyValidationError) as caught:
            policy_core.validate_revision_chain(records, expected_head=head)
        self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(str(caught.exception), reason)
        OBSERVED_REASON_COUNTS[reason] += 1

    def _decision(self, selected=None, observation=None, fields=None, now=NOW,
                  status="applicable", reason="applicable"):
        decision = policy_core.evaluate_applicability(
            self._policy() if selected is None else selected,
            copy.deepcopy(OBSERVATION) if observation is None else observation,
            ["facts.load"] if fields is None else fields, now=now,
        )
        self.assertEqual((decision.status, decision.reason), (status, reason))
        OBSERVED_REASON_COUNTS[reason] += 1
        return decision

    def test_frozen_independent_canonical_vector(self):
        self.assertEqual(hashlib.sha256(CANONICAL_BYTES).hexdigest(), EXPECTED_DIGEST)
        payload = json.loads(CANONICAL_BYTES)
        independently_encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual(independently_encoded, CANONICAL_BYTES)
        selected = self._policy()
        self.assertEqual(selected.head, EXPECTED_DIGEST)
        self._decision(selected, fields=["facts.load", "identity.code"])
        self.assertEqual(self._decision(selected), self._decision(selected))

    def test_two_revisions_and_no_cached_previous_approval(self):
        records = _chain(["pending", "approved"])
        selected = policy_core.validate_revision_chain(records, expected_head=records[-1]["digest"])
        self.assertEqual(selected.latest.revision, 2)
        self._decision(selected)
        records = _chain(["approved", "withdrawn"])
        selected = policy_core.validate_revision_chain(records, expected_head=records[-1]["digest"])
        self._decision(selected, status="not_applicable", reason="state_not_approved")
        self._decision(self._policy())

    def test_all_nonapproved_states_and_unknown_state(self):
        for state in ("pending", "restricted", "withdrawn"):
            with self.subTest(state=state):
                value = _base()
                value["state"] = state
                self._decision(self._policy(_seal(value)), status="not_applicable", reason="state_not_approved")
        value = _base()
        value["state"] = "APPROVED"
        self._invalid([_seal(value)], "state_invalid")

    def test_exact_time_window_boundaries(self):
        self._decision(now=datetime(2026, 10, 20, tzinfo=timezone.utc))
        self._decision(now=datetime(2026, 10, 21, 23, 59, 59, tzinfo=timezone.utc))
        self._decision(now=datetime(2026, 10, 22, tzinfo=timezone.utc),
                       status="not_applicable", reason="expired")
        self._decision(now=datetime(2026, 10, 19, tzinfo=timezone.utc),
                       status="not_applicable", reason="review_in_future")
        value = _base()
        value["validity"]["not_before"] = "2026-10-21T01:00:00Z"
        self._decision(self._policy(_seal(value)), status="not_applicable", reason="not_yet_valid")
        value = _base()
        value["validity"]["not_after"] = None
        self._decision(self._policy(_seal(value)), now=datetime(2099, 1, 1, tzinfo=timezone.utc))
        value = _base()
        value["review"]["reviewed_at"] = "2026-10-23T00:00:00Z"
        self._decision(self._policy(_seal(value)), now=datetime(2026, 10, 24, tzinfo=timezone.utc),
                       status="not_applicable", reason="review_outside_validity")

    def test_now_must_be_explicit_standard_utc_datetime(self):
        for now in (None, NOW.replace(tzinfo=None), "2026-10-21T00:00:00Z", 0,
                    NOW.astimezone(timezone(timedelta(hours=1)))):
            with self.subTest(kind=type(now).__name__):
                self._decision(now=now, status="invalid", reason="now_invalid")
        with self.assertRaises(TypeError):
            policy_core.evaluate_applicability(self._policy(), OBSERVATION, ["facts.load"])

    def test_timestamp_spellings_and_calendar_validity(self):
        bad = ("2026-13-20T00:00:00Z", "2026-02-30T00:00:00Z", "2026-10-20T24:00:00Z",
               "2026-10-20T00:00:60Z", "2026-10-20T00:00:00", "2026-10-20T00:00:00+00:00",
               "2026-10-20T00:00:00.0Z", "2026-10-20t00:00:00z", "0000-01-01T00:00:00Z")
        for timestamp in bad:
            for group, key in (("review", "reviewed_at"), ("validity", "not_before"),
                               ("validity", "not_after")):
                with self.subTest(group=group, key=key, timestamp=timestamp):
                    value = _base()
                    value[group][key] = timestamp
                    self._invalid([_seal(value)], "timestamp_invalid")
        value = _base()
        value["validity"]["not_after"] = value["validity"]["not_before"]
        self._invalid([_seal(value)], "validity_invalid")

    def test_each_observation_component_is_exact(self):
        for key, replacement, reason in (
            ("source_id", "source-2", "source_not_covered"),
            ("snapshot_id", "snap-2", "observation_not_covered"),
            ("raw_hash", "3" * 64, "observation_not_covered"),
            ("parser_version", "parser-2", "observation_not_covered"),
        ):
            with self.subTest(key=key):
                observation = dict(OBSERVATION)
                observation[key] = replacement
                self._decision(observation=observation, status="not_applicable", reason=reason)

    def test_observations_are_triples_not_a_cartesian_product(self):
        value = _base()
        value["coverage"]["observations"].append({
            "snapshot_id": "snap-2", "raw_hash": "3" * 64, "parser_version": "parser-2",
        })
        selected = self._policy(_seal(value))
        for key, replacement in (("snapshot_id", "snap-2"), ("raw_hash", "3" * 64),
                                 ("parser_version", "parser-2")):
            observation = dict(OBSERVATION)
            observation[key] = replacement
            self._decision(selected, observation, status="not_applicable", reason="observation_not_covered")
        observation = {"source_id": "source-1", **value["coverage"]["observations"][1]}
        self._decision(selected, observation)

    def test_fields_require_complete_exact_coverage(self):
        self._decision(fields=["identity.code"])
        for fields in (["facts.load_extra"], ["facts.load", "evidence.code"], ["facts.alias"]):
            self._decision(fields=fields, status="not_applicable", reason="fields_not_covered")
        for fields in ([], ["facts.*"], ["Facts.load"], ["facts.Load"], ["facts.load", "facts.load"],
                       ["facts."], ["facts. load"], ["facts.0load"], ["facts.load "],
                       ("facts.load",), "facts.load", [True]):
            self._decision(fields=fields, status="invalid", reason="field_keys_invalid")

    def test_observation_closed_shape_and_strict_types(self):
        for key, replacement in (("snapshot_id", 1), ("raw_hash", True), ("raw_hash", "A" * 64),
                                 ("parser_version", " parser-1"), ("source_id", "source/1")):
            observation = dict(OBSERVATION)
            observation[key] = replacement
            self._decision(observation=observation, status="invalid", reason="observation_invalid")
        for observation in ({}, {**OBSERVATION, "extra": 1}, list(OBSERVATION)):
            self._decision(observation=observation, status="invalid", reason="observation_invalid")

    def test_chain_shape_head_and_capacity(self):
        self._invalid((), "chain_shape_invalid")
        self._invalid([], "chain_length_invalid")
        self._invalid([_base()] * 257, "chain_length_invalid")
        for head in ("", "A" * 64, 1, False):
            self._invalid([_base()], "expected_head_invalid", head=head)
        with self.assertRaises(policy_core.PolicyValidationError) as caught:
            policy_core.validate_revision_chain([_base()], expected_head=None)
        self.assertEqual(caught.exception.reason, "expected_head_invalid")
        OBSERVED_REASON_COUNTS["expected_head_invalid"] += 1
        with self.assertRaises(TypeError):
            policy_core.validate_revision_chain([_base()])
        self._invalid([_base()], "head_mismatch", head="0" * 64)
        chain = _chain(["approved"] * 256)
        selected = policy_core.validate_revision_chain(chain, expected_head=chain[-1]["digest"])
        self.assertEqual(selected.latest.revision, 256)
        self._decision(selected)

    def test_revision_types_sequence_and_missing_middle(self):
        for revision in (True, False, 0, -1, 257, 1.0, "1"):
            value = _base()
            value["revision"] = revision
            self._invalid([_seal(value)], "revision_invalid")
        chain = _chain(["approved"] * 3)
        self._invalid([chain[0], chain[2]], "revision_sequence_invalid")
        self._invalid([chain[1], chain[0]], "revision_sequence_invalid")
        self._invalid([chain[0], chain[0]], "revision_sequence_invalid")
        value = _base()
        value["revision"] = 2
        value["previous_digest"] = EXPECTED_DIGEST
        self._invalid([_seal(value)], "revision_sequence_invalid")

    def test_previous_digest_and_review_order(self):
        value = _base()
        value["previous_digest"] = EXPECTED_DIGEST
        self._invalid([_seal(value)], "previous_digest_invalid")
        for previous in (None, "A" * 64, True):
            chain = _chain(["approved", "approved"])
            chain[1]["previous_digest"] = previous
            _seal(chain[1])
            self._invalid(chain, "previous_digest_invalid")
        chain = _chain(["approved", "approved"])
        chain[1]["previous_digest"] = "0" * 64
        _seal(chain[1])
        self._invalid(chain, "previous_digest_mismatch")
        chain = _chain(["approved", "approved"])
        chain[1]["review"]["reviewed_at"] = "2026-10-19T23:59:59Z"
        _seal(chain[1])
        self._invalid(chain, "review_order_invalid")

    def test_chain_identity_and_fixed_schema_purpose(self):
        for key in ("grant_id", "source_id"):
            chain = _chain(["approved", "approved"])
            chain[1][key] += "-other"
            _seal(chain[1])
            self._invalid(chain, "chain_identity_mismatch")
        for key, replacement, reason in (("purpose", "store_original", "purpose_invalid"),
                                         ("schema", "external-fact-policy@2", "schema_invalid")):
            chain = _chain(["approved", "approved"])
            chain[1][key] = replacement
            _seal(chain[1])
            self._invalid(chain, reason)

    def test_unknown_and_missing_keys_at_each_level(self):
        for group, reason in ((None, "record_shape_invalid"), ("coverage", "coverage_invalid"),
                              ("rights", "rights_invalid"), ("review", "review_invalid"),
                              ("validity", "validity_invalid"), ("observation", "observation_invalid")):
            for change in ("extra", "missing"):
                value = _base()
                container = (value if group is None else value["coverage"]["observations"][0]
                             if group == "observation" else value[group])
                if change == "extra":
                    container["unknown"] = "synthetic"
                else:
                    del container[next(iter(container))]
                self._invalid([_seal(value)], reason)
        value = _base()
        value[1] = "synthetic"
        self._invalid([value], "record_shape_invalid")

    def test_hashes_are_strict_lowercase_and_cover_all_payload(self):
        for group, key, reason in ((None, "digest", "digest_invalid"),
                                   ("rights", "evidence_sha256", "rights_invalid"),
                                   ("observation", "raw_hash", "observation_invalid")):
            for replacement in (None, True, 0, "A" * 64, "a" * 63, "a" * 65):
                value = _base()
                container = (value if group is None else value["coverage"]["observations"][0]
                             if group == "observation" else value[group])
                container[key] = replacement
                if key != "digest":
                    _seal(value)
                self._invalid([value], reason, head=EXPECTED_DIGEST)
        mutations = (
            lambda value: value.update(grant_id="other"),
            lambda value: value.update(source_id="other"),
            lambda value: value.update(state="withdrawn"),
            lambda value: value["rights"].update(basis="Changed synthetic basis"),
            lambda value: value["review"].update(reviewer="Other reviewer"),
            lambda value: value["validity"].update(not_after=None),
            lambda value: value["coverage"]["field_keys"].reverse(),
            lambda value: value["coverage"]["observations"][0].update(parser_version="other"),
        )
        for mutate in mutations:
            value = _base()
            mutate(value)
            self._invalid([value], "digest_mismatch")

    def test_text_bounds_unicode_controls_and_no_coercion(self):
        for group, key, maximum, reason in (("rights", "holder", 160, "rights_invalid"),
                                           ("rights", "basis", 1000, "rights_invalid"),
                                           ("rights", "evidence_reference", 512, "rights_invalid"),
                                           ("review", "reviewer", 160, "review_invalid"),
                                           ("observation", "parser_version", 100, "observation_invalid")):
            for replacement in ("", " leading", "trailing ", "a\x00b", "a\x7fb", "a\x85b",
                                "a\u200bb", "a\ud800b", "a\uffffb", "x" * (maximum + 1),
                                True, 1, float("nan"), float("inf")):
                value = _base()
                container = value["coverage"]["observations"][0] if group == "observation" else value[group]
                container[key] = replacement
                # These invalid types/text must fail before serialization, including NaN.
                self._invalid([value], reason)
            value = _base()
            container = value["coverage"]["observations"][0] if group == "observation" else value[group]
            container[key] = "审" * maximum
            self._decision(self._policy(_seal(value)),
                           observation={**OBSERVATION, "parser_version": "审" * maximum}
                           if group == "observation" else OBSERVATION)
        for key, maximum in (("grant_id", 80), ("source_id", 80)):
            for replacement in ("a" * (maximum + 1), "id/path", "标识", " id", "id ", True):
                value = _base()
                value[key] = replacement
                self._invalid([_seal(value)], "identifier_invalid")

    def test_coverage_duplicates_shapes_and_limits(self):
        for observations in ([], [_base()["coverage"]["observations"][0]] * 257,
                             [_base()["coverage"]["observations"][0]] * 2, (), None):
            value = _base()
            value["coverage"]["observations"] = observations
            self._invalid([_seal(value)], "observations_invalid")
        for fields in ([], ["facts.load"] * 2, ["facts.f" + str(i) for i in range(129)],
                       ["facts." + "x" * 81], ["facts.*"], ["Facts.load"], None):
            value = _base()
            value["coverage"]["field_keys"] = fields
            self._invalid([_seal(value)], "field_keys_invalid")
        value = _base()
        value["coverage"]["observations"] = [
            {"snapshot_id": "s" + str(i), "raw_hash": "1" * 64, "parser_version": "parser-1"}
            for i in range(256)
        ]
        value["coverage"]["field_keys"] = ["facts.f" + str(i) for i in range(127)] + ["facts." + "x" * 80]
        selected = self._policy(_seal(value))
        self._decision(selected, {**OBSERVATION, "snapshot_id": "s255"}, ["facts." + "x" * 80])

    def test_no_input_mutation_or_mutable_aliases(self):
        records = [_base()]
        original = copy.deepcopy(records)
        selected = policy_core.validate_revision_chain(records, expected_head=EXPECTED_DIGEST)
        observation = dict(OBSERVATION)
        fields = ["facts.load"]
        decision = self._decision(selected, observation, fields)
        self.assertEqual(records, original)
        self.assertEqual(observation, OBSERVATION)
        self.assertEqual(fields, ["facts.load"])
        records[0]["coverage"]["field_keys"].clear()
        records[0]["coverage"]["observations"][0]["parser_version"] = "changed"
        records[0]["rights"]["basis"] = "changed"
        records.clear()
        fields.clear()
        observation.clear()
        self.assertEqual(self._decision(selected), decision)
        for item, attribute, replacement in ((selected, "head", "0" * 64),
                                              (selected.latest, "state", "withdrawn"),
                                              (selected.latest.coverage, "field_keys", ()),
                                              (decision, "status", "invalid")):
            with self.assertRaises(FrozenInstanceError):
                setattr(item, attribute, replacement)

    def test_damaged_policy_is_invalid_without_traceback_or_echo(self):
        for damage in (
            lambda selected: object.__setattr__(selected, "head", "0" * 64),
            lambda selected: object.__setattr__(selected.latest, "state", "withdrawn"),
            lambda selected: object.__setattr__(selected.latest.coverage, "field_keys", ["facts.load"]),
            lambda selected: object.__setattr__(selected.latest.coverage, "field_keys", ("facts.load",) * 129),
            lambda selected: object.__setattr__(selected.latest.coverage, "observations",
                                                selected.latest.coverage.observations * 257),
            lambda selected: object.__setattr__(selected.latest.rights, "basis", "\ud800"),
            lambda selected: object.__delattr__(selected.latest.review, "reviewer"),
        ):
            selected = self._policy()
            damage(selected)
            self._decision(selected, status="invalid", reason="policy_invalid")
        self._decision({}, status="invalid", reason="policy_invalid")

    def test_recomputed_fabrication_only_demonstrates_self_consistency(self):
        value = _base()
        value["rights"]["holder"] = "Another synthetic holder"
        value["rights"]["basis"] = "No actual permission is demonstrated"
        selected = self._policy(_seal(value))
        self.assertNotEqual(selected.head, EXPECTED_DIGEST)
        self._decision(selected)
        # Supplying both fabricated records and their recomputed head can pass.
        # Actual evidence/reviewer identity and the current trusted head are G1b.
        self._invalid([value], "head_mismatch", head=EXPECTED_DIGEST)

    def test_errors_never_echo_arbitrary_reason(self):
        self.assertEqual(str(policy_core.PolicyValidationError("opaque:private-input")), "policy_invalid")


if __name__ == "__main__":
    unittest.main()
