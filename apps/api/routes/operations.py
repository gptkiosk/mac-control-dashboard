"""Phase 6 read-only panels. The app's normal sign-in guard protects every route."""
import re
import time
from fastapi import Depends
from sqlalchemy.orm import Session
from deps import get_session
from models import AlertEvent
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")

@router.get("/github/repos")
def repositories(request: Request):
    return request.app.state.github.repos()

@router.get("/github/repos/{owner}/{repo}")
def repository(request: Request, owner: str, repo: str):
    value = request.app.state.github.details(f"{owner}/{repo}")
    if value is None:
        raise HTTPException(404, "Repository is not in the accessible catalog.")
    return value

@router.get("/reports")
def reports(request: Request):
    return request.app.state.reports.catalog()

@router.get("/reports/{report_id}")
def report(request: Request, report_id: str):
    if not re.fullmatch(r"[a-f0-9]{64}", report_id):
        raise HTTPException(404, "Report not found.")
    try:
        return request.app.state.reports.read(report_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except OSError:
        raise HTTPException(404, "Report is unavailable. Refresh the report list.") from None


@router.get("/alerts")
def alerts(request: Request):
    return request.app.state.alerts.status()


@router.post("/alerts/{event_id}/acknowledge")
def acknowledge_alert(event_id: str, session: Session = Depends(get_session)):
    if not re.fullmatch(r"[a-f0-9]{32}", event_id):
        raise HTTPException(404, "Alert not found.")
    event = session.get(AlertEvent, event_id)
    if event is None:
        raise HTTPException(404, "Alert not found.")
    if event.status not in {"uncertain", "held"}:
        raise HTTPException(409, "Only alerts awaiting delivery review can be acknowledged.")
    event.reviewed_at = event.reviewed_at or int(time.time())
    session.commit()
    return {"ok": True, "reviewed_at": event.reviewed_at}
