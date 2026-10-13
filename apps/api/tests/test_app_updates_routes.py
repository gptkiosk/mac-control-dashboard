"""/api/app-updates/check, /fetch and the release notes in /api/app-updates (N4).

The helper process is never started here: _spawn is replaced by a recorder, and the Releases API is
replaced by monkeypatching release_fetch. What is asserted is what the routes refuse and exactly
what they would hand to the helper.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest

import release_fetch as rf
import release_verify as rv
import update_engine as ue
from routes import updates as routes
from tests.test_release_verify import make_release
from tests.test_update_engine import cfg, config_file, fake_builder, this_host  # noqa: F401

DIGEST = "ab" * 32
CHANGELOG = """# Changelog

## [Unreleased]

### Added
- not yet

## [1.2.0] - 2026-10-20

### Added
- Settings shows the changelog before an install.

### Fixed
- A thing <script>alert(1)</script> stays plain text.

## [1.1.0] - 2026-10-01

### Added
- The old thing.
"""


@pytest.fixture
def managed(tmp_path, monkeypatch, make_client, cfg):  # noqa: F811
    """A client signed in as the operator, on a managed (release) install rooted at cfg.root."""
    helper = cfg.root / "helper"
    helper.mkdir(mode=0o700)
    shutil.copyfile(config_file(tmp_path, cfg), helper / "helper.json")
    (helper / "helper.json").chmod(0o600)
    monkeypatch.setenv("MAC_CONTROL_UPDATE_ROOT", str(cfg.root))
    monkeypatch.setattr(ue, "install_kind", lambda app_root, root: ("release", "packaged version 1.1.0"))
    spawned: list[list[str]] = []
    monkeypatch.setattr(routes, "_spawn", lambda c, args: spawned.append(args) or {"started": args[0], "poll": "/api/app-updates"})
    client = make_client()
    state = {"signed_in": True, "agent": False}

    @client.app.middleware("http")
    async def session(request, call_next):
        if state["signed_in"]:
            request.state.user = {"email": "operator@example.invalid"}
        if state["agent"]:
            request.state.agent_grant = {"id": "test"}
        return await call_next(request)

    client.state, client.spawned, client.cfg = state, spawned, cfg
    return client


def candidate() -> rf.Candidate:
    asset = lambda kind, name: rf.Asset(kind, name, f"https://github.com/gptkiosk/mac-control-dashboard/releases/download/v1.2.0/{name}", 10, DIGEST, 100)  # noqa: E731
    names = rf.asset_names("mcd", "1.2.0", "darwin-arm64")
    return rf.Candidate(product="mcd", platform="darwin-arm64", repository="gptkiosk/mac-control-dashboard", channel="stable",
                        tag="v1.2.0", version="1.2.0", name="mcd-1.2.0-darwin-arm64", change="upgrade", notes="Notes",
                        html_url=None, published_at=None, prerelease=False,
                        assets=tuple(asset(kind, name) for kind, name in names.items()))


# --- /check ------------------------------------------------------------------------------


def test_check_reports_the_candidate_and_the_installed_version_and_changes_nothing(managed, monkeypatch):
    monkeypatch.setattr(rf, "check", lambda c, channel: candidate())
    monkeypatch.setattr(rf, "installed_version", lambda c: "1.1.0")
    with managed:
        body = managed.get("/api/app-updates/check").json()
    assert body["available"] is True and body["installed"] == "1.1.0"
    assert body["candidate"]["version"] == "1.2.0" and body["candidate"]["notes"] == "Notes"
    assert body["candidate"]["notes_format"] == "text"
    assert managed.spawned == []  # a check never starts the helper


def test_check_with_nothing_newer_says_so(managed, monkeypatch):
    monkeypatch.setattr(rf, "check", lambda c, channel: None)
    monkeypatch.setattr(rf, "installed_version", lambda c: "1.2.0")
    with managed:
        body = managed.get("/api/app-updates/check?channel=prerelease").json()
    assert body == {"available": False, "candidate": None, "installed": "1.2.0"}


def test_check_failures_from_github_are_a_502_with_the_reasons(managed, monkeypatch):
    def boom(c, channel):
        raise rf.FetchError(["GitHub rate limit reached; resets at epoch 1", "second reason"])
    monkeypatch.setattr(rf, "check", boom)
    with managed:
        response = managed.get("/api/app-updates/check")
    assert response.status_code == 502
    assert response.json()["detail"]["problems"] == ["GitHub rate limit reached; resets at epoch 1", "second reason"]


@pytest.mark.parametrize("query", ["channel=nightly", "channel=", "channel=stable%0a"])
def test_check_refuses_an_unknown_channel(managed, query):
    with managed:
        assert managed.get(f"/api/app-updates/check?{query}").status_code == 422


def test_check_needs_a_signed_in_operator_and_never_an_agent(managed):
    with managed:
        managed.state["signed_in"] = False
        assert managed.get("/api/app-updates/check").status_code == 403
        managed.state["signed_in"], managed.state["agent"] = True, True
        assert managed.get("/api/app-updates/check").status_code == 403


def test_check_is_refused_with_instructions_on_a_source_checkout(managed, monkeypatch):
    monkeypatch.setattr(ue, "install_kind", lambda app_root, root: ("dev", "this is a source checkout"))
    called = []
    monkeypatch.setattr(rf, "check", lambda c, channel: called.append(1))
    with managed:
        response = managed.get("/api/app-updates/check")
    assert response.status_code == 409 and "manual_instructions" in response.text and called == []


def test_check_is_refused_while_an_update_is_interrupted(managed):
    state = ue.load_state(managed.cfg)
    state["tx"] = {"id": "0" * 16, "kind": "switch", "phase": "starting", "target": "x", "from": "y"}
    ue.save_state(managed.cfg, state)
    with managed:
        response = managed.get("/api/app-updates/check")
    assert response.status_code == 409 and "recovery" in response.text


# --- /fetch ------------------------------------------------------------------------------


def fetch_body(**changes):
    return {"version": "1.2.0", "channel": "stable", "confirm": True, "manifest_sha256": DIGEST, **changes}


def test_fetch_hands_the_helper_exactly_the_confirmed_version_channel_and_pin(managed):
    with managed:
        response = managed.post("/api/app-updates/fetch", json=fetch_body())
    assert response.status_code == 202
    assert managed.spawned == [["fetch", "1.2.0", "--channel", "stable", "--manifest-sha256", DIGEST]]


def test_fetch_without_a_pin_is_passed_on_for_the_helper_to_refuse(managed):
    """Trust is decided by the helper's own configuration, not by the route."""
    body = fetch_body()
    del body["manifest_sha256"]
    with managed:
        assert managed.post("/api/app-updates/fetch", json=body).status_code == 202
    assert managed.spawned == [["fetch", "1.2.0", "--channel", "stable"]]


