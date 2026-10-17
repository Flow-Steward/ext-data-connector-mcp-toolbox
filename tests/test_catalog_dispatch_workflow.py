"""Run the actual catalog-notification shell steps with only GitHub I/O replaced."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


@pytest.fixture
def notification(tmp_path):
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["announce_catalog"]
    scripts = [step["run"] for step in job["steps"]]
    capture = tmp_path / "requests.jsonl"
    binary = tmp_path / "gh"
    # This boundary stub has no network client and refuses every release mutation.
    binary.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["DISPATCH_CAPTURE"]).open("a") as output:
    output.write(json.dumps(args) + "\n")
if args[:2] == ["release", "view"]:
    state = os.environ.get("SOURCE_RELEASE_STATE", "published")
    if state == "missing":
        print("Release not found", file=sys.stderr)
        sys.exit(1)
    print("true" if state == "draft" else "false")
elif args[:1] == ["api"]:
    status = os.environ.get("DISPATCH_RESPONSE", "204")
    if status != "204":
        print("Dispatch rejected: " + status, file=sys.stderr)
        sys.exit(1)
else:
    print("Unexpected or mutating GitHub command", file=sys.stderr)
    sys.exit(97)
"""
    )
    binary.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
        "SOURCE_REPOSITORY": "Flow-Steward/example-fixture",
        "RELEASE_TAG": "v1.2.0",
        "GH_TOKEN": uuid.uuid4().hex,
        "DISPATCH_CAPTURE": str(capture),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }

    def run(step: int, **overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", scripts[step]],
            cwd=tmp_path,
            env={**env, **overrides},
            capture_output=True,
            text=True,
            check=False,
        )

    def requests() -> list[list[str]]:
        if not capture.exists():
            return []
        return [json.loads(line) for line in capture.read_text().splitlines()]

    return run, requests, tmp_path


@pytest.mark.parametrize(
    ("state", "succeeds"), [("published", True), ("draft", False), ("missing", False)]
)
def test_only_an_existing_published_release_passes_verification(
    notification, state, succeeds
):
    run, requests, _tmp_path = notification

    result = run(0, SOURCE_RELEASE_STATE=state)

    assert (result.returncode == 0) is succeeds, result.stderr
    assert requests() == [
        [
            "release",
            "view",
            "v1.2.0",
            "--repo",
            "Flow-Steward/example-fixture",
            "--json",
            "isDraft",
            "--jq",
            ".isDraft",
        ]
    ]
    if not succeeds:
        assert "::error::" in result.stdout


def test_an_empty_retry_tag_is_refused_before_any_github_request(notification):
    run, requests, _tmp_path = notification

    result = run(0, RELEASE_TAG="")

    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert requests() == []


def test_dispatch_posts_the_catalog_event_and_original_release_identity(notification):
    run, requests, tmp_path = notification

    result = run(1)

    assert result.returncode == 0, result.stderr
    assert requests() == [
        [
            "api",
            "--hostname",
            "github.com",
            "--method",
            "POST",
            "repos/Flow-Steward/extensions/dispatches",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2026-03-10",
            "--raw-field",
            "event_type=extension-released",
            "--raw-field",
            "client_payload[repository]=Flow-Steward/example-fixture",
            "--raw-field",
            "client_payload[tag]=v1.2.0",
        ]
    ]
    assert "Catalog notification accepted" in (tmp_path / "summary.md").read_text()


@pytest.mark.parametrize("status", ["403", "404", "422", "transport-error"])
def test_dispatch_failure_is_visible_and_never_rewrites_the_release(
    notification, status
):
    run, requests, tmp_path = notification

    result = run(1, DISPATCH_RESPONSE=status)

    assert result.returncode != 0
    assert "::error::Catalog notification failed" in result.stdout
    assert "remain published" in result.stdout
    assert len(requests()) == 1
    assert requests()[0][0] == "api"
    assert not (tmp_path / "summary.md").exists()


def test_a_missing_dispatch_credential_fails_without_calling_github(notification):
    run, requests, _tmp_path = notification

    result = run(1, GH_TOKEN="")

    assert result.returncode != 0
    assert "CATALOG_DISPATCH_TOKEN is missing" in result.stdout
    assert requests() == []


def test_a_retry_tag_is_always_data_in_both_shell_steps(notification):
    run, requests, tmp_path = notification
    marker = tmp_path / "injected"
    tag = f"v1.2.0; touch {marker}; $(touch {marker})"

    verified = run(0, RELEASE_TAG=tag)
    announced = run(1, RELEASE_TAG=tag)

    assert verified.returncode == 0, verified.stderr
    assert announced.returncode == 0, announced.stderr
    assert requests()[0][2] == tag
    assert requests()[1][-1] == f"client_payload[tag]={tag}"
    assert not marker.exists()
