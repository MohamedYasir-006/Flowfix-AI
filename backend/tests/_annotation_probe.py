"""Probe script used by test_imports.py.

Imports a module in a fresh interpreter, then resolves the type hints of every
function and class *defined in that module*. With
``from __future__ import annotations`` a missing or wrong name in an annotation
is stored as a string and only fails when resolved, so this catches mistakes
that a plain import would miss.

Usage: python _annotation_probe.py <module.name>
"""

from __future__ import annotations

import inspect
import sys
import typing


def main(module_name: str) -> int:
    module = __import__(module_name, fromlist=["__name__"])

    for name, obj in vars(module).items():
        # Only check objects defined here; imported SQLAlchemy/FastAPI symbols
        # have annotations that reference their own modules.
        if inspect.isfunction(obj):
            if obj.__module__ != module_name:
                continue
        elif inspect.isclass(obj):
            if obj.__module__ != module_name:
                continue
        else:
            continue

        try:
            typing.get_type_hints(obj)
        except Exception as exc:  # noqa: BLE001 - any failure is the finding
            print(f"{module_name}.{name}: {type(exc).__name__}: {exc}")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