@pytest.mark.parametrize("changes", [
    {"confirm": False},
    {"version": "../../etc/passwd"},
    {"version": ""},
    {"version": "1.2.0; rm -rf /"},
    {"version": "x" * 65},
    {"channel": "nightly"},
    {"manifest_sha256": "abc"},
    {"manifest_sha256": DIGEST.upper()},
    {"url": "https://evil.example/release.tar.gz"},
    {"repository": "attacker/mac-control-dashboard"},
    {"force": True},
])
def test_fetch_refuses_unconfirmed_malformed_and_unexpected_requests(managed, changes):
    with managed:
        response = managed.post("/api/app-updates/fetch", json=fetch_body(**changes))
    assert response.status_code == 422
    assert managed.spawned == []


def test_fetch_without_confirm_is_refused_even_when_otherwise_valid(managed):
    body = fetch_body()
    del body["confirm"]
    with managed:
        assert managed.post("/api/app-updates/fetch", json=body).status_code == 422
    assert managed.spawned == []


def test_fetch_on_the_prerelease_channel_needs_the_helper_opt_in(managed):
    with managed:
        response = managed.post("/api/app-updates/fetch", json=fetch_body(channel="prerelease", version="1.3.0-rc.1"))
    assert response.status_code == 409 and "prerelease" in response.text
    assert managed.spawned == []


