"""Independent synthetic projection vectors; no real rights or owner evidence.

Load only the two exact source files, bypassing application/package startup.
All fixtures are in memory. The canonical policy digest was independently
computed using SHA256.HashData over UTF-8 in PowerShell 7, without product code.
"""

import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import MappingProxyType, ModuleType
import unittest


_PACKAGE = "_external_tire_fact_projection_test_package"
_ROOT = Path(__file__).resolve().parents[1] / "tire_api"
_package = ModuleType(_PACKAGE)
_package.__path__ = []
sys.modules[_PACKAGE] = _package


def _load(name, filename):
    target = _ROOT / filename
    spec = importlib.util.spec_from_file_location(_PACKAGE + "." + name, target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(target.read_bytes(), str(target), "exec"), vars(module))
    return module


policy_core = _load("external_fact_policy", "external_fact_policy.py")
projection = _load("external_tire_fact_projection", "external_tire_fact_projection.py")
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
REQUIRED_FIELDS = [
    "evidence.source_id", "evidence.snapshot_id", "evidence.raw_hash", "evidence.parser_version",
    "identity.variant_id", "identity.identity_status", "identity.identity_contract_version",
    "identity.brand", "identity.model", "identity.region", "identity.manufacturer_product_code",
    "identity.product_code_type", "identity.size", "identity.load_index", "identity.speed_rating",
    "identity.xl", "identity.hl", "identity.run_flat", "identity.oe_mark",
    "identity.acoustic_technology", "identity.gtin", "identity.technology_features", "identity.eprel_id",
]
FACT_NAMES = [
    "utqg_treadwear", "utqg_traction", "utqg_temperature", "eu_fuel_class", "eu_wet_grip",
    "eu_external_noise_db", "eu_noise_class", "weight_kg", "tread_depth",
]
CANONICAL_BYTES = (
    b'{"coverage":{"field_keys":["evidence.source_id","evidence.snapshot_id","evidence.raw_hash",'
    b'"evidence.parser_version","identity.variant_id","identity.identity_status",'
    b'"identity.identity_contract_version","identity.brand","identity.model","identity.region",'
    b'"identity.manufacturer_product_code","identity.product_code_type","identity.size",'
    b'"identity.load_index","identity.speed_rating","identity.xl","identity.hl","identity.run_flat",'
    b'"identity.oe_mark","identity.acoustic_technology","identity.gtin","identity.technology_features",'
    b'"identity.eprel_id","facts.utqg_treadwear","facts.utqg_traction","facts.utqg_temperature",'
    b'"facts.eu_fuel_class","facts.eu_wet_grip","facts.eu_external_noise_db","facts.eu_noise_class",'
    b'"facts.weight_kg","facts.tread_depth"],"observations":[{"parser_version":"parser-1",'
    b'"raw_hash":"1111111111111111111111111111111111111111111111111111111111111111",'
    b'"snapshot_id":"snap-1"}]},"grant_id":"grant-1","previous_digest":null,'
    b'"purpose":"external_structured_fact_read","review":{"reviewed_at":"2026-10-20T00:00:00Z",'
    b'"reviewer":"Fixture reviewer"},"revision":1,"rights":{"basis":"Synthetic test basis",'
    b'"evidence_reference":"opaque:fixture","evidence_sha256":'
    b'"2222222222222222222222222222222222222222222222222222222222222222",'
    b'"holder":"Fixture holder"},"schema":"external-fact-policy@1","source_id":"source-1",'
    b'"state":"approved","validity":{"not_after":"2026-10-22T00:00:00Z",'
    b'"not_before":"2026-10-20T00:00:00Z"}}'
)
EXPECTED_DIGEST = "cb276198438f02b8f6fb0345ddb503f1625db7df8fe1b49757fa5d0a9a00857d"


def _record():
    value = json.loads(CANONICAL_BYTES)
    value["digest"] = EXPECTED_DIGEST
    return value


def _seal(value):
    # Test-owned serializer: no product serializer/hash/projection builds answers.
    body = {key: child for key, child in value.items() if key != "digest"}
    value["digest"] = hashlib.sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return value


