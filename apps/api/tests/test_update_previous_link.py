"""The `previous` link after a failed or interrupted update (found by the N4 launchd preview).

A rolled-back update used to leave `previous` pointing at the version that was running, so the panel's next
"Roll back" offered the current version. The link must come back to what it was before the switch.
"""

from __future__ import annotations

import os

import pytest

import update_engine as ue
from tests.test_update_engine import Service, cfg, installed, no_blockers, ready, staged, this_host  # noqa: F401


def bad(cfg, version, started):
    return False, "health check failed"


def good_for_old(old_version):
    return lambda cfg, version, started: (version == old_version, "ok" if version == old_version else "not healthy")


def link(cfg, name):
    return ue._link_target(cfg, name)  # noqa: SLF001


def test_a_first_failed_update_leaves_no_previous_link_at_all(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    assert link(cfg, "previous") is None
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, new, service=Service(), readiness=good_for_old("1.1.0"), blockers=no_blockers)
    assert link(cfg, "current") == old
    assert link(cfg, "previous") is None            # it used to point at `old`, the running version


def test_a_failed_update_keeps_the_previous_version_the_operator_could_roll_back_to(tmp_path, cfg):
    first, second = installed(cfg, tmp_path)                       # running 1.1.0, 1.2.0 staged
    ue.apply(cfg, second, service=Service(), readiness=ready, blockers=no_blockers)
    assert (link(cfg, "current"), link(cfg, "previous")) == (second, first)
    third = staged(cfg, tmp_path, "1.3.0")
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, third, service=Service(), readiness=good_for_old("1.2.0"), blockers=no_blockers)
    assert (link(cfg, "current"), link(cfg, "previous")) == (second, first)
    assert ue.status(cfg)["previous"] == first


def test_a_committed_update_still_moves_previous_to_the_version_it_replaced(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    ue.apply(cfg, new, service=Service(), readiness=ready, blockers=no_blockers)
    assert (link(cfg, "current"), link(cfg, "previous")) == (new, old)


def test_a_service_that_will_not_start_also_restores_the_previous_link(tmp_path, cfg):
    first, second = installed(cfg, tmp_path)
    ue.apply(cfg, second, service=Service(), readiness=ready, blockers=no_blockers)
    third = staged(cfg, tmp_path, "1.3.0")

    class WontStart(Service):
        def start(self):
            super().start()
            if self.calls.count("start") == 1:
                raise ue.UpdateError("service start failed")
    with pytest.raises(ue.UpdateError):
        ue.apply(cfg, third, service=WontStart(), readiness=good_for_old("1.2.0"), blockers=no_blockers)
    assert (link(cfg, "current"), link(cfg, "previous")) == (second, first)


def test_recovery_of_an_update_killed_between_the_two_link_changes_restores_previous(tmp_path, cfg):
    """Killed after `previous` was repointed at the running version and before `current` moved."""
    first, second = installed(cfg, tmp_path)
    ue.apply(cfg, second, service=Service(), readiness=ready, blockers=no_blockers)
    third = staged(cfg, tmp_path, "1.3.0")
    state = ue.load_state(cfg)
    state["tx"] = {"id": "0" * 16, "kind": "switch", "phase": "switching", "target": third, "from": second,
                   "prev": first, "backup": None, "backup_meta": None, "started_at": 1}
    ue.save_state(cfg, state)
    ue._point(cfg, "previous", second)                          # the half-done switch  # noqa: SLF001
    assert ue.recover(cfg, Service(), ready) == "aborted"
    assert (link(cfg, "current"), link(cfg, "previous")) == (second, first)


def test_a_journal_without_the_field_is_handled_as_before(tmp_path, cfg):
    first, second = installed(cfg, tmp_path)
    ue.apply(cfg, second, service=Service(), readiness=ready, blockers=no_blockers)
    third = staged(cfg, tmp_path, "1.3.0")
    state = ue.load_state(cfg)
    state["tx"] = {"id": "1" * 16, "kind": "switch", "phase": "switching", "target": third, "from": second,
                   "backup": None, "backup_meta": None, "started_at": 1}
    ue.save_state(cfg, state)
    ue._point(cfg, "previous", second)  # noqa: SLF001
    assert ue.recover(cfg, Service(), ready) == "aborted"
    assert link(cfg, "current") == second                       # no crash; previous is left as the old code left it


def test_a_pruned_previous_version_is_dropped_rather_than_pointed_at(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    tx = {"prev": "0.9.0-gone"}
    ue._restore_previous(cfg, tx)                               # noqa: SLF001
    assert not os.path.lexists(cfg.root / "previous")
