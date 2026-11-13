"""Filesystem invariants for verified parser source enumeration."""
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tire_api import parser_bundles as bundles


def extended(path):
    """Fixture spelling independent from the production path converter."""
    return Path('\\\\?\\' + str(path)) if os.name == 'nt' else path


def long_directory(tmp_path, name, segment='nested_directory_segment'):
    path = tmp_path / name
    while len(str(path)) < 300:
        path /= segment
    return path


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
        if self in (target, extended(target)) and not changed:
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
        if self in (root, extended(root)):
            return SimpleNamespace(st_mode=stat.S_IFLNK if kind == 'symlink' else stat.S_IFDIR,
                                   st_file_attributes=0 if kind == 'symlink' else 0x400)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(bundles.BundleError, match='parser_bundle_link_forbidden'):
        bundles._tree(root)
    assert root / 'adapter.py' not in visited
    assert extended(root / 'adapter.py') not in visited


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


@pytest.mark.skipif(os.name != 'nt', reason='Windows namespace and junction containment')
def test_regression_guard_keeps_resolved_namespace_and_handle_boundaries(tmp_path):
    import _winapi
    from regression_guard import RegressionGuard

    output = tmp_path / '.artifacts' / 'scope'
    private = output / 'private'
    private.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    guard = RegressionGuard(tmp_path, private, output)

    def extended(path):
        return Path('\\\\?\\' + str(path))

    inside_file, outside_file = private / 'inside.py', outside / 'outside.py'
    assert guard._inside(inside_file) and guard._inside(extended(inside_file))
    assert not guard._inside(outside_file) and not guard._inside(extended(outside_file))
    assert not guard._inside(extended(private / '..' / '..' / '..' / 'outside' / 'outside.py'))
    for path, expected in ((inside_file, True), (outside_file, False)):
        with path.open('wb') as stream:
            assert guard._inside(stream.fileno()) is expected

    link = private / 'escape'
    _winapi.CreateJunction(str(outside), str(link))
    try:
        assert not guard._inside(link / 'outside.py')
        assert not guard._inside(extended(link / 'outside.py'))
    finally:
        # Remove only the junction created here, never its target directory.
        link.rmdir()
    assert outside_file.is_file()


@pytest.mark.skipif(os.name != 'nt', reason='Windows long local paths')
@pytest.mark.parametrize('spelling', ['ordinary', 'extended'])
@pytest.mark.parametrize('segment', ['nested_directory_segment', '轮胎证据目录'])
def test_long_tree_read_and_verified_copy_preserve_bytes(tmp_path, spelling, segment):
    source = long_directory(tmp_path, 'source', segment)
    destination = long_directory(tmp_path, 'destination', segment)
    extended(source).mkdir(parents=True)
    expected = {'__init__.py': b'', 'adapter.py': b'value = 1\n'}
    for name, data in expected.items():
        (extended(source) / name).write_bytes(data)
    selected = source if spelling == 'ordinary' else extended(source)
    assert bundles._tree(selected) == expected
    manifest = {'files': bundles._metadata(expected)}
    bundles.copy_verified(selected, manifest, destination)
    assert bundles._tree(destination) == bundles._tree(extended(destination)) == expected
    assert {name: (extended(destination) / name).read_bytes() for name in expected} == expected


@pytest.mark.skipif(os.name != 'nt', reason='Windows long-path hardlinks')
def test_long_tree_still_refuses_real_hardlinks(tmp_path):
    source = long_directory(tmp_path, 'hardlinked')
    extended(source).mkdir(parents=True)
    leaf = extended(source) / 'adapter.py'
    leaf.write_bytes(b'value = 1\n')
    os.link(leaf, extended(source.parent) / 'alias.py')
    with pytest.raises(bundles.BundleError, match='parser_bundle_link_forbidden'):
        bundles._tree(source)


@pytest.mark.skipif(os.name != 'nt', reason='Windows long-path junctions')
@pytest.mark.parametrize('position', ['root', 'nested'])
def test_long_tree_still_refuses_real_junctions(tmp_path, position):
    import _winapi

    source = long_directory(tmp_path, 'redirected')
    extended(source).mkdir(parents=True)
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'adapter.py').write_bytes(b'value = 2\n')
    link = extended(source) / 'jump'
    _winapi.CreateJunction(str(target), str(link))
    try:
        selected = source / 'jump' if position == 'root' else source
        with pytest.raises(bundles.BundleError, match='parser_bundle_link_forbidden'):
            bundles._tree(selected)
    finally:
        link.rmdir()
    assert (target / 'adapter.py').read_bytes() == b'value = 2\n'


@pytest.mark.skipif(os.name != 'nt', reason='Windows path spelling rules')
def test_path_conversion_preserves_alias_meaning_and_explicit_namespaces(tmp_path):
    normal = tmp_path / 'ordinary'
    assert bundles._filesystem_path(normal) == extended(normal)
    assert bundles._filesystem_path(extended(normal)) == extended(normal)
    for path in (tmp_path / 'ordinary' / '..' / 'other', tmp_path / 'ordinary.', tmp_path / 'ordinary '):
        assert bundles._filesystem_path(path) == path
    for name in ('NUL', 'con.txt', 'COM1', 'LPT³', 'file:stream'):
        assert bundles._filesystem_path(tmp_path / name) == tmp_path / name
    # Pure spelling checks only: no device or network access.
    assert bundles._filesystem_path(Path(r'\\server\share\archive')) == Path(r'\\?\UNC\server\share\archive')
    assert bundles._filesystem_path(Path(r'\\.\pipe\example')) == Path(r'\\.\pipe\example')