def _policy(*, fields=None, record=None):
    value = _record() if record is None else record
    if fields is not None:
        value["coverage"]["field_keys"] = fields
    _seal(value)
    return policy_core.validate_revision_chain([value], expected_head=value["digest"])


def _payload():
    return {
        "observation": {"source_id": "source-1", "snapshot_id": "snap-1",
                        "raw_hash": "1" * 64, "parser_version": "parser-1"},
        "identity": {
            "variant_id": "variant-1", "contract_version": "variant-identity@2", "status": "complete",
            "values": {"brand": "Fixture brand", "model": "Fixture model", "region": "EU",
                       "manufacturer_product_code": "000123", "product_code_type": "maker-stock",
                       "size": "265/40ZR20", "load_index": "104/102", "speed_rating": "Y",
                       "xl": True, "hl": False, "run_flat": False,
                       "oe_mark": "", "acoustic_technology": ""},
        },
        "facts": {"utqg_treadwear": 320, "utqg_traction": "AA", "utqg_temperature": "A",
                  "eu_fuel_class": "G", "eu_wet_grip": "A", "eu_external_noise_db": 72,
                  "eu_noise_class": "B", "weight_kg": 12.345,
                  "tread_depth": {"value": 10, "unit": "1/32 in"}},
        "conflicted_fields": [],
    }


