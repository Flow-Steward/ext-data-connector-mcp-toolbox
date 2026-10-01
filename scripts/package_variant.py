#!/usr/bin/env python3
"""Package a rendered variant for Flow Steward, one archive per runtime target.

    python3 scripts/render_variant.py <variant>
    scripts/build_toolbox.sh <variant>
    python3 scripts/package_variant.py <variant>   ->  dist/<extension_id>-<version>-<target>.zip

The archives are what ``flow-steward extensions bundle --runtime-target <target>``
produces: the extension under one top folder, only its own ``bin/<target>/``,
and a ``.fs-package.yaml`` naming the native executable and its SHA-256.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("linux-amd64", "linux-arm64")
# The product bundler leaves these out (core/application/tooling/extensions/bundle_extension.py).
EXCLUDED_DIRECTORIES = {
    ".fs-python", ".hypothesis", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "dev-wheels",
}
EXCLUDED_FILES = {".fs-extension-install.yaml", ".fs-package.yaml"}
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 150 * 1024 * 1024


def package(variant: str) -> list[Path]:
    rendered = [path for path in (ROOT / "build" / variant).iterdir() if (path / "extension.yaml").is_file()]
    if len(rendered) != 1:
        sys.exit(f"run scripts/render_variant.py {variant} first")
    source = rendered[0]
    manifest = yaml.safe_load((source / "extension.yaml").read_text(encoding="utf-8"))
    extension_id, version = manifest["extension_id"], manifest["version"]
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and not set(path.relative_to(source).parts) & EXCLUDED_DIRECTORIES
        # Binaries staged for the tests are added per target below, never twice.
        and path.relative_to(source).parts[0] != "bin"
        and path.name not in EXCLUDED_FILES
    )
    written = []
    for target in TARGETS:
        binary = ROOT / "build" / variant / "bin" / target / "toolbox"
        if not binary.is_file():
            sys.exit(f"{binary} is missing; run scripts/build_toolbox.sh {variant} first")
        out = ROOT / "dist" / f"{extension_id}-{version}-{target}.zip"
        out.parent.mkdir(exist_ok=True)
        unpacked = 0
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=f"{source.name}/{path.relative_to(source).as_posix()}")
                unpacked += path.stat().st_size
            archive.write(binary, arcname=f"{source.name}/bin/{target}/toolbox")
            unpacked += binary.stat().st_size
            archive.writestr(
                f"{source.name}/.fs-package.yaml",
                yaml.safe_dump(
                    {
                        "native_executable": {
                            "path": f"bin/{target}/toolbox",
                            "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                        },
                        "runtime_target": target,
                    },
                    sort_keys=True,
                ),
            )
        size = out.stat().st_size
        if size > MAX_ZIP_BYTES or unpacked > MAX_UNPACKED_BYTES:
            sys.exit(f"{out.name}: {size} zipped / {unpacked} unpacked bytes exceed Flow Steward's install limits")
        print(f"{out.relative_to(ROOT)}  {size / 2**20:.1f} MB zipped, {unpacked / 2**20:.1f} MB unpacked")
        written.append(out)
    return written


if __name__ == "__main__":
    for name in sys.argv[1:] or sys.exit("usage: package_variant.py <variant>..."):
        package(name)
