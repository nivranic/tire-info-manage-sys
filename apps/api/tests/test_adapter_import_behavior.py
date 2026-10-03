"""Import boundaries in fresh interpreters, independent of pytest's module cache.

These probes import local source only. They do not fetch sources, invoke a
Parser, create a database, or provide performance/OS-isolation acceptance.
"""
import json
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest


API_ROOT = Path(__file__).resolve().parents[1]
HEAVY_IMPORTS = (
    'tire_api.adapters.registry', 'tire_api.captures', 'tire_api.db',
    'fastapi', 'sqlalchemy', 'aiohttp',
)


def fresh_import(script, *arguments):
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-c', dedent(script), str(API_ROOT), *arguments],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('adapter,parser', [
    ('pirelli', 'parse_html'), ('toyo', 'parse_html'),
    ('hankook', 'parse_html'), ('michelin', 'parse_michelin_html'),
])
def test_leaf_parser_import_does_not_load_online_or_database_dependencies(adapter, parser):
    observed = fresh_import('''
        import importlib
        import json
        import sys

        sys.path.insert(0, sys.argv[1])
        package = importlib.import_module('tire_api.adapters')
        before = sorted(sys.modules)
        leaf = importlib.import_module('tire_api.adapters.' + sys.argv[2])
        print(json.dumps({
            'before': before,
            'after': sorted(sys.modules),
            'parser_callable': callable(getattr(leaf, sys.argv[3])),
            'package_leaf_is_module': getattr(package, sys.argv[2]) is leaf,
        }))
    ''', adapter, parser)
    assert observed['parser_callable'] and observed['package_leaf_is_module']
    for phase in ('before', 'after'):
        forbidden = [name for name in observed[phase]
                     if any(name == prefix or name.startswith(prefix + '.') for prefix in HEAVY_IMPORTS)]
        assert forbidden == [], forbidden


@pytest.mark.parametrize('first_access', ['attribute', 'from_import', 'star_import'])
def test_registry_access_forms_load_the_same_complete_registry(first_access):
    observed = fresh_import('''
        import importlib
        import json
        import sys

        sys.path.insert(0, sys.argv[1])
        package = importlib.import_module('tire_api.adapters')
        initial_registry_loaded = 'tire_api.adapters.registry' in sys.modules
        mode = sys.argv[2]
        if mode == 'attribute':
            first = package.registry
        elif mode == 'from_import':
            from tire_api.adapters import registry as first
        else:
            namespace = {}
            exec('from tire_api.adapters import *', namespace)
            first = namespace['registry']

        from tire_api.adapters import registry as imported
        namespace = {}
        exec('from tire_api.adapters import *', namespace)
        direct = importlib.import_module('tire_api.adapters.registry')
        print(json.dumps({
            'initial_registry_loaded': initial_registry_loaded,
            'same_module': first is imported is namespace['registry'] is package.registry is direct,
            'sources': sorted(first.SPECS),
            'pirelli_requires_size': first.SPECS['pirelli-us'].requires_size,
            'advertised_sources': sorted(row['id'] for row in first.sources()),
        }))
    ''', first_access)
    assert observed['initial_registry_loaded'] is False
    assert observed['same_module'] and observed['pirelli_requires_size']
    assert observed['sources'] == [
        'hankook-us', 'michelin-cn', 'michelin-de', 'michelin-fr',
        'michelin-uk', 'michelin-us', 'pirelli-us', 'toyo-us',
    ]
    assert observed['advertised_sources'] == [
        'eprel', 'hankook-us', 'michelin-cn', 'michelin-de', 'michelin-fr',
        'michelin-uk', 'michelin-us', 'nhtsa-us-recalls', 'pirelli-us', 'toyo-us',
    ]


def test_unknown_attribute_raises_without_loading_registry():
    observed = fresh_import('''
        import importlib
        import json
        import sys

        sys.path.insert(0, sys.argv[1])
        package = importlib.import_module('tire_api.adapters')
        missing = 'not_an_adapter'
        try:
            getattr(package, missing)
        except AttributeError:
            rejected = True
        else:
            rejected = False
        print(json.dumps({
            'rejected': rejected,
            'has_missing': hasattr(package, missing),
            'registry_loaded': 'tire_api.adapters.registry' in sys.modules,
        }))
    ''')
    assert observed == {'rejected': True, 'has_missing': False, 'registry_loaded': False}