class ExternalTireFactProjectionTests(unittest.TestCase):
    def _decision(self, payload=None, *, selected=None, fields=None, now=NOW,
                  status="projected", reason="projected"):
        if selected is None:
            selected = _policy(fields=fields)
        result = projection.project_observation(selected, _payload() if payload is None else payload, now=now)
        self.assertEqual((result.status, result.reason), (status, reason))
        if status == "projected":
            self.assertIs(type(result.item), MappingProxyType)
        else:
            self.assertIsNone(result.item)
            self.assertEqual(result.to_dict(), {"status": status, "reason": reason, "item": None})
        return result

    def _bad_identity(self, key, value):
        payload = _payload()
        payload["identity"]["values"][key] = value
        return self._decision(payload, status="invalid", reason="identity_invalid")

    def _fact(self, key, value, *, valid=True):
        payload = _payload()
        payload["facts"] = {key: value}
        if valid:
            result = self._decision(payload)
            self.assertEqual(result.to_dict()["item"]["facts"], {key: value})
            return result
        return self._decision(payload, status="invalid", reason="fact_value_invalid")

    def test_independent_digest_and_handwritten_complete_projection(self):
        self.assertEqual(len(CANONICAL_BYTES), 1428)
        self.assertEqual(hashlib.sha256(CANONICAL_BYTES).hexdigest(), EXPECTED_DIGEST)
        self.assertEqual(json.dumps(json.loads(CANONICAL_BYTES), ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8"), CANONICAL_BYTES)
        self.assertEqual(json.loads(CANONICAL_BYTES)["coverage"]["field_keys"],
                         REQUIRED_FIELDS + ["facts." + name for name in FACT_NAMES])
        self.assertEqual(_policy().head, EXPECTED_DIGEST)
        expected = {
            "schema": "external-tire-fact-projection@1", "data_state": "local_snapshot",
            "source_refresh_performed": False,
            "observation": {"source_id": "source-1", "snapshot_id": "snap-1",
                            "raw_hash": "1111111111111111111111111111111111111111111111111111111111111111",
                            "parser_version": "parser-1"},
            "identity": {
                "variant_id": "variant-1", "contract_version": "variant-identity@2", "status": "complete",
                "values": {"brand": "Fixture brand", "model": "Fixture model", "region": "EU",
                           "manufacturer_product_code": "000123", "product_code_type": "maker-stock",
                           "size": "265/40ZR20", "load_index": "104/102", "speed_rating": "Y",
                           "xl": True, "hl": False, "run_flat": False,
                           "oe_mark": "", "acoustic_technology": "", "gtin": None,
                           "technology_features": None, "eprel_id": None},
            },
            "facts": {"utqg_treadwear": 320, "utqg_traction": "AA", "utqg_temperature": "A",
                      "eu_fuel_class": "G", "eu_wet_grip": "A", "eu_external_noise_db": 72,
                      "eu_noise_class": "B", "weight_kg": 12.345,
                      "tread_depth": {"value": 10, "unit": "1/32 in"}},
            "conflicted_fields": [],
        }
        self.assertEqual(self._decision().to_dict()["item"], expected)

    def test_source_scoped_unknowns_false_empty_and_optional_identity(self):
        payload = _payload()
        payload["identity"]["status"] = "source_scoped"
        values = payload["identity"]["values"]
        for key in ("manufacturer_product_code", "product_code_type", "load_index", "speed_rating",
                    "xl", "hl", "run_flat", "oe_mark", "acoustic_technology"):
            values[key] = None
        result = self._decision(payload)
        self.assertEqual(result.item["identity"]["status"], "source_scoped")
        for key in ("gtin", "technology_features", "eprel_id"):
            self.assertIsNone(result.item["identity"]["values"][key])
        values.update(gtin="036000291452", technology_features=["zeta", "Alpha", "隔音"], eprel_id="1",
                      xl=False, hl=False, run_flat=False, oe_mark="", acoustic_technology="")
        result = self._decision(payload)
        self.assertEqual(result.item["identity"]["values"]["technology_features"], ("Alpha", "zeta", "隔音"))
        self.assertEqual(result.item["identity"]["values"]["gtin"], "036000291452")
        self.assertIs(result.item["identity"]["values"]["xl"], False)
        self.assertEqual(result.item["identity"]["values"]["oe_mark"], "")
        self.assertEqual(values["technology_features"], ["zeta", "Alpha", "隔音"])
        self.assertEqual(result.item["identity"]["status"], "source_scoped")

    def test_complete_requires_all_thirteen_nonnull_identity_values(self):
        names = ("brand", "model", "region", "manufacturer_product_code", "product_code_type", "size",
                 "load_index", "speed_rating", "xl", "hl", "run_flat", "oe_mark", "acoustic_technology")
        for name in names:
            with self.subTest(name=name):
                self._bad_identity(name, None)
                payload = _payload()
                del payload["identity"]["values"][name]
                self._decision(payload, status="invalid", reason="identity_invalid")
        for key in ("manufacturer_product_code", "product_code_type"):
            self._bad_identity(key, "")

    def test_identity_text_limits_and_unicode_are_exact(self):
        for key, maximum in (("brand", 120), ("model", 200), ("region", 40),
                             ("manufacturer_product_code", 100), ("product_code_type", 100),
                             ("oe_mark", 100), ("acoustic_technology", 100)):
            with self.subTest(key=key):
                payload = _payload()
                payload["identity"]["values"][key] = "审" * maximum
                self.assertEqual(self._decision(payload).item["identity"]["values"][key], "审" * maximum)
                for bad in ("审" * (maximum + 1), " leading", "trailing ", "a\x00b", "a\x7fb",
                            "a\u0085b", "a\u200bb", "a\uffffb", 1, False, [], {}):
                    self._bad_identity(key, bad)
        for key in ("brand", "model", "region"):
            self._bad_identity(key, "")

    def test_ascii_size_and_load_boundaries_without_normalization(self):
        for size in ("100/20R10", "455/95ZR30", "265/40R20", "265/40ZR20", "265/40ZR29.5"):
            payload = _payload()
            payload["identity"]["values"]["size"] = size
            self.assertEqual(self._decision(payload).item["identity"]["values"]["size"], size)
        for size in ("099/20R10", "456/40R20", "265/19R20", "265/96R20", "265/40R09",
                     "265/40R30.5", "265/40R20.0", "265/40R20.50", "265/40 R20", "265/40r20",
                     "２６５/40R20", "265/٤٠R20", "265/40R２０", 265, " 265/40R20"):
            with self.subTest(size=size):
                self._bad_identity("size", size)
        for load in ("00", "99", "104", "999/999"):
            payload = _payload()
            payload["identity"]["values"]["load_index"] = load
            self.assertEqual(self._decision(payload).item["identity"]["values"]["load_index"], load)
        for load in (104, True, "1", "1000", "104/1", "104 /102", "１０４", "١٠٤", "104/102/100"):
            self._bad_identity("load_index", load)

    def test_speed_and_bool_identity_are_strict(self):
        for speed in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "B", "C", "D", "E",
                      "F", "G", "J", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "U", "H",
                      "V", "W", "Y", "(Y)", "ZR"):
            payload = _payload()
            payload["identity"]["values"]["speed_rating"] = speed
            self.assertEqual(self._decision(payload).item["identity"]["values"]["speed_rating"], speed)
        for speed in ("y", "A0", "A9", "I", "O", "X", " Y", "(y)", 1, False, [], {}):
            self._bad_identity("speed_rating", speed)
        for key in ("xl", "hl", "run_flat"):
            for bad in (0, 1, "false", "true", [], {}):
                self._bad_identity(key, bad)

    def test_gtin_checksum_eprel_and_feature_bounds(self):
        for gtin in ("00000000", "036000291452", "4006381333931", "00000000000000"):
            payload = _payload()
            payload["identity"]["values"]["gtin"] = gtin
            self.assertEqual(self._decision(payload).item["identity"]["values"]["gtin"], gtin)
        for gtin in ("96385075", "036000291453", "4006381333932", "0" * 7, "0" * 9, "0" * 15,
                     "０" * 8, "٠" * 8, 36000291452, " 036000291452"):
            self._bad_identity("gtin", gtin)
        for eprel in ("1", "9" * 20):
            payload = _payload()
            payload["identity"]["values"]["eprel_id"] = eprel
            self.assertEqual(self._decision(payload).item["identity"]["values"]["eprel_id"], eprel)
        for eprel in ("0", "01", "1" * 21, "١", "+1", 1):
            self._bad_identity("eprel_id", eprel)
        for features in ([], ["z", "a"], [str(index) + "x" * 98 for index in range(32)]):
            payload = _payload()
            payload["identity"]["values"]["technology_features"] = features
            self.assertEqual(self._decision(payload).item["identity"]["values"]["technology_features"],
                             tuple(sorted(features)))
        for features in (["x"] * 2, [str(index) for index in range(33)], [""], [" leading"],
                         ["x" * 101], [1], {"feature": "x"}):
            self._bad_identity("technology_features", features)

    def test_identity_distinctions_are_preserved_without_new_ids(self):
        for key, value in (("product_code_type", "another-namespace"), ("size", "265/40R20"),
                           ("oe_mark", "MO"), ("acoustic_technology", "Acoustic"),
                           ("technology_features", ["Acoustic"]), ("model", "fixture model")):
            with self.subTest(key=key):
                payload = _payload()
                payload["identity"]["values"][key] = value
                changed = self._decision(payload)
                self.assertEqual(changed.item["identity"]["variant_id"], "variant-1")
                self.assertNotEqual(changed.item["identity"]["values"], self._decision().item["identity"]["values"])
        payload = _payload()
        payload["identity"]["status"] = "source_scoped"
        self.assertEqual(self._decision(payload).item["identity"]["status"], "source_scoped")

    def test_all_enum_fact_values_and_wrong_spellings(self):
        for key, legal in (("utqg_traction", ("AA", "A", "B", "C")),
                           ("utqg_temperature", ("A", "B", "C")),
                           ("eu_fuel_class", tuple("ABCDEFG")), ("eu_wet_grip", tuple("ABCDEFG")),
                           ("eu_noise_class", ("A", "B", "C"))):
            for value in legal:
                with self.subTest(key=key, value=value):
                    self._fact(key, value)
            for bad in ("a", " AA", "H", "", 0, False, 1.0, [], {}):
                self._fact(key, bad, valid=False)

    def test_integer_fact_min_max_and_exact_types(self):
        for key, maximum in (("utqg_treadwear", 5000), ("eu_external_noise_db", 200)):
            for value in (0, 1, maximum - 1, maximum):
                with self.subTest(key=key, value=value):
                    result = self._fact(key, value)
                    self.assertIs(type(result.item["facts"][key]), int)
            for bad in (-1, maximum + 1, 0.0, float(maximum), True, False, "0", [], {}, 10 ** 500):
                self._fact(key, bad, valid=False)
        self._fact("utqg_treadwear", 321)  # No invented multiple-of-20 rule.

    def test_weight_boundaries_precision_and_nonfinite(self):
        for value in (0.001, 1, 12.345, 199.999, 200, 200.0):
            result = self._fact("weight_kg", value)
            self.assertIs(type(result.item["facts"]["weight_kg"]), type(value))
        for bad in (0, 0.0, -0.0, -1, 200.001, 0.0001, 1.2345, 1e-7,
                    True, False, "12.345", float("nan"), float("inf"), float("-inf"), {}, []):
            self._fact("weight_kg", bad, valid=False)

    def test_tread_units_boundaries_and_precision_without_conversion(self):
        for unit, maximum, smallest, too_precise in (("mm", 100, 0.001, 0.0001),
                                                    ("1/32 in", 128, 0.001, 0.0001),
                                                    ("in", 4, 0.0001, 0.00001)):
            for value in (0, -0.0, smallest, maximum):
                with self.subTest(unit=unit, value=value):
                    self._fact("tread_depth", {"value": value, "unit": unit})
            for bad in (-smallest, maximum + smallest, too_precise, True, False, "1", None,
                        float("nan"), float("inf"), float("-inf")):
                self._fact("tread_depth", {"value": bad, "unit": unit}, valid=False)
        for bad in ({"value": 1, "unit": "MM"}, {"value": 1, "unit": "inch"},
                    {"value": 1, "unit": 1}, {"value": 1}, {"unit": "mm"},
                    {"value": 1, "unit": "mm", "extra": 1}, 1, "1mm", []):
            self._fact("tread_depth", bad, valid=False)

    def test_missing_null_zero_and_conflict_are_separate(self):
        payload = _payload()
        payload["facts"] = {"utqg_treadwear": 0, "eu_external_noise_db": None, "weight_kg": 12}
        payload["conflicted_fields"] = ["weight_kg", "eu_wet_grip"]
        item = self._decision(payload).to_dict()["item"]
        self.assertEqual(item["facts"], {"eu_external_noise_db": None, "utqg_treadwear": 0})
        self.assertEqual(item["conflicted_fields"], ["eu_wet_grip", "weight_kg"])
        self.assertNotIn("eu_fuel_class", item["facts"])
        for name in FACT_NAMES:
            with self.subTest(explicit_null=name):
                self._fact(name, None)
        payload["facts"] = {}
        payload["conflicted_fields"] = []
        self._decision(payload, status="not_applicable", reason="no_permitted_facts")
        payload["conflicted_fields"] = ["weight_kg"]
        self.assertEqual(self._decision(payload).to_dict()["item"]["facts"], {})

    def test_every_required_field_including_null_optional_needs_coverage(self):
        self.assertEqual(len(REQUIRED_FIELDS), 23)
        for missing in REQUIRED_FIELDS:
            with self.subTest(missing=missing):
                fields = [name for name in REQUIRED_FIELDS if name != missing] + ["facts.utqg_treadwear"]
                self._decision(fields=fields, status="not_applicable", reason="required_fields_not_covered")
        self._decision(fields=["facts.utqg_treadwear"], status="not_applicable",
                       reason="required_fields_not_covered")

    def test_each_fact_is_individually_trimmed_using_same_selected_policy(self):
        payload = _payload()
        for name in FACT_NAMES:
            with self.subTest(permitted=name):
                result = self._decision(payload, fields=REQUIRED_FIELDS + ["facts." + name])
                self.assertEqual(result.to_dict()["item"]["facts"], {name: payload["facts"][name]})
        self._decision(fields=REQUIRED_FIELDS, status="not_applicable", reason="no_permitted_facts")
        for collection in ([_policy(), _policy()], (_policy(), _policy()), {"allow": True}):
            self._decision(selected=collection, status="invalid", reason="policy_invalid")

    def test_unpermitted_conflicts_and_explicit_null_do_not_leak(self):
        payload = _payload()
        payload["facts"] = {"utqg_treadwear": None, "weight_kg": None}
        payload["conflicted_fields"] = ["weight_kg", "eu_wet_grip"]
        result = self._decision(payload, fields=REQUIRED_FIELDS + ["facts.utqg_treadwear"])
        self.assertEqual(result.to_dict()["item"]["facts"], {"utqg_treadwear": None})
        self.assertEqual(result.item["conflicted_fields"], ())
        self._decision(payload, fields=REQUIRED_FIELDS, status="not_applicable", reason="no_permitted_facts")
        result = self._decision(payload, fields=REQUIRED_FIELDS + ["facts.weight_kg"])
        self.assertEqual(result.to_dict()["item"]["facts"], {})
        self.assertEqual(result.item["conflicted_fields"], ("weight_kg",))

    def test_malformed_unpermitted_fact_is_still_rejected(self):
        payload = _payload()
        payload["facts"]["weight_kg"] = "secret-invalid-value"
        result = self._decision(payload, fields=REQUIRED_FIELDS + ["facts.utqg_treadwear"],
                                status="invalid", reason="fact_value_invalid")
        self.assertNotIn("secret-invalid-value", repr(result))
        payload["facts"]["weight_kg"] = 12
        for conflicts in (["weight_kg", "weight_kg"], ["weight"], [None], ["weight_kg"] * 10, {}):
            payload["conflicted_fields"] = conflicts
            self._decision(payload, status="invalid", reason="fact_value_invalid")

    def test_exact_observation_and_no_cartesian_product_coverage(self):
        for key, wrong in (("source_id", "source-2"), ("snapshot_id", "snap-2"),
                           ("raw_hash", "3" * 64), ("parser_version", "parser-2")):
            payload = _payload()
            payload["observation"][key] = wrong
            with self.subTest(key=key):
                self._decision(payload, status="not_applicable", reason="policy_not_applicable")
        record = _record()
        record["coverage"]["observations"].append({
            "snapshot_id": "snap-2", "raw_hash": "3" * 64, "parser_version": "parser-2",
        })
        selected = _policy(record=record)
        for key, wrong in (("snapshot_id", "snap-2"), ("raw_hash", "3" * 64), ("parser_version", "parser-2")):
            payload = _payload()
            payload["observation"][key] = wrong
            self._decision(payload, selected=selected, status="not_applicable", reason="policy_not_applicable")

    def test_nonapproved_future_expired_and_withdrawn_policy(self):
        for state in ("pending", "restricted", "withdrawn"):
            record = _record()
            record["state"] = state
            self._decision(selected=_policy(record=record), status="not_applicable", reason="policy_not_applicable")
        for now in (datetime(2026, 10, 19, tzinfo=timezone.utc), datetime(2026, 10, 22, tzinfo=timezone.utc)):
            self._decision(now=now, status="not_applicable", reason="policy_not_applicable")
        self._decision(now=datetime(2026, 10, 20, tzinfo=timezone.utc))
        self._decision(now=datetime(2026, 10, 21, 23, 59, 59, tzinfo=timezone.utc))
        record = _record()
        record["validity"]["not_before"] = "2026-10-21T01:00:00Z"
        self._decision(selected=_policy(record=record), status="not_applicable", reason="policy_not_applicable")
        first = _record()
        second = _record()
        second.update(revision=2, previous_digest=first["digest"], state="withdrawn")
        _seal(second)
        selected = policy_core.validate_revision_chain([first, second], expected_head=second["digest"])
        self._decision(selected=selected, status="not_applicable", reason="policy_not_applicable")

    def test_bad_policy_and_explicit_utc_now_fail_closed(self):
        for selected in ({}, object(), True):
            self._decision(selected=selected, status="invalid", reason="policy_invalid")
        for damage in (
            lambda selected: object.__setattr__(selected, "head", "0" * 64),
            lambda selected: object.__setattr__(selected.latest, "state", "withdrawn"),
            lambda selected: object.__setattr__(selected.latest.coverage, "field_keys", ["facts.weight_kg"]),
            lambda selected: object.__delattr__(selected.latest.review, "reviewer"),
        ):
            selected = _policy()
            damage(selected)
            self._decision(selected=selected, status="invalid", reason="policy_invalid")
        for now in (None, 0, "2026-10-21T00:00:00Z", NOW.replace(tzinfo=None),
                    NOW.astimezone(timezone(timedelta(hours=1)))):
            self._decision(now=now, status="invalid", reason="policy_invalid")
        with self.assertRaises(TypeError):
            projection.project_observation(_policy(), _payload())

    def test_closed_shapes_aliases_and_observation_types(self):
        for group, reason in ((None, "input_invalid"), ("observation", "input_invalid"),
                              ("identity", "identity_invalid")):
            for mutation in ("extra", "missing"):
                payload = _payload()
                value = payload if group is None else payload[group]
                if mutation == "extra":
                    value["private_input"] = "must-not-echo"
                else:
                    del value[next(iter(value))]
                self._decision(payload, status="invalid", reason=reason)
        for key, bad in (("variant_id", "id/path"), ("variant_id", "a" * 65),
                         ("contract_version", "variant-identity@1"), ("contract_version", []),
                         ("status", "COMPLETE"), ("status", []), ("values", [])):
            payload = _payload()
            payload["identity"][key] = bad
            self._decision(payload, status="invalid", reason="identity_invalid")
        payload = _payload()
        payload["identity"]["values"]["source_variant_name"] = "private"
        self._decision(payload, status="invalid", reason="identity_invalid")
        for alias in ("weight", "tread_depth_mm", "fuel_class", "utqg", "raw", "citation", "verification_id"):
            payload = _payload()
            payload["facts"][alias] = 1
            self._decision(payload, status="invalid", reason="fact_value_invalid")
        for key, bad in (("source_id", "source/1"), ("snapshot_id", "s" * 65), ("raw_hash", "A" * 64),
                         ("parser_version", " parser-1"), ("parser_version", "a\x00b")):
            payload = _payload()
            payload["observation"][key] = bad
            self._decision(payload, status="invalid", reason="input_invalid")

    def test_cycles_depth_and_node_capacity_are_bounded(self):
        cycle = []
        cycle.append(cycle)
        self._decision(cycle, status="invalid", reason="input_invalid")
        payload = _payload()
        payload["facts"]["tread_depth"] = payload
        self._decision(payload, status="invalid", reason="input_invalid")
        # Root depth 0: four nested arrays plus the scalar reach depth 4.
        self._decision([[[[0]]]], status="invalid", reason="input_invalid")
        self._decision([[[[[0]]]]], status="invalid", reason="projection_capacity")
        # JSON value nodes count the root plus each scalar; names are not nodes.
        self._decision([None] * 255, status="invalid", reason="input_invalid")
        self._decision([None] * 256, status="invalid", reason="projection_capacity")
        self._decision([None] * 257, status="invalid", reason="projection_capacity")
        payload = _payload()
        payload["identity"]["values"]["technology_features"] = ["feature"]
        self._decision(payload)  # The deepest legal identity list scalar is depth 4.

    def test_utf8_byte_capacity_and_valid_maximal_identity(self):
        for oversized in ("a" * 65537, "😀" * 16385, "a" * 32769 + "审" * 10923):
            self._decision(oversized, status="invalid", reason="projection_capacity")
        payload = _payload()
        payload["identity"]["values"]["technology_features"] = [
            str(index).zfill(2) + "😀" * 98 for index in range(32)
        ]
        result = self._decision(payload)
        ordinary = result.to_dict()["item"]
        encoded = json.dumps(ordinary, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertLessEqual(len(encoded), 65536)
        self.assertEqual(len(ordinary["identity"]["values"]["technology_features"]), 32)
        for location in ("value", "key"):
            payload = _payload()
            if location == "value":
                payload["identity"]["values"]["brand"] = "x\ud800y"
            else:
                payload["x\udfffy"] = None
            self._decision(payload, status="invalid", reason="input_invalid")

    def test_container_and_scalar_subclasses_cannot_run_user_methods(self):
        class HostileDict(dict):
            def items(self):
                raise AssertionError("dict subclass method executed")

        class HostileList(list):
            def __iter__(self):
                raise AssertionError("list subclass method executed")

        class HostileStr(str):
            def encode(self, *args, **kwargs):
                raise AssertionError("string subclass method executed")

        class HostileInt(int):
            def bit_length(self):
                raise AssertionError("integer subclass method executed")

        class HostileFloat(float):
            def __str__(self):
                raise AssertionError("float subclass method executed")

        class HostileMeta(type):
            def __eq__(self, other):
                raise AssertionError("metaclass equality executed")

        class HostileObject(metaclass=HostileMeta):
            pass

        for bad in (HostileDict(_payload()), HostileList([]), HostileStr("x"), HostileInt(1),
                    HostileFloat(1), HostileObject(), (), MappingProxyType({}), Decimal("1"), b"x", object()):
            self._decision(bad, status="invalid", reason="input_invalid")
        for key, bad in (("brand", HostileStr("brand")), ("technology_features", HostileList(["x"]))):
            payload = _payload()
            payload["identity"]["values"][key] = bad
            self._decision(payload, status="invalid", reason="input_invalid")
        payload = _payload()
        payload["facts"] = {}
        payload["facts"][HostileStr("weight_kg")] = 1
        self._decision(payload, status="invalid", reason="input_invalid")

    def test_all_output_layers_are_immutable_and_detached(self):
        payload = _payload()
        payload["identity"]["values"]["technology_features"] = ["z", "a"]
        payload["conflicted_fields"] = ["weight_kg"]
        before = copy.deepcopy(payload)
        selected = _policy()
        result = self._decision(payload, selected=selected)
        self.assertEqual(payload, before)
        for mapping in (result.item, result.item["observation"], result.item["identity"],
                        result.item["identity"]["values"], result.item["facts"],
                        result.item["facts"]["tread_depth"]):
            with self.assertRaises(TypeError):
                mapping["new"] = "changed"
        for sequence in (result.item["conflicted_fields"], result.item["identity"]["values"]["technology_features"]):
            self.assertIs(type(sequence), tuple)
            with self.assertRaises(TypeError):
                sequence[0] = "changed"
        with self.assertRaises(FrozenInstanceError):
            result.status = "invalid"
        expected = result.to_dict()
        payload["observation"].clear()
        payload["identity"]["values"]["technology_features"].append("changed")
        payload["identity"]["values"].clear()
        payload["facts"]["tread_depth"]["value"] = 99
        payload["conflicted_fields"].clear()
        exported = result.to_dict()
        exported["item"]["identity"]["values"]["technology_features"].append("changed")
        exported["item"]["facts"]["tread_depth"]["unit"] = "in"
        self.assertEqual(result.to_dict(), expected)

    def test_deterministic_order_and_no_policy_authenticity_claim(self):
        payload = _payload()
        payload["identity"]["values"]["technology_features"] = ["z", "a"]
        payload["conflicted_fields"] = ["weight_kg", "eu_wet_grip"]
        first = self._decision(payload)
        reordered = {key: payload[key] for key in reversed(list(payload))}
        reordered = copy.deepcopy(reordered)
        reordered["facts"] = dict(reversed(list(reordered["facts"].items())))
        reordered["conflicted_fields"].reverse()
        reordered["identity"]["values"]["technology_features"].reverse()
        second = self._decision(reordered)
        self.assertEqual(first, second)
        self.assertEqual(first.to_dict(), second.to_dict())
        record = _record()
        record["rights"]["holder"] = "Fabricated synthetic holder"
        record["rights"]["basis"] = "Self consistency does not authenticate actual permission"
        self.assertEqual(self._decision(selected=_policy(record=record)), self._decision())
        # Neither policy provenance nor the actual owner/binding is proven here.


if __name__ == "__main__":
    unittest.main()