def test_fetch_is_refused_for_agents_signed_out_callers_and_unmanaged_installs(managed, monkeypatch):
    with managed:
        managed.state["signed_in"] = False
        assert managed.post("/api/app-updates/fetch", json=fetch_body()).status_code == 403
        managed.state["signed_in"], managed.state["agent"] = True, True
        assert managed.post("/api/app-updates/fetch", json=fetch_body()).status_code == 403
        managed.state["agent"] = False
        monkeypatch.setattr(ue, "install_kind", lambda app_root, root: ("unmanaged", "not running from the update root"))
        response = managed.post("/api/app-updates/fetch", json=fetch_body())
    assert response.status_code == 409 and "manual_instructions" in response.text
    assert managed.spawned == []


def test_fetch_is_refused_while_an_update_is_interrupted(managed):
    state = ue.load_state(managed.cfg)
    state["tx"] = {"id": "0" * 16, "kind": "switch", "phase": "starting", "target": "x", "from": "y"}
    ue.save_state(managed.cfg, state)
    with managed:
        response = managed.post("/api/app-updates/fetch", json=fetch_body())
    assert response.status_code == 409 and managed.spawned == []


def test_install_and_rollback_still_need_a_fully_staged_version(managed):
    with managed:
        response = managed.post("/api/app-updates/apply", json={"version_id": "1.2.0-abcdef"})
    assert response.status_code == 409 and "not completely staged" in response.text
    assert managed.spawned == []


# --- release notes in the status -----------------------------------------------------------


def stage_with_changelog(cfg, tmp_path, version, changelog=CHANGELOG, name=None):
    release = make_release(tmp_path, version=version, name=name or f"pkg-{version}",
                           extra_files={"CHANGELOG.md": (changelog.encode(), 0o644)})
    for path in (release.manifest_path, release.artifact_path):
        shutil.copyfile(path, cfg.inbox / path.name)
    digest = hashlib.sha256(release.manifest_bytes).hexdigest()
    return ue.stage(cfg, release.base, digest, builder=fake_builder)["id"]


def test_status_shows_the_changelog_section_of_a_staged_version_as_plain_text(managed, tmp_path):
    cfg = managed.cfg
    old = stage_with_changelog(cfg, tmp_path, "1.1.0")
    ue.activate_initial(cfg, old)
    new = stage_with_changelog(cfg, tmp_path, "1.2.0")
    with managed:
        versions = {v["version"]: v for v in managed.get("/api/app-updates").json()["install"]["versions"]}
    notes = versions["1.2.0"]["notes"]
    assert "Settings shows the changelog before an install." in notes
    assert "<script>alert(1)</script>" in notes          # kept as text; the UI never renders it as HTML
    assert "The old thing." not in notes and "not yet" not in notes   # only this version's section
    assert versions["1.1.0"]["notes"] is None             # the running version needs no notes
    assert versions["1.2.0"]["id"] == new


@pytest.mark.parametrize("changelog", ["", "# Changelog\n\n## [1.1.0] - 2026-10-01\n- other\n", "## [1.2.01] - x\n- no\n",
                                       "## [1.2.0] - 2026-10-20\n"])
def test_a_package_without_a_matching_section_has_no_notes(tmp_path, cfg, changelog):
    vid = stage_with_changelog(cfg, tmp_path, "1.2.0", changelog)
    assert ue.release_notes(cfg, vid, "1.2.0") is None


def test_notes_are_capped(tmp_path, cfg):
    vid = stage_with_changelog(cfg, tmp_path, "1.2.0", "## [1.2.0] - 2026-10-20\n" + "- line\n" * 20000)
    assert len(ue.release_notes(cfg, vid, "1.2.0")) == ue.NOTES_MAX_CHARS


def test_notes_never_follow_a_symlinked_changelog(tmp_path, cfg):
    vid = stage_with_changelog(cfg, tmp_path, "1.2.0")
    version_dir = cfg.versions / vid
    secret = tmp_path / "secret.md"
    secret.write_text("## [1.2.0] - 2026-10-20\n- leaked\n")
    version_dir.chmod(0o755)
    (version_dir / "CHANGELOG.md").unlink()
    (version_dir / "CHANGELOG.md").symlink_to(secret)
    assert ue.release_notes(cfg, vid, "1.2.0") is None
    assert ue.release_notes(cfg, "../x", "1.2.0") is None
