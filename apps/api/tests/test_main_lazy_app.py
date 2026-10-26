"""Regression tests for the module-level default app export.

Each case executes the real main.py bytes in a fresh package-local module. The
real database and telemetry constructors are blocked before that execution, and
the default factory is replaced with an in-memory stub before resolving app.
"""

from contextlib import contextmanager
import importlib
import importlib.util
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


PROBE_NAME = "tire_api._main_lazy_app_test_probe"
PROBE_ATTRIBUTE = "_main_lazy_app_test_probe"
ABSENT = object()
LOCK_WAIT_SECONDS = 3
THREAD_JOIN_SECONDS = 10


class BoundedLock:
    """Keep the real lock semantics while bounding a broken recursion path."""

    def __init__(self, lock):
        self.lock = lock

    def __enter__(self):
        if not self.lock.acquire(timeout=LOCK_WAIT_SECONDS):
            raise TimeoutError("default app lock wait exceeded")
        return self

    def __exit__(self, _error_type, _error, _traceback):
        self.lock.release()


@contextmanager
def fresh_main():
    package = importlib.import_module("tire_api")
    db_module = importlib.import_module("tire_api.db")
    telemetry_module = importlib.import_module("tire_api.telemetry")
    source = Path(package.__file__).with_name("main.py")
    spec = importlib.util.spec_from_file_location(PROBE_NAME, source)
    if spec is None:
        raise AssertionError("main module spec unavailable")
    module: ModuleType = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(PROBE_NAME, ABSENT)
    previous_attribute = package.__dict__.get(PROBE_ATTRIBUTE, ABSENT)
    constructor_calls = {"database": 0, "telemetry": 0}

    def reject_database(_self, *_args, **_kwargs):
        constructor_calls["database"] += 1
        raise AssertionError("default Database constructed during import")

    def reject_telemetry(_self, *_args, **_kwargs):
        constructor_calls["telemetry"] += 1
        raise AssertionError("default TelemetryRuntime constructed during import")

    try:
        with patch.object(db_module.Database, "__init__", reject_database), patch.object(
                telemetry_module.TelemetryRuntime, "__init__", reject_telemetry):
            sys.modules[PROBE_NAME] = module
            package.__dict__[PROBE_ATTRIBUTE] = module
            exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)
            # A regressed owner check must fail within the test deadline instead
            # of leaving a worker blocked forever on the original non-reentrant lock.
            module.__dict__["_default_app_lock"] = BoundedLock(module.__dict__["_default_app_lock"])
            yield module, constructor_calls
    finally:
        if previous_module is ABSENT:
            sys.modules.pop(PROBE_NAME, None)
        else:
            sys.modules[PROBE_NAME] = previous_module
        if previous_attribute is ABSENT:
            package.__dict__.pop(PROBE_ATTRIBUTE, None)
        else:
            package.__dict__[PROBE_ATTRIBUTE] = previous_attribute


