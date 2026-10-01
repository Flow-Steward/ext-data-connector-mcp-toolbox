#!/usr/bin/env python3
"""Render one variant of the connector as its own Flow Steward extension.

    python3 scripts/render_variant.py <variant>   ->  build/<variant>/<folder>/

``connector/`` holds the one shared implementation, written for every database
Google MCP Toolbox offers. A variant (``variants/<name>.yaml``) becomes the
extension ``flowsteward.data-connector-mcp-toolbox-<name>``: the shared files
with that identity, and a manifest and connection schema that offer only the
variant's prebuilt configurations — the ones its binary was compiled for.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONNECTOR = ROOT / "connector"
ID_PREFIX = "flowsteward.data-connector-mcp-toolbox-"

# The shared connector's own identity, replaced in every text file it ships.
_SOURCE_ID = "flowsteward.toolbox-dataset-connector"
_SOURCE_FOLDER = "flowsteward_toolbox_dataset_connector"
_SOURCE_SERVICE_ACCOUNT = "svc_ext_toolbox_dataset_connector"
_TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".md", ".toml", ".txt"}


def folder_name(extension_id: str) -> str:
    return extension_id.replace(".", "_").replace("-", "_")


def runtime_prebuilt_aliases() -> dict[str, str]:
    """The connector's own map from a connection type to the Toolbox prebuilt it runs.

    MariaDB, for one, runs on Toolbox's MySQL prebuilt. Read from ``main.py`` so
    the build compiles what the runtime will actually start.
    """
    tree = ast.parse((CONNECTOR / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TOOLBOX_RUNTIME_PREBUILT_ALIASES"
            for target in node.targets
        ):
            return dict(ast.literal_eval(node.value))
    return {}


def load_variant(name: str) -> dict:
    variant = yaml.safe_load((ROOT / "variants" / f"{name}.yaml").read_text(encoding="utf-8"))
    if variant.get("name") != name or not variant.get("prebuilts"):
        sys.exit(f"variants/{name}.yaml must name itself '{name}' and list prebuilts")
    return variant


def _filter_prebuilt_enum(schema: dict, prebuilts: list[str]) -> None:
    """Offer only this variant's prebuilts in a schema's ``properties.prebuilt.enum``."""
    prebuilt = (schema.get("properties") or {}).get("prebuilt") or {}
    if isinstance(prebuilt.get("enum"), list):
        unknown = sorted(set(prebuilts) - set(prebuilt["enum"]))
        if unknown:
            sys.exit(f"the shared connector does not support prebuilts {unknown}")
        prebuilt["enum"] = [value for value in prebuilt["enum"] if value in prebuilts]


def render(name: str) -> Path:
    variant = load_variant(name)
    prebuilts = list(variant["prebuilts"])
    extension_id = ID_PREFIX + name
    folder = folder_name(extension_id)
    out = ROOT / "build" / name / folder
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(CONNECTOR, out, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))

    for path in out.rglob("*"):
        if path.is_file() and path.suffix in _TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            renamed = (
                text.replace(_SOURCE_ID, extension_id)
                .replace(_SOURCE_FOLDER, folder)
                .replace(_SOURCE_SERVICE_ACCOUNT, "svc_ext_" + folder.removeprefix("flowsteward_"))
            )
            if renamed != text:
                path.write_text(renamed, encoding="utf-8")

    manifest_path = out / "extension.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["display_name"] = variant["display_name"]
    manifest["description"] = variant["summary"]
    listing = manifest.setdefault("listing", {})
    listing["summary"] = variant["summary"]
    listing["tags"] = sorted({*listing.get("tags", []), *prebuilts})
    for connector in manifest["runtime"]["extension_contract_v2"]["dataset_connectors"]:
        connector["source_extension_name"] = variant["display_name"]
        catalog = [
            entry for entry in connector["connector_catalog"] if entry["preset_config"]["prebuilt"] in prebuilts
        ]
        missing = sorted(set(prebuilts) - {entry["preset_config"]["prebuilt"] for entry in catalog})
        if missing:
            sys.exit(f"the shared connector catalog has no entry for {missing}")
        connector["connector_catalog"] = catalog
        _filter_prebuilt_enum(connector.get("connection_schema") or {}, prebuilts)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")

    schema_path = out / "schemas" / "config.schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    _filter_prebuilt_enum(schema, prebuilts)
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # Read by connector/main.py: the runtime offers what the binary was built for.
    (out / "variant.json").write_text(
        json.dumps({"prebuilts": prebuilts, "display_name": variant["display_name"]}, indent=2) + "\n",
        encoding="utf-8",
    )

    aliases = runtime_prebuilt_aliases()
    toolbox_prebuilts = sorted({aliases.get(prebuilt, prebuilt) for prebuilt in prebuilts})

    # Provenance names this variant's build, and the package carries the sums
    # its binaries must match (sums/<variant>.sha256, committed and verified).
    provenance_path = out / "THIRD_PARTY.yml"
    provenance = yaml.safe_load(provenance_path.read_text(encoding="utf-8"))
    build = provenance.setdefault("build", {})
    build["script"] = "scripts/build_toolbox.sh (github.com/Flow-Steward/ext-data-connector-mcp-toolbox)"
    build.pop("excluded_native_sources", None)
    build["registered_prebuilts"] = toolbox_prebuilts
    provenance_path.write_text(yaml.safe_dump(provenance, sort_keys=False, allow_unicode=True), encoding="utf-8")
    sums = ROOT / "sums" / f"{name}.sha256"
    if sums.is_file():
        shutil.copyfile(sums, out / "SHA256SUMS")
    # What scripts/build_toolbox.sh compiles for: the prebuilts the runtime starts.
    (ROOT / "build" / name / "toolbox-prebuilts.txt").write_text(" ".join(toolbox_prebuilts) + "\n")

    print(f"{out.relative_to(ROOT)}: {extension_id} offering {', '.join(prebuilts)}")
    return out


if __name__ == "__main__":
    for variant_name in sys.argv[1:] or sys.exit("usage: render_variant.py <variant>..."):
        render(variant_name)
