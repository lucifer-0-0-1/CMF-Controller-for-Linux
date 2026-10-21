"""Run all unit tests in the tests directory with fixture support."""
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on sys.path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tests"))

import test_engine
import test_motion
import test_platform_config
import test_settings
import test_shortcuts
import test_volume_source
import test_linux_platform

modules = [
    test_engine,
    test_motion,
    test_platform_config,
    test_settings,
    test_shortcuts,
    test_volume_source,
    test_linux_platform,
]


class MonkeyPatch:
    def __init__(self):
        self._setattr_undo = []
        self._setenv_undo = []

    def setattr(self, target, name, value, raising=True):
        old = getattr(target, name, None)
        self._setattr_undo.append((target, name, old))
        setattr(target, name, value)

    def setenv(self, key, value):
        old = os.environ.get(key)
        self._setenv_undo.append((key, old))
        os.environ[key] = value

    def undo(self):
        for target, name, old in reversed(self._setattr_undo):
            setattr(target, name, old)
        for key, old in reversed(self._setenv_undo):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


passed = 0
failed = 0
errors = []

for mod in modules:
    mod_name = mod.__name__
    print(f"\nRunning {mod_name}...")

    # Run unittest.TestCase classes if present
    suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
    if suite.countTestCases() > 0:
        runner = unittest.TextTestRunner(verbosity=1)
        res = runner.run(suite)
        passed += res.testsRun - len(res.failures) - len(res.errors)
        failed += len(res.failures) + len(res.errors)
        for f in res.failures + res.errors:
            errors.append(f"{mod_name}: {f[0]} -> {f[1]}")

    # Run standalone test_ functions
    for name, obj in inspect.getmembers(mod):
        if name.startswith("test_") and inspect.isfunction(obj):
            params = inspect.signature(obj).parameters
            kwargs = {}
            temp_dir = None
            mp = None

            if "tmp_path" in params:
                temp_dir = tempfile.TemporaryDirectory()
                kwargs["tmp_path"] = Path(temp_dir.name)
            if "monkeypatch" in params:
                mp = MonkeyPatch()
                kwargs["monkeypatch"] = mp

            try:
                obj(**kwargs)
                passed += 1
                sys.stdout.write(".")
                sys.stdout.flush()
            except Exception as ex:
                failed += 1
                sys.stdout.write("F")
                sys.stdout.flush()
                errors.append(f"{mod_name}.{name}: {ex}")
            finally:
                if mp:
                    mp.undo()
                if temp_dir:
                    temp_dir.cleanup()

print(f"\n\n==========================================")
print(f"Test Results: {passed} passed, {failed} failed")
if errors:
    print("\nErrors / Failures:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
else:
    print("ALL TESTS PASSED SUCCESSFULLY!")
    sys.exit(0)
