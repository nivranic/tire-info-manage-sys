"""Current trusted bootstrap; frozen bundles supply only fixed parser functions."""
from importlib.machinery import PathFinder, SourceFileLoader
import os
from pathlib import Path
import sys


class _SourceOnlyLoader(SourceFileLoader):
    def get_code(self, fullname):
        filename = self.get_filename(fullname)
        return self.source_to_code(self.get_data(filename), filename)


class _SourceOnlyFinder:
    _HOST_MODULES = {'parser_runtime', 'parser_limits', 'parser_bundles', 'parser_child'}

    def __init__(self, host_root, package_root):
        self.host_root = Path(host_root).resolve(strict=True)
        self.package_root = Path(package_root).resolve(strict=True)
        if not self.host_root.is_dir() or not self.package_root.is_dir():
            raise ImportError('parser_source_import_not_allowed')

    def find_spec(self, fullname, path=None, target=None):
        namespace, _, name = fullname.partition('.')
        if namespace not in {'_tire_parser_host', 'tire_api'}:
            return None
        if namespace == '_tire_parser_host':
            if name not in self._HOST_MODULES:
                raise ImportError('parser_source_import_not_allowed')
            root = self.host_root
            search = [str(root)]
            expected = {root / f'{name}.py'}
        else:
            parts = fullname.split('.')[1:]
            if any(not part.isidentifier() for part in parts):
                raise ImportError('parser_source_import_not_allowed')
            root = self.package_root
            module_path = root.joinpath(*parts)
            search = [str(module_path.parent)]
            expected = {module_path / '__init__.py'}
            if parts:
                expected.add(module_path.with_suffix('.py'))
        try:
            spec = PathFinder.find_spec(fullname, search, target)
            if spec is None or not isinstance(spec.loader, SourceFileLoader) or not isinstance(spec.origin, str):
                raise ImportError('parser_source_import_not_allowed')
            filename = Path(spec.origin)
            if (filename.suffix != '.py' or filename.absolute() not in expected
                    or not filename.resolve(strict=True).is_relative_to(root)):
                raise ImportError('parser_source_import_not_allowed')
            if spec.submodule_search_locations is not None:
                locations = list(spec.submodule_search_locations)
                if (namespace == '_tire_parser_host' or len(locations) != 1
                        or Path(locations[0]).resolve(strict=True) != filename.parent.resolve(strict=True)
                        or not Path(locations[0]).resolve(strict=True).is_relative_to(root)):
                    raise ImportError('parser_source_import_not_allowed')
            spec.loader = _SourceOnlyLoader(fullname, str(filename))
            return spec
        except (OSError, TypeError, ValueError):
            raise ImportError('parser_source_import_not_allowed') from None


def _install_source_only_finder(host_root, package_root):
    finder = _SourceOnlyFinder(host_root, package_root)
    sys.meta_path.insert(0, finder)
    sys.dont_write_bytecode = True
    sys.pycache_prefix = None
    return finder


def _host_runtime():
    # Keep current supervisor/limits code separate from the tire_api namespace
    # that will be imported from the selected immutable execution copy.
    import importlib
    import types
    package = types.ModuleType('_tire_parser_host')
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[package.__name__] = package
    return importlib.import_module('_tire_parser_host.parser_runtime')


def _check_imports(package_root):
    for name, module in tuple(sys.modules.items()):
        if name == 'tire_api' or name.startswith('tire_api.'):
            filename = getattr(module, '__file__', None)
            if filename is None or Path(filename).suffix != '.py' or not Path(filename).resolve().is_relative_to(package_root):
                raise ValueError('parser_import_outside_bundle')