class TestMainLazyApp(unittest.TestCase):
    def test_import_does_not_construct_default_app(self):
        with fresh_main() as (module, constructor_calls):
            self.assertNotIn("app", module.__dict__)
            self.assertEqual(constructor_calls, {"database": 0, "telemetry": 0})
            self.assertTrue(callable(module.__dict__["create_app"]))

    def test_first_attribute_access_creates_and_caches_once(self):
        with fresh_main() as (module, constructor_calls):
            marker = object()
            calls = []

            def factory():
                calls.append(1)
                return marker

            module.create_app = factory
            self.assertNotIn("app", module.__dict__)
            self.assertIs(getattr(module, "app"), marker)
            self.assertIs(getattr(module, "app"), marker)
            self.assertIs(module.__dict__["app"], marker)
            self.assertEqual(len(calls), 1)
            self.assertEqual(constructor_calls, {"database": 0, "telemetry": 0})

    def test_first_from_import_uses_the_same_cache(self):
        with fresh_main() as (module, constructor_calls):
            marker = object()
            calls = []

            def factory():
                calls.append(1)
                return marker

            module.create_app = factory
            self.assertNotIn("app", module.__dict__)
            from tire_api._main_lazy_app_test_probe import app as imported_app

            self.assertIs(imported_app, marker)
            self.assertIs(getattr(module, "app"), marker)
            self.assertIs(module.__dict__["app"], marker)
            self.assertEqual(len(calls), 1)
            self.assertEqual(constructor_calls, {"database": 0, "telemetry": 0})

    def test_concurrent_access_calls_factory_once(self):
        with fresh_main() as (module, constructor_calls):
            marker = object()
            gate = threading.Barrier(8)
            count_lock = threading.Lock()
            count = 0
            results = []
            failures = []

            def factory():
                nonlocal count
                with count_lock:
                    count += 1
                time.sleep(0.05)
                return marker

            def worker():
                try:
                    gate.wait(timeout=5)
                    results.append(getattr(module, "app"))
                except BaseException as error:
                    failures.append(type(error).__name__)

            module.create_app = factory
            threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
            started = []
            deadline = time.monotonic() + THREAD_JOIN_SECONDS
            try:
                for thread in threads:
                    thread.start()
                    started.append(thread)
                for thread in started:
                    thread.join(timeout=max(0, deadline - time.monotonic()))
            finally:
                gate.abort()
                for thread in started:
                    thread.join(timeout=max(0, deadline - time.monotonic()))
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(failures, [])
            self.assertEqual(len(results), 8)
            self.assertTrue(all(value is marker for value in results))
            self.assertEqual(count, 1)
            self.assertEqual(constructor_calls, {"database": 0, "telemetry": 0})

    def test_failed_factory_is_not_cached_and_can_retry(self):
        with fresh_main() as (module, constructor_calls):
            marker = object()
            calls = []

            def factory():
                calls.append(1)
                if len(calls) == 1:
                    raise ValueError("controlled first failure")
                return marker

            module.create_app = factory
            with self.assertRaisesRegex(ValueError, "controlled first failure"):
                getattr(module, "app")
            self.assertNotIn("app", module.__dict__)
            self.assertIs(getattr(module, "app"), marker)
            self.assertEqual(len(calls), 2)
            self.assertEqual(constructor_calls, {"database": 0, "telemetry": 0})

    def test_same_thread_recursion_is_bounded_and_rejected(self):
        with fresh_main() as (module, constructor_calls):
            outcome = []

            def recursive_factory():
                return getattr(module, "app")

            def worker():
                try:
                    getattr(module, "app")
                except BaseException as error:
                    outcome.append(type(error))
                else:
                    outcome.append(None)

            module.create_app = recursive_factory
            thread = threading.Thread(target=worker, daemon=True)
            started = False
            deadline = time.monotonic() + THREAD_JOIN_SECONDS
            try:
                thread.start()
                started = True
                thread.join(timeout=max(0, deadline - time.monotonic()))
            finally:
                if started:
                    thread.join(timeout=max(0, deadline - time.monotonic()))
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome, [RuntimeError])
            self.assertNotIn("app", module.__dict__)
            self.assertEqual(constructor_calls, {"database": 0, "telemetry": 0})

    def test_unknown_attribute_is_rejected_without_factory_call(self):
        with fresh_main() as (module, constructor_calls):
            calls = []

            def factory():
                calls.append(1)
                return object()

            module.create_app = factory
            with self.assertRaises(AttributeError):
                getattr(module, "unknown_lazy_app_attribute")
            self.assertEqual(calls, [])
            self.assertNotIn("app", module.__dict__)
            self.assertEqual(constructor_calls, {"database": 0, "telemetry": 0})


class TestRegressionRunnerCleanup(unittest.TestCase):
    """Cleanup must never resolve the lazy default application export."""

    @staticmethod
    def runner():
        source = Path(__file__).resolve().parents[3] / "scripts/run_api_worker_regression.py"
        spec = importlib.util.spec_from_file_location("r134_regression_cleanup_probe", source)
        if spec is None or spec.loader is None:
            raise AssertionError("regression runner spec unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_uncached_module_does_not_resolve_lazy_export(self):
        module = ModuleType("cleanup_uncached")
        resolutions = []

        def resolve(name):
            resolutions.append(name)
            raise AssertionError("cleanup resolved a lazy export")

        module.__getattr__ = resolve
        self.runner().dispose_cached_default_app(module)
        self.assertEqual(resolutions, [])
        self.assertNotIn("app", vars(module))

    def test_existing_cached_instance_is_disposed_once(self):
        module = ModuleType("cleanup_cached")
        disposed = []
        module.app = SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(
            engine=SimpleNamespace(dispose=lambda: disposed.append(True)))))
        self.runner().dispose_cached_default_app(module)
        self.assertEqual(disposed, [True])

    def test_absent_or_none_cached_instance_is_ignored(self):
        runner = self.runner()
        runner.dispose_cached_default_app(None)
        module = ModuleType("cleanup_none")
        module.app = None
        runner.dispose_cached_default_app(module)

    def test_disposal_failure_reaches_runner_failure_handling(self):
        expected = RuntimeError("controlled cached disposal failure")

        def dispose():
            raise expected

        module = ModuleType("cleanup_dispose_failure")
        module.app = SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(
            engine=SimpleNamespace(dispose=dispose))))
        with self.assertRaises(RuntimeError) as raised:
            self.runner().dispose_cached_default_app(module)
        self.assertIs(raised.exception, expected)
