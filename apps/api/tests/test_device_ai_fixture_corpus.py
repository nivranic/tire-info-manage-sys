"""Portable corpus integrity failures use disposable copies, never sealed files."""
import shutil

import pytest

from device_ai_fixture_corpus import CORPUS, CORPUS_ROOT, DeviceAiFixtureCorpus


def test_complete_reference_closure_is_bound_without_artifact_access():
    CORPUS.verify_all()
    assert len(CORPUS.entries) == 127
    assert CORPUS.read_json("projection-vectors-a/inputs/manifest.json")["synthetic_private_only"] is True


def test_changed_provenance_is_rejected_before_fixture_use(tmp_path):
    (tmp_path / "provenance.json").write_bytes((CORPUS_ROOT / "provenance.json").read_bytes() + b" ")
    with pytest.raises(AssertionError, match="provenance SHA drift"):
        DeviceAiFixtureCorpus(tmp_path)


@pytest.mark.parametrize("same_size", [False, True])
def test_changed_fixture_bytes_are_rejected(tmp_path, same_size):
    relative = "specs/decoder-fixtures-a/fixtures.json"
    shutil.copyfile(CORPUS_ROOT / "provenance.json", tmp_path / "provenance.json")
    destination = tmp_path / relative
    destination.parent.mkdir(parents=True)
    original = CORPUS.read_bytes(relative)
    destination.write_bytes(original[:-1] + bytes([original[-1] ^ 1]) if same_size else b"tampered")
    with pytest.raises(AssertionError, match="corpus (byte count|SHA) drift"):
        DeviceAiFixtureCorpus(tmp_path).read_bytes(relative)


@pytest.mark.parametrize("relative", ["../provenance.json", "/absolute", "a\\b", "a/../b", "", "missing.json"])
def test_unbound_or_escaping_paths_are_rejected(relative):
    with pytest.raises(AssertionError, match="(invalid corpus path|unbound corpus file)"):
        CORPUS.read_bytes(relative)
