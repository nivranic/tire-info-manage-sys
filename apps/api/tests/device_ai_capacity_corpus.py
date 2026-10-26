"""Pinned, closed test-only reader for the independent synthetic R73 corpus."""
import hashlib
import json
from pathlib import Path, PurePosixPath

CORPUS_ROOT = Path(__file__).resolve().parents[3] / "packages/domain-types/fixtures/device-ai-capacity-v1"
MANIFEST_SHA256 = "c1d454ce4875a9d9c6e77fc8dd9f59ae4ae147ca0ca030af553e83bae14525d1"


def relative_path(value):
    assert type(value) is str and value and "\\" not in value and ":" not in value, "invalid capacity corpus path"
    assert not PurePosixPath(value).is_absolute(), "invalid capacity corpus path"
    assert all(part not in {"", ".", ".."} for part in value.split("/")), "invalid capacity corpus path"


def check_bytes(raw, size, digest):
    assert type(size) is int and len(raw) == size, "capacity corpus byte count drift"
    assert hashlib.sha256(raw).hexdigest() == digest, "capacity corpus SHA drift"


class CapacityCorpus:
    def __init__(self, root=CORPUS_ROOT):
        self.root = Path(root).resolve()
        raw = (self.root / "manifest.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256, "capacity manifest SHA drift"
        manifest = json.loads(raw)
        assert manifest["schema"] == "device-ai-capacity-corpus@1" and manifest["synthetic_only"] is True
        assert manifest["max_package_bytes"] == 8_388_608
        self.entries = {}
        for entry in manifest["files"]:
            path = entry["path"]
            relative_path(path)
            assert path not in self.entries, "duplicate capacity corpus path"
            self.entries[path] = entry
        self.verify_all()

    def read_bytes(self, path):
        relative_path(path)
        assert path in self.entries, "unbound capacity corpus file"
        target = (self.root / path).resolve()
        assert target.is_relative_to(self.root), "capacity corpus escaped root"
        raw = target.read_bytes()
        entry = self.entries[path]
        check_bytes(raw, entry["byte_count"], entry["sha256"])
        return raw

    def read_json(self, path):
        return json.loads(self.read_bytes(path))

    def verify_all(self):
        for path in self.entries:
            self.read_bytes(path)

    def expand(self, case):
        recipe = case["input"]
        assert recipe["form"] == "repeat_hex"
        assert type(recipe["repeat_count"]) is int and 0 <= recipe["repeat_count"] <= 8_388_609
        prefix, repeat, suffix = (bytes.fromhex(recipe[k]) for k in ["prefix_hex", "repeat_hex", "suffix_hex"])
        assert len(prefix) + len(repeat) * recipe["repeat_count"] + len(suffix) == case["input_byte_count"]
        raw = prefix + repeat * recipe["repeat_count"] + suffix
        check_bytes(raw, case["input_byte_count"], case["input_sha256"])
        return raw

    def formal_bytes(self, spec, case):
        base = self.read_bytes(spec["base_pack"])
        count = case["padding_spaces"]
        assert type(count) is int and 0 <= count <= 8_388_609
        raw = base + b" " * count
        check_bytes(raw, case["input_byte_count"], case["input_sha256"])
        return raw


CORPUS = CapacityCorpus()
