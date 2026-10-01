#!/usr/bin/env python3
"""Fail fast when the family is inconsistent, before anything is built.

    python3 scripts/check_family.py

* every connection type the shared connector offers is in exactly one variant;
* every variant names prebuilts the connector knows, and renders to an extension
  whose manifest, connection schema and variant.json offer exactly those;
* ids, folders and service accounts are unique across the family;
* every variant has committed binary sums.

Nothing here is configured by hand per variant, so nothing can be forgotten:
a new variant file is checked the moment it exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_variant  # noqa: E402

ROOT = render_variant.ROOT


def main() -> int:
    problems: list[str] = []
    manifest = yaml.safe_load((ROOT / "connector" / "extension.yaml").read_text(encoding="utf-8"))
    catalog = manifest["runtime"]["extension_contract_v2"]["dataset_connectors"][0]["connector_catalog"]
    offered = [entry["preset_config"]["prebuilt"] for entry in catalog]
    variants = sorted(path.stem for path in (ROOT / "variants").glob("*.yaml"))
    if not variants:
        problems.append("variants/ is empty")

    owner: dict[str, str] = {}
    for name in variants:
        for prebuilt in render_variant.load_variant(name)["prebuilts"]:
            if prebuilt in owner:
                problems.append(f"{prebuilt} is in both variants/{owner[prebuilt]}.yaml and variants/{name}.yaml")
            owner[prebuilt] = name
    for prebuilt in offered:
        if prebuilt not in owner:
            problems.append(f"connector type {prebuilt} is in no variant; add it to variants/<name>.yaml")
    for prebuilt, name in owner.items():
        if prebuilt not in offered:
            problems.append(f"variants/{name}.yaml offers {prebuilt}, which connector/extension.yaml does not")

    seen: dict[str, str] = {}
    for name in variants:
        if problems:
            break
        out = render_variant.render(name)
        rendered = yaml.safe_load((out / "extension.yaml").read_text(encoding="utf-8"))
        prebuilts = render_variant.load_variant(name)["prebuilts"]
        connector = rendered["runtime"]["extension_contract_v2"]["dataset_connectors"][0]
        offered_here = sorted(entry["preset_config"]["prebuilt"] for entry in connector["connector_catalog"])
        schema = yaml.safe_load((out / "schemas" / "config.schema.yaml").read_text(encoding="utf-8"))
        variant_json = json.loads((out / "variant.json").read_text(encoding="utf-8"))
        for label, values in (
            ("manifest connector_catalog", offered_here),
            ("manifest connection_schema enum", sorted(connector["connection_schema"]["properties"]["prebuilt"]["enum"])),
            ("config.schema.yaml enum", sorted(schema["properties"]["prebuilt"]["enum"])),
            ("variant.json", sorted(variant_json["prebuilts"])),
        ):
            if values != sorted(prebuilts):
                problems.append(f"{name}: {label} offers {values}, expected {sorted(prebuilts)}")
        for label, value in (
            ("extension_id", rendered["extension_id"]),
            ("folder", out.name),
            ("service account", rendered["machine_auth"]["service_account_key"]),
        ):
            if value in seen:
                problems.append(f"{name}: {label} {value} is also used by {seen[value]}")
            seen[value] = name
        if rendered["version"] != manifest["version"]:
            problems.append(f"{name}: version {rendered['version']} differs from the family's {manifest['version']}")
        if not (ROOT / "sums" / f"{name}.sha256").is_file():
            problems.append(f"{name}: sums/{name}.sha256 is missing; build it and commit the sums")

    if problems:
        print("Family check failed:\n" + "\n".join(f"- {p}" for p in problems), file=sys.stderr)
        return 1
    print(f"Family OK: {len(variants)} variants cover {len(offered)} connection types, version {manifest['version']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
