"""Audit the packaged, pinned Redis-only native build and its safety patch."""

import hashlib
import json
import re
import struct
from pathlib import Path

EXTENSION = Path(__file__).resolve().parents[1]
COMMIT = "b0010060a939455d91e4f8ba62dc3e72b1892469"
IMAGE = (
    "golang:1.26.2-bookworm@sha256:47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19"
)


def test_native_build_pins_source_and_minimal_driver():
    script = (EXTENSION / "scripts/build_toolbox.sh").read_text()
    assert COMMIT in script
    assert IMAGE in script
    assert "git apply" in script
    assert "CGO_ENABLED=0" in script
    assert "-trimpath -buildvcs=false" in script
    assert "internal/sources/redis" in script
    assert "internal/tools/redis" in script
    assert "linux-amd64 linux-arm64" in script


def test_native_patch_disables_retries_and_preserves_nil_and_errors():
    patch = (EXTENSION / "scripts/patches/0002-flowsteward-key-value-safety.patch").read_text()
    added = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    assert len(re.findall(r"MaxRetries:\s+-1", added)) == 2
    assert "errors.Is(err, redis.Nil)" in added
    assert "out[i] = nil" in added
    assert 'return nil, fmt.Errorf("error executing command: %w", err)' in added
    assert "len(cmds) != 1" in added
    assert "s.RedisClient().Do(ctx, cmd...).Result()" in added
    assert "out[i] = errString" not in added


def test_packaged_native_binaries_match_provenance():
    provenance = json.loads((EXTENSION / "toolbox-provenance.json").read_text())
    assert provenance["commit"] == COMMIT
    assert provenance["tag"] == "v1.3.0"
    assert provenance["go_image"] == IMAGE
    assert provenance["packages"] == [
        "github.com/googleapis/mcp-toolbox/internal/sources/redis",
        "github.com/googleapis/mcp-toolbox/internal/tools/redis",
    ]
    patch = EXTENSION / provenance["patch"]
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == provenance["patch_sha256"]
    assert set(provenance["binaries"]) == {"linux-amd64", "linux-arm64"}
    for target, machine in (("linux-amd64", 62), ("linux-arm64", 183)):
        binary = EXTENSION / "bin" / target / "toolbox"
        content = binary.read_bytes()
        assert content[:6] == b"\x7fELF\x02\x01"
        assert struct.unpack_from("<H", content, 18)[0] == machine
        assert binary.stat().st_mode & 0o111
        assert hashlib.sha256(content).hexdigest() == provenance["binaries"][target]["sha256"]
        assert len(content) == provenance["binaries"][target]["size"]


def test_native_patch_verifies_tls_hostname_for_pinned_address():
    patch = (EXTENSION / "scripts/patches/0002-flowsteward-key-value-safety.patch").read_text()
    assert 'ServerName         string `yaml:"serverName"`' in patch
    assert "ServerName:         r.TLS.ServerName," in patch
