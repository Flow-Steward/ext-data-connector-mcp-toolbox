#!/usr/bin/env python3
"""Start a variant's Toolbox binary once per prebuilt it offers.

    python3 scripts/smoke_variant.py <variant> [--binary build/<variant>/bin/linux-amd64/toolbox]

With no database behind the dummy settings, a healthy binary fails at
*connecting*. A binary missing a source or tool type fails earlier, while
parsing the prebuilt — that is what this catches, for every prebuilt of every
variant, so a change made for one database cannot silently drop another's.
"""

from __future__ import annotations

import argparse
import ast
import os
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_variant  # noqa: E402

ROOT = render_variant.ROOT
# What a binary missing a type, or a prebuilt it cannot load, reports. Anything
# else (a refused connection, a dummy value Toolbox rejects) means it got past
# type registration, which is all this checks.
BROKEN = ("unknown source type", "unknown tool type", "no prebuilt", "not a valid prebuilt", "environment variable not found")


def _main_py_literal(name: str) -> dict:
    tree = ast.parse((ROOT / "connector" / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return dict(ast.literal_eval(node.value))
    raise SystemExit(f"connector/main.py has no {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant")
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    arch = {"x86_64": "linux-amd64", "amd64": "linux-amd64", "aarch64": "linux-arm64", "arm64": "linux-arm64"}
    binary = args.binary or ROOT / "build" / args.variant / "bin" / arch[platform.machine().lower()] / "toolbox"
    aliases = render_variant.runtime_prebuilt_aliases()
    env_fields = _main_py_literal("TOOLBOX_ENV_FIELDS")
    failures = []
    for prebuilt in render_variant.load_variant(args.variant)["prebuilts"]:
        runtime = aliases.get(prebuilt, prebuilt)
        # Every setting the connector would pass, pointing at nothing.
        env = {**os.environ, **{name: ("1" if field == "port" else "smoke") for name, field in env_fields.get(runtime, {}).items()}}
        env.update({name: "127.0.0.1" for name, field in env_fields.get(runtime, {}).items() if field == "host"})
        try:
            done = subprocess.run(
                [str(binary), f"--prebuilt={runtime}", "--stdio"],
                env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
            )
            output = done.stdout + done.stderr
        except subprocess.TimeoutExpired:
            output = ""  # it started and waited for MCP input: types are all present
        broken = next((marker for marker in BROKEN if marker in output.lower()), "")
        status = f"BROKEN ({broken})" if broken else "ok"
        print(f"{args.variant}/{prebuilt} (toolbox --prebuilt={runtime}): {status}")
        if broken:
            failures.append(output.strip().splitlines()[-1] if output.strip() else broken)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