def main():
    if sys.stdin.buffer.read(3) != b'GO\n':
        return 78
    # These argv values are constructed by the supervisor, never HTTP/JSON.
    if len(sys.argv) not in (4, 5) or sys.argv[-2] != '--execution-root':
        return 78
    dependencies = [Path(value).resolve(strict=True) for value in sys.argv[1:-2]]
    execution_root = Path(sys.argv[-1]).resolve(strict=True)
    if any(not value.is_dir() for value in dependencies) or execution_root != Path.cwd() / 'package':
        return 78
    # Explicitly precede site-packages, including a normally installed tire_api.
    sys.path[:0] = [str(execution_root), *map(str, dependencies)]
    _install_source_only_finder(Path(__file__).resolve().parent, execution_root / 'tire_api')
    host = _host_runtime()
    bundles = host.bundles
    try:
        from _tire_parser_host.parser_limits import apply_child_limits, python_network_guard
        limits_backend = apply_child_limits()
    except Exception:
        return 77
    python_network_guard()
    import base64
    import json

    raw = sys.stdin.buffer.read(host.MAX_PROTOCOL_BYTES + 1)
    if len(raw) > host.MAX_PROTOCOL_BYTES:
        return 78
    request = None
    package_root = execution_root / 'tire_api'
    try:
        request = host.strict_json(raw)
        expected_keys = {'protocol', 'run_id', 'source_id', 'parser_version', 'parser_digest', 'query', 'body_base64',
                         'manifest', 'bundle_id', 'execution_digest', 'deployment_revision', 'input_hash'}
        if not isinstance(request, dict) or set(request) != expected_keys or request['protocol'] != host.PROTOCOL:
            return 78
        if not isinstance(request['run_id'], str) or len(request['run_id']) != 32 or any(char not in '0123456789abcdef' for char in request['run_id']):
            return 78
        if request['deployment_revision'] is not None and (type(request['deployment_revision']) is not int or not 0 <= request['deployment_revision'] <= 2**53):
            return 78
        manifest = bundles.checked_manifest(request['manifest'], protocol=host.PROTOCOL, limits=host.limits())
        bundles.verify_tree(package_root, manifest)
        descriptor = host.descriptor_for_manifest(manifest, request['source_id'])
        if any(request[name] != descriptor[name] for name in ('bundle_id', 'parser_version', 'parser_digest', 'execution_digest')):
            return 79
        body_bytes = base64.b64decode(request['body_base64'], validate=True)
        if not 0 < len(body_bytes) <= host.MAX_BODY_BYTES:
            return 78
        body = body_bytes.decode('utf-8', errors='strict')
        query = request['query']
        allowed = host.query_fields(descriptor['target_kind'], query)
        if (not isinstance(query, dict) or set(query) - allowed
                or any(not isinstance(value, str) or len(value) > 256 for value in query.values())
                or descriptor['target_kind'] == 'vehicle' and not query.get('vehicle_id')
                or descriptor['target_kind'] == 'recall' and set(query) != allowed):
            return 78
        if request['input_hash'] != host.input_hash(request, body_bytes):
            return 79
        source_id = request['source_id']
        if source_id.startswith('michelin-'):
            from tire_api.adapters.michelin import parse_michelin_html
            _check_imports(package_root)
            region = {'michelin-us': 'US', 'michelin-uk': 'UK', 'michelin-fr': 'FR', 'michelin-de': 'DE', 'michelin-cn': 'CN'}[source_id]
            payload = parse_michelin_html(body, query, region=region)
        elif source_id == 'toyo-us':
            from tire_api.adapters.toyo import parse_html
            _check_imports(package_root)
            payload = parse_html(body, query)
        elif source_id == 'hankook-us':
            from tire_api.adapters.hankook import parse_html
            _check_imports(package_root)
            payload = parse_html(body, query)
        elif source_id == 'pirelli-us':
            from tire_api.adapters.pirelli import parse_html
            _check_imports(package_root)
            payload = parse_html(body, query)
        elif source_id == 'xiaomi-cn-vehicles':
            from tire_api.adapters.xiaomi import parse_config
            _check_imports(package_root)
            payload = parse_config(body, query['vehicle_id'])
        elif source_id == 'nhtsa-us-recalls':
            from tire_api.adapters.nhtsa import parse_json
            _check_imports(package_root)
            payload = parse_json(body, query)
        else:
            return 78
        _check_imports(package_root)
        bundles.verify_tree(package_root, manifest)
        if host.descriptor_for_manifest(manifest, source_id)['execution_digest'] != request['execution_digest']:
            return 79
        response = {'protocol': host.PROTOCOL, 'run_id': request['run_id'], 'ok': True, 'payload': payload,
                    'source_id': source_id, 'parser_version': descriptor['parser_version'],
                    'parser_digest': descriptor['parser_digest'], 'limits_backend': limits_backend,
                    **{key: request[key] for key in ('bundle_id', 'input_hash', 'execution_digest', 'deployment_revision')}}
    except bundles.BundleError as error:
        response = {'protocol': host.PROTOCOL, 'run_id': request.get('run_id') if isinstance(request, dict) else None,
                    'ok': False, 'error': error.code}
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        response = {'protocol': host.PROTOCOL, 'run_id': request.get('run_id') if isinstance(request, dict) else None,
                    'ok': False, 'error': 'parser_schema_changed'}
    except Exception:
        response = {'protocol': host.PROTOCOL, 'run_id': request.get('run_id') if isinstance(request, dict) else None,
                    'ok': False, 'error': 'parser_failed'}
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > host.MAX_OUTPUT_BYTES:
        return 80
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except BaseException:
        code = 78
    os._exit(code)
