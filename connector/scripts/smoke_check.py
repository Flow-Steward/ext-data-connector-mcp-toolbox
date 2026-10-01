#!/usr/bin/env python3
"""Stateless smoke check for the Toolbox Dataset Connector."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
FAKE_TOOLBOX = ROOT / "fixtures" / "fake_toolbox.py"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module(ROOT / "main.py", "toolbox_dataset_connector_main")
    module._TOOLBOX_COMMAND_OVERRIDE = [sys.executable, str(FAKE_TOOLBOX)]
    connection = {
        "prebuilt": "postgres",
        "host": "postgres.test",
        "port": "5432",
        "database": "toolbox_test",
        "user": "toolbox_test",
    }
    request = {
        "mode": "action",
        "action": {
            "action_id": "introspect_schema",
            "input": {"connection_config": connection},
        },
    }
    payload = module.handle_action(request)
    if payload.get("ok") is not True:
        raise AssertionError(payload)
    snapshot = payload["result"]["schema_snapshot"]
    resources = sorted(row["resource_id"] for row in snapshot["resources"])
    if not {"customers", "orders"}.issubset(resources):
        raise AssertionError(resources)
    print(json.dumps({"ok": True, "resources": resources}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
