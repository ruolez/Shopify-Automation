import sys
import types

import pytest

from run_all_migrations import MIGRATION_ORDER, apply_migration


FAKE_MIGRATION = "zz_fake_runner_probe"


@pytest.fixture
def fake_migration_module():
    module = types.ModuleType(f"migrations.{FAKE_MIGRATION}")
    module.calls = []
    module.run_migration = lambda: module.calls.append("ran")
    sys.modules[module.__name__] = module
    yield module
    sys.modules.pop(module.__name__, None)


def test_apply_migration_executes_run_migration(fake_migration_module):
    assert apply_migration(FAKE_MIGRATION) is True
    assert fake_migration_module.calls == ["ran"]


def test_apply_migration_without_run_migration_only_marks():
    name = "zz_fake_runner_noop"
    sys.modules[f"migrations.{name}"] = types.ModuleType(f"migrations.{name}")
    try:
        assert apply_migration(name) is False
    finally:
        sys.modules.pop(f"migrations.{name}", None)


def test_apply_migration_for_missing_module_only_marks():
    assert apply_migration("zz_fake_runner_missing_module") is False
