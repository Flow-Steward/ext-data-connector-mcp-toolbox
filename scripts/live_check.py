#!/usr/bin/env python3
"""Run a rendered variant against a real database, through its own runtime.

    python3 scripts/live_check.py <variant> --prebuilt postgres \\
        --host 127.0.0.1 --port 5432 --database shop --user reader --password-env DB_PASSWORD

Loads the variant's ``main.py`` exactly as Flow Steward does and calls
``introspect_schema`` and a parameterised ``execute_template`` against a
``products`` table the caller seeded (see .github/workflows/ci.yml). The
parameter goes through the driver-binding patch this repository applies to
Toolbox, so a regression there fails here, for that database only.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent


def write_roundtrip(runtime: Any, common: dict[str, Any]) -> None:
    """Insert/update/read/delete only a uniquely owned fixture row."""
    sku = "fs-" + uuid4().hex[:16]
    scope = {
        "group_id": None,
        "for_each_id": None,
        "step_id": "write_roundtrip",
        "step_execution_id": str(uuid4()),
        "test_mode": False,
    }
    connection = {
        "connection_id": "live-check",
        "connection_type": "toolbox_sql_writer",
        "config": common["connection_config"],
        "secrets": common["secret_refs"]["values"],
    }

    def write(statement: str, params: dict[str, Any]) -> None:
        response = runtime.handle_request(
            {
                "contract_version": "extension_host_v2",
                "runtime_context": scope,
                "mode": "action",
                "action": {
                    "action_id": "execute_write",
                    "target": {"connection": connection},
                    "input": {
                        "connection_ref": "live-check",
                        "sql": statement,
                        "params": params,
                        "param_schema": {
                            "type": "object",
                            "properties": {
                                "sku": {"type": "string"},
                                "name": {"type": "string"},
                                "stock": {"type": "integer"},
                            },
                        },
                    },
                },
            }
        )
        assert response["ok"] is True, response
        assert response["external_effect_status"] == "succeeded", response
        assert response["result"]["rows"] == [], response

    def read() -> list[dict[str, Any]]:
        response = runtime.handle_request(
            {
                "contract_version": "extension_host_v2",
                "runtime_context": scope,
                "mode": "action",
                "action": {
                    "action_id": "execute_template",
                    "input": {
                        **common,
                        "dataset": {
                            "resource_scope_jsonb": {
                                "version": 1,
                                "resources": [{"resource_id": "products", "columns": None}],
                            }
                        },
                        "query_template": {
                            "query_definition_jsonb": {
                                "sql": "SELECT sku, stock FROM products WHERE sku = :sku"
                            },
                            "param_schema_jsonb": {
                                "type": "object",
                                "properties": {"sku": {"type": "string"}},
                            },
                        },
                        "params": {"sku": sku},
                        "limits": {"max_runtime_rows": 5},
                    },
                },
            }
        )
        assert response["ok"] is True, response
        return list(response["result"]["rows"])

    try:
        write(
            "INSERT INTO products (sku, name, stock) VALUES (:sku, :name, :stock)",
            {"sku": sku, "name": "O'Reilly; UPDATE products SET stock = 999", "stock": 1},
        )
        assert read() == [{"sku": sku, "stock": 1}]
        write("UPDATE products SET stock = :stock WHERE sku = :sku", {"sku": sku, "stock": 2})
        assert read() == [{"sku": sku, "stock": 2}]
    finally:
        write("DELETE FROM products WHERE sku = :sku", {"sku": sku})
    assert read() == []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant")
    parser.add_argument("--prebuilt", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password-env", required=True)
    args = parser.parse_args()
    [source] = [
        path for path in (ROOT / "build" / args.variant).iterdir() if (path / "main.py").is_file()
    ]
    for target in ("linux-amd64", "linux-arm64"):
        binary = ROOT / "build" / args.variant / "bin" / target / "toolbox"
        link = source / "bin" / target / "toolbox"
        if binary.is_file() and not link.exists():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(binary)
    spec = importlib.util.spec_from_file_location("variant_runtime", source / "main.py")
    assert spec and spec.loader
    sys.path.insert(0, str(source))
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)

    common = {
        "connection_config": {
            "prebuilt": args.prebuilt,
            "host": args.host,
            "port": args.port,
            "database": args.database,
            "user": args.user,
        },
        "secret_refs": {"values": {"password": os.environ[args.password_env]}},
    }
    introspection = runtime.handle_action(
        {"mode": "action", "action": {"action_id": "introspect_schema", "input": common}}
    )
    assert introspection["ok"] is True, introspection
    tables = {row["resource_id"] for row in introspection["result"]["resources"]}
    assert "products" in tables, f"introspection found {sorted(tables)}"

    execution = runtime.handle_action(
        {
            "mode": "action",
            "action": {
                "action_id": "execute_template",
                "input": {
                    **common,
                    "dataset": {
                        "resource_scope_jsonb": {
                            "version": 1,
                            "resources": [{"resource_id": "products", "columns": None}],
                        }
                    },
                    "query_template": {
                        "query_definition_jsonb": {
                            "sql": "SELECT sku, stock FROM products WHERE sku = :sku"
                        },
                        "param_schema_jsonb": {
                            "type": "object",
                            "properties": {"sku": {"type": "string"}},
                            "required": ["sku"],
                        },
                    },
                    "params": {"sku": "A-1"},
                    "limits": {"max_runtime_rows": 5},
                },
            },
        }
    )
    assert execution["ok"] is True, execution
    assert execution["result"]["rows"] == [{"sku": "A-1", "stock": 12}], execution["result"]["rows"]
    write_roundtrip(runtime, common)
    print(
        f"{args.variant}/{args.prebuilt}: introspection, bound read and INSERT/UPDATE/DELETE roundtrip passed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
