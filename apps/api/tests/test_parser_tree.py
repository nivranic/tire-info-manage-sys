"""Filesystem invariants for verified parser source enumeration."""
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tire_api import parser_bundles as bundles


def package(tmp_path):
    root = tmp_path / 'package'
    root.mkdir()
    (root / '__init__.py').write_bytes(b'')
    (root / 'adapter.py').write_bytes(b'value = 1\n')
    return root


def test_exact_bytes_and_source_only_exclusions(tmp_path):
    root = package(tmp_path)
    expected = {'__init__.py': b'', 'adapter.py': b'value = 1\n'}
    assert bundles._tree(root) == expected
    (root / 'notes.txt').write_bytes(b'ignored in trusted source only')
    (root / '__pycache__').mkdir()
    (root / '__pycache__/adapter.pyc').write_bytes(b'not executable')
    assert bundles._tree(root, source=True) == expected
    with pytest.raises(bundles.BundleError, match='parser_bundle_integrity_failed'):
        bundles._tree(root)


def test_existing_hardlink_is_refused(tmp_path):
    root = package(tmp_path)
    os.link(root / 'adapter.py', tmp_path / 'alias.py')
    with pytest.raises(bundles.BundleError, match='parser_bundle_link_forbidden'):
        bundles._tree(root)


@pytest.mark.parametrize('swap', ['hardlink', 'different_inode'])
def test_open_handle_must_still_match_the_checked_single_link_file(tmp_path, monkeypatch, swap):
    root = package(tmp_path)
    target = root / 'adapter.py'
    original_open = Path.open
    changed = False

    def open_after_swap(self, *args, **kwargs):
        nonlocal changed
        if self == target and not changed:
            changed = True
            if swap == 'hardlink':
                os.link(target, tmp_path / 'late-alias.py')
            else:
                # Same bytes must not hide a changed filesystem object.
                replacement = tmp_path / 'replacement.py'
                replacement.write_bytes(b'value = 1\n')
                os.replace(replacement, target)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', open_after_swap)
    with pytest.raises(bundles.BundleError, match='parser_bundle_link_forbidden'):
        bundles._tree(root)
    assert changed


@pytest.mark.parametrize('kind', ['symlink', 'windows_reparse'])
def test_ancestor_redirection_is_refused_before_reading_leaf(tmp_path, monkeypatch, kind):
    root = package(tmp_path)
    original = Path.lstat
    visited = []

    def lstat(self, *args, **kwargs):
        visited.append(self)
        if self == root:
            return SimpleNamespace(st_mode=stat.S_IFLNK if kind == 'symlink' else stat.S_IFDIR,
                                   st_file_attributes=0 if kind == 'symlink' else 0x400)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(bundles.BundleError, match='parser_bundle_link_forbidden'):
        bundles._tree(root)
    assert root / 'adapter.py' not in visited


@pytest.mark.parametrize('limit', ['file', 'total', 'count'])
def test_allocation_limits_still_apply(tmp_path, monkeypatch, limit):
    root = package(tmp_path)
    name, value = {'file': ('MAX_FILE_BYTES', 2), 'total': ('MAX_TOTAL_BYTES', 2),
                   'count': ('MAX_FILES', 1)}[limit]
    monkeypatch.setattr(bundles, name, value)
    expected = 'parser_bundle_integrity_failed' if limit == 'file' else 'parser_bundle_too_large'
    with pytest.raises(bundles.BundleError, match=expected):
        bundles._tree(root)


def test_source_changes_during_copy_are_rejected(tmp_path, monkeypatch):
    root = package(tmp_path)
    manifest = {'files': bundles._metadata(bundles._tree(root))}
    destination = tmp_path / 'copied'
    original = bundles.verify_tree

    def mutate_source(checked, manifest, **kwargs):
        original(checked, manifest, **kwargs)
        (root / 'adapter.py').write_bytes(b'value = 2\n')

    monkeypatch.setattr(bundles, 'verify_tree', mutate_source)
    with pytest.raises(bundles.BundleError, match='parser_bundle_integrity_failed'):
        bundles.copy_verified(root, manifest, destination)
