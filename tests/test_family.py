"""Repository-level guarantees, independent of any one variant."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_the_build_pins_toolbox_go_and_the_build_epoch() -> None:
    script = (ROOT / "scripts" / "build_toolbox.sh").read_text(encoding="utf-8")

    assert "TOOLBOX_TAG=v1.3.0" in script
    assert "TOOLBOX_COMMIT=b0010060a939455d91e4f8ba62dc3e72b1892469" in script
    assert "golang:1.26.2-bookworm@sha256:" in script
    assert "SOURCE_DATE_EPOCH=" in script
    assert "CGO_ENABLED=0" in script
    assert "-trimpath" in script and "-buildid=" in script
    assert 'git apply "/out/$PATCH"' in script


def test_the_family_is_consistent() -> None:
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_family.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr

    for variant_path in sorted((ROOT / "variants").glob("*.yaml")):
        name = variant_path.stem
        [bundle] = (ROOT / "build" / name).glob("flowsteward_*")
        manifest = yaml.safe_load((bundle / "extension.yaml").read_text())
        actions = yaml.safe_load((bundle / "ui/actions/actions.yaml").read_text())["actions"]
        contract = manifest["runtime"]["extension_contract_v2"]
        write_enabled = name in {"postgres", "mysql", "mssql"}
        assert any(row["action_id"] == "execute_write" for row in actions) is write_enabled
        assert (
            any(row["operation_id"] == "execute_write" for row in contract["operation_manifest"])
            is write_enabled
        )
        if write_enabled:
            [writer] = contract["connection_types"]
            offered = yaml.safe_load(variant_path.read_text())["prebuilts"]
            assert set(writer["config_schema"]["properties"]["prebuilt"]["enum"]) == set(offered)
            assert manifest["external_effects"][0]["operation_id"] == "execute_write"
        else:
            assert not contract.get("connection_types")
            assert not manifest.get("external_effects")
        smoke = subprocess.run(
            [sys.executable, "scripts/smoke_check.py"],
            cwd=bundle,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(bundle)},
        )
        assert smoke.returncode == 0, smoke.stdout + smoke.stderr


def test_every_variant_pins_both_runtime_targets() -> None:
    for variant in sorted((ROOT / "variants").glob("*.yaml")):
        sums = (ROOT / "sums" / f"{variant.stem}.sha256").read_text(encoding="ascii").splitlines()
        assert sorted(line.split("  ", 1)[1] for line in sums) == [
            "bin/linux-amd64/toolbox",
            "bin/linux-arm64/toolbox",
        ], variant.stem
