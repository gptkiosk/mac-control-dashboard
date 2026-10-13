"""A failed project story that another card already carries is an unneeded duplicate and can be deleted."""
from sqlalchemy import select

from models import Card, ProjectMemory, ProjectTask, Run
from tests.test_projects import app, active, node          # noqa: F401  (fixtures and helpers)


def story(p):
    return next(t["card_id"] for t in p["tasks"] if t["role"] == "story")


def duplicate_of(app, cid, column="failed"):
    """A second card bound to the same story of the same revision, as Hermes once created."""
    with app[1].begin() as d:
        orig = d.get(Card, cid)
        dup = Card(**{c.name: getattr(orig, c.name) for c in Card.__table__.columns if c.name != "id"})
        d.add(dup); d.flush()
        link = d.get(ProjectTask, cid)
        d.add(ProjectTask(card_id=dup.id, project_id=link.project_id, revision=link.revision, node_key=link.node_key, role=link.role))
        dup.column = column
        return dup.id


def set_column(app, cid, column):
    with app[1].begin() as d:
        d.get(Card, cid).column = column


def test_failed_duplicate_of_a_finished_story_is_marked_and_deletable(app):
    c, s, wd, settings = app
    p = active(app, [node("a")])
    keep = story(p)
    set_column(app, keep, "done")
    dup = duplicate_of(app, keep, "failed")
    assert c.get(f"/api/cards/{dup}").json()["superseded_by"] == keep
    assert c.get(f"/api/cards/{keep}").json()["superseded_by"] is None
    listed = {x["id"]: x for x in c.get("/api/cards").json()["cards"]}
    assert listed[dup]["superseded_by"] == keep and listed[keep]["superseded_by"] is None
    assert c.delete(f"/api/cards/{dup}").status_code == 204
    assert c.get(f"/api/cards/{dup}").status_code == 404
    assert c.get(f"/api/cards/{keep}").status_code == 200                                   # the real story is untouched
    with s() as d:
        assert d.get(ProjectTask, dup) is None and d.get(ProjectTask, keep) is not None
        note = d.scalar(select(ProjectMemory).where(ProjectMemory.text.like("Deleted duplicate failed card%")))
        assert note and f"#{keep}" in note.text and note.kind == "decision"                 # the ledger keeps the record


def test_a_sibling_in_review_also_counts(app):
    c, s, wd, settings = app
    keep = story(active(app, [node("a")]))
    set_column(app, keep, "review")
    dup = duplicate_of(app, keep)
    assert c.delete(f"/api/cards/{dup}").status_code == 204


def test_real_stories_stay_protected(app):
    c, s, wd, settings = app
    keep = story(active(app, [node("a")]))
    # a lone failed story with no finished sibling
    set_column(app, keep, "failed")
    assert c.get(f"/api/cards/{keep}").json()["superseded_by"] is None
    assert c.delete(f"/api/cards/{keep}").status_code == 409
    # a failed duplicate whose sibling is not finished
    dup = duplicate_of(app, keep, "failed")
    assert c.get(f"/api/cards/{dup}").json()["superseded_by"] is None
    assert c.delete(f"/api/cards/{dup}").status_code == 409
    # the finished card itself, and a non-failed duplicate of it
    set_column(app, keep, "done")
    assert c.delete(f"/api/cards/{keep}").status_code == 409
    queued = duplicate_of(app, keep, "queued")
    assert c.get(f"/api/cards/{queued}").json()["superseded_by"] is None
    assert c.delete(f"/api/cards/{queued}").status_code == 409


def test_deleting_the_duplicate_keeps_the_project_working(app):
    c, s, wd, settings = app
    p = active(app, [node("a")])
    keep = story(p)
    set_column(app, keep, "done")
    dup = duplicate_of(app, keep)
    assert c.delete(f"/api/cards/{dup}").status_code == 204
    detail = c.get(f"/api/projects/{p['id']}").json()
    assert [t["card_id"] for t in detail["tasks"] if t["role"] == "story"] == [keep]


def test_release_envelope_names_the_version_commit_and_whether_it_is_modified(app):
    c, s, wd, settings = app
    r = c.get("/api/release").json()
    from version import __version__
    assert r["version"] == __version__ and r["version"].count(".") == 2
    assert isinstance(r["dirty"], bool) and r["commit_sha"] and r["product"] and r["owner"]


def test_api_and_web_carry_the_same_version():
    import json
    from pathlib import Path
    from version import __version__
    web = json.loads((Path(__file__).resolve().parents[2] / "web" / "package.json").read_text())["version"]
    assert web == __version__, "apps/web/package.json and apps/api/version.py must carry the same version"
