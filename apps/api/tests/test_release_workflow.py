"""The draft release workflow (N4): what it may do, what it may not, and that it fails cleanly without a key.

These read .github/workflows/release-on-tag.yml as data. The workflow itself can only be proven on GitHub,
and cannot sign until the operator creates RELEASE_SSH_PRIVATE_KEY (punchlist N9), so what is pinned here is
its shape: least privilege, pinned actions, a draft that carries the changelog notes and only four assets.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[3]
TEXT = (ROOT / ".github" / "workflows" / "release-on-tag.yml").read_text()
WORKFLOW = yaml.safe_load(TEXT)
JOBS = WORKFLOW["jobs"]


def steps_text(job: str) -> str:
    return "\n".join(f"{s.get('name', '')}\n{s.get('run', '')}\n{s.get('uses', '')}" for s in JOBS[job]["steps"])


def test_it_runs_for_version_tags_or_explicit_tag_dispatch_never_pull_requests():
    triggers = WORKFLOW[True] if True in WORKFLOW else WORKFLOW["on"]       # PyYAML reads the key `on` as True
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v*"]}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"tag"}
    assert inputs["tag"]["required"] is True and inputs["tag"]["type"] == "string"
    checkout = next(s for s in JOBS["build"]["steps"] if s.get("uses", "").startswith("actions/checkout"))
    assert "format('refs/tags/{0}', inputs.tag)" in checkout["with"]["ref"]
    assert "inputs.tag || github.ref_name" in JOBS["build"]["env"]["TAG"]
    assert "pull_request_target" not in TEXT and "workflow_run" not in TEXT


def test_the_default_token_is_read_only_and_write_access_is_in_the_publish_job_alone():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    writers = [name for name, job in JOBS.items() if (job.get("permissions") or {}).get("contents") == "write"]
    assert writers == ["publish-draft"]
    assert JOBS["sign-and-attest"]["permissions"] == {"contents": "read", "attestations": "write", "id-token": "write"}


def test_the_job_order_is_gate_build_sign_publish():
    assert JOBS["build"]["needs"] == "gate" and JOBS["sign-and-attest"]["needs"] == "build"
    assert JOBS["publish-draft"]["needs"] == "sign-and-attest"
    assert JOBS["build"]["if"] == "needs.gate.outputs.build == 'true'"


def test_the_build_runs_on_an_apple_silicon_runner_and_the_rest_on_linux():
    assert JOBS["build"]["runs-on"] == "macos-14"
    assert JOBS["sign-and-attest"]["runs-on"].startswith("ubuntu") and JOBS["publish-draft"]["runs-on"].startswith("ubuntu")
    assert "uname -s)\" = Darwin" in steps_text("build") and "uname -m)\" = arm64" in steps_text("build")


def test_every_external_action_is_pinned_to_a_full_commit():
    refs = re.findall(r"uses:\s+([^\s]+)", TEXT)
    assert refs and all(re.search(r"@[0-9a-f]{40}$", ref) for ref in refs), refs


def test_the_build_checks_out_without_credentials_and_never_sees_a_token_or_the_key():
    checkout = next(s for s in JOBS["build"]["steps"] if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["persist-credentials"] is False
    build = "\n".join(str(s) for s in JOBS["build"]["steps"])
    assert "GH_TOKEN" not in build and "secrets." not in build and "github.token" not in build


def test_the_key_is_used_by_the_signing_step_alone_and_its_absence_fails_before_anything_is_published():
    holders = [name for name, job in JOBS.items() if "secrets.RELEASE_SSH_PRIVATE_KEY" in str(job)]
    assert holders == ["sign-and-attest"]
    signing = next(s for s in JOBS["sign-and-attest"]["steps"] if s.get("name") == "Sign the detached manifest")
    assert 'test -n "${RELEASE_SSH_PRIVATE_KEY:-}"' in signing["run"] and "exit 1" in signing["run"]
    assert signing["run"].index("exit 1") < signing["run"].index("ssh-keygen")   # the guard comes first
    assert "-n dashboard-release" in signing["run"]
    assert "trap 'rm -f \"$key\"' EXIT" in signing["run"]                         # the key file never outlives the step
    for later in ("Attest the four allowlisted assets", "Pass the signed assets to the publish job"):
        names = [s.get("name") for s in JOBS["sign-and-attest"]["steps"]]
        assert names.index("Sign the detached manifest") < names.index(later)
    assert "RELEASE_SSH_PRIVATE_KEY" not in steps_text("publish-draft")


def test_the_release_is_a_draft_with_the_changelog_notes_and_nothing_replaces_an_existing_one():
    publish = steps_text("publish-draft")
    assert "--draft" in publish and "--notes-file release-body.md" in publish
    assert "--latest" not in publish
    assert 'gh release view "$TAG"' in publish and "refusing to alter an existing release" in publish
    build = steps_text("build")
    assert "scripts/release/changelog.py check" in build and "scripts/release/changelog.py notes" in build
    assert "--notes \"\"" not in publish


def test_the_draft_carries_the_manifest_digest_the_in_app_updater_asks_for():
    publish = steps_text("publish-draft")
    assert "sha256sum" in publish and "Manifest SHA-256" in publish


def test_only_the_four_allowlisted_assets_are_checksummed_attested_and_published():
    sign = steps_text("sign-and-attest")
    assert 'wc -l < dist-release/SHA256SUMS' in sign and '= 3' in sign
    assert 'find dist-release -maxdepth 1 -type f | wc -l' in sign and '= 4' in sign
    subjects = next(s for s in JOBS["sign-and-attest"]["steps"] if s.get("name") == "Attest the four allowlisted assets")["with"]["subject-path"]
    assert [line.strip() for line in subjects.splitlines() if line.strip()] == [
        "dist-release/*.tar.gz", "dist-release/*.manifest.json", "dist-release/*.manifest.json.sig", "dist-release/SHA256SUMS"]
    assert "dist-release/*" in steps_text("publish-draft")
    assert "release-notes.md" not in "\n".join(str(s.get("with", "")) for s in JOBS["sign-and-attest"]["steps"])


def test_the_tag_must_equal_the_source_version_and_the_package_is_verified_against_it():
    build = steps_text("build")
    assert 'test "${TAG}" = "v${version}"' in build
    assert "--expect-version \"${TAG#v}\"" in build and "--expect-product mcd" in build and "--expect-platform darwin-arm64" in build
    assert "build-macos-arm64.sh --out dist-release --repro" in build


def test_a_tag_that_already_has_a_release_is_left_alone():
    gate = steps_text("gate")
    assert "gh release view" in gate and "build=false" in gate and "never alters a release" in gate
    assert JOBS["gate"]["permissions"] == {"contents": "read"}
