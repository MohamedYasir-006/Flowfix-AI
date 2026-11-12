"""Import-integrity tests.

Every module must import cleanly in a *fresh interpreter*. This catches missing
imports that a test suite can mask when another test imports a symbol into
shared state before the module under test loads — exactly how a missing
``PolicyUpdate`` import shipped to the container while all tests passed.
"""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys

import pytest

import app


def iter_modules():
    for module_info in pkgutil.walk_packages(app.__path__, prefix=f"{app.__name__}."):
        yield module_info.name


@pytest.mark.parametrize("module_name", sorted(iter_modules()))
def test_module_imports_in_fresh_interpreter(module_name):
    """Import the module in a clean Python process.

    A subprocess guarantees no prior test has populated the import system, so a
    module that only works because something else imported it first will fail.
    ``typing.get_type_hints`` then resolves every annotation: with
    ``from __future__ import annotations`` a wrong or missing name in an
    annotation is stored as a string and only fails when something actually
    resolves it, which is how a missing import can ship unnoticed.
    """
    import os

    env = dict(os.environ)
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = backend_root + os.pathsep + env.get("PYTHONPATH", "")
    probe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_annotation_probe.py")
    result = subprocess.run(
        [sys.executable, probe_path, module_name],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=backend_root,
    )
    assert result.returncode == 0, (
        f"{module_name} failed to import cleanly in a fresh interpreter:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_main_app_imports_in_fresh_interpreter():
    import os

    env = dict(os.environ)
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = backend_root + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print(len(app.openapi()['paths']))"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=backend_root,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) > 10


def test_all_routers_registered():
    """Every documented blueprint endpoint must exist in the OpenAPI schema.

    This FastAPI version mounts routers lazily, so ``app.routes`` does not
    expose their paths until the schema is built.
    """
    from app.main import app as fastapi_app

    paths = set(fastapi_app.openapi()["paths"].keys())
    expected = {
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/agents",
        "/api/v1/tools",
        "/api/v1/policies",
        "/api/v1/decisions/evaluate",
        "/api/v1/approvals",
        "/api/v1/events",
        "/api/v1/overview",
        "/api/v1/users",
        "/api/v1/settings",
    }
    missing = expected - paths
    assert not missing, f"missing routes: {sorted(missing)}"
