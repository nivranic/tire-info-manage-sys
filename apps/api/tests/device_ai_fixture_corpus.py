"""Test-only access to the portable, synthetic device-AI fixture closure."""
import hashlib
import json
from pathlib import Path, PurePosixPath

CORPUS_ROOT = Path(__file__).resolve().parents[3] / "packages/domain-types/fixtures/device-ai-v1"
PROVENANCE_SHA256 = "278e8cacad9a8537264781e49ce381111e6ed50b17a224aa32ccdf066012172d"


def _relative_path(value: str) -> None:
    assert isinstance(value, str) and value and "\\" not in value and ":" not in value, "invalid corpus path"
    assert not PurePosixPath(value).is_absolute(), "invalid corpus path"
    assert all(part not in {"", ".", ".."} for part in value.split("/")), "invalid corpus path"


class DeviceAiFixtureCorpus:
    def __init__(self, root: Path = CORPUS_ROOT):
        self.root = root
        raw = (root / "provenance.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == PROVENANCE_SHA256, "corpus provenance SHA drift"
        provenance = json.loads(raw)
        assert provenance["schema"] == "device-ai-test-corpus-provenance@1"
        assert provenance["synthetic_only"] is True
        assert provenance["source_root"] == ".artifacts/device-ai50"
        assert provenance["file_count"] == len(provenance["files"]) == 127
        self.entries = {}
        for entry in provenance["files"]:
            relative = entry["path"]
            _relative_path(relative)
            assert relative not in self.entries, "duplicate corpus binding"
            assert entry["source_path"] == provenance["source_root"] + "/" + relative
            self.entries[relative] = entry

    def read_bytes(self, relative: str) -> bytes:
        _relative_path(relative)
        assert relative in self.entries, "unbound corpus file"
        entry = self.entries[relative]
        raw = (self.root / relative).read_bytes()
        assert len(raw) == entry["byte_count"], f"corpus byte count drift: {relative}"
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], f"corpus SHA drift: {relative}"
        return raw

    def read_json(self, relative: str):
        return json.loads(self.read_bytes(relative))

    def verify_all(self) -> None:
        for relative in self.entries:
            self.read_bytes(relative)


CORPUS = DeviceAiFixtureCorpus()
CORPUS.verify_all()


def read_producer_sample(name: str) -> bytes:
    return CORPUS.read_bytes("projection-vectors-a/inputs/" + name)
