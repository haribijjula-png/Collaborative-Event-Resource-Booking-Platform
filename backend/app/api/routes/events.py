from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response

from app.api.deps import DB, CurrentUser, Pg, ok
from app.models.enums import AttendanceStatus, EventStatus, RegistrationStatus
from app.schemas.schemas import (AttachmentOut, AttendanceIn, AttendanceOut, AttendanceUpdate, CommentIn, CommentOut,
                                 Envelope, EventCreate, EventDetail, EventOut, EventStatusIn, EventUpdate, Message, Page,
                                 RegisterEventIn, RegistrationDecision, RegistrationOut, SessionBase, SessionOut,
                                 SessionUpdate)
from app.services.events import EventService
from app.services.misc import AttendanceService, CommentService, FileService
from app.services.registrations import RegistrationService
from app.services.sessions import SessionService

router = APIRouter(tags=["Events"])


# ---------------- events ----------------
@router.post("/events", response_model=Envelope[EventOut], status_code=201)
def create_event(body: EventCreate, db: DB, user: CurrentUser):
    return ok(EventService(db, user).create(body.model_dump()))


@router.get("/events", response_model=Envelope[Page[EventOut]])
def list_events(db: DB, user: CurrentUser, pg: Pg, status: EventStatus | None = None, organizer_id: int | None = None,
                organization_id: int | None = None, start_from: datetime | None = None, start_to: datetime | None = None,
                location: str | None = None, search: str | None = None, sort: str | None = Query(None, description="e.g. start_time or -start_time")):
    return ok(EventService(db, user).list(pg.page, pg.page_size, status=status.value if status else None, organizer_id=organizer_id,
                                          organization_id=organization_id, start_from=start_from, start_to=start_to,
                                          location=location, search=search, sort=sort))


@router.get("/events/{event_id}", response_model=Envelope[EventDetail])
def get_event(event_id: int, db: DB, user: CurrentUser):
    return ok(EventService(db, user).get(event_id))


@router.patch("/events/{event_id}", response_model=Envelope[EventOut])
def update_event(event_id: int, body: EventUpdate, db: DB, user: CurrentUser):
    return ok(EventService(db, user).update(event_id, body.model_dump(exclude_unset=True)))


@router.delete("/events/{event_id}", response_model=Envelope[Message])
def delete_event(event_id: int, db: DB, user: CurrentUser):
    EventService(db, user).delete(event_id)
    return ok({"message": "Event deleted."})


@router.post("/events/{event_id}/publish", response_model=Envelope[EventOut])
def publish_event(event_id: int, db: DB, user: CurrentUser):
    return ok(EventService(db, user).transition(event_id, EventStatus.PUBLISHED))


@router.post("/events/{event_id}/cancel", response_model=Envelope[EventOut])
def cancel_event(event_id: int, db: DB, user: CurrentUser):
    return ok(EventService(db, user).transition(event_id, EventStatus.CANCELLED))


@router.post("/events/{event_id}/archive", response_model=Envelope[EventOut])
def archive_event(event_id: int, db: DB, user: CurrentUser):
    return ok(EventService(db, user).transition(event_id, EventStatus.ARCHIVED))


@router.post("/events/{event_id}/status", response_model=Envelope[EventOut], summary="Generic status transition (e.g. ongoing, completed)")
def set_status(event_id: int, body: EventStatusIn, db: DB, user: CurrentUser):
    return ok(EventService(db, user).transition(event_id, body.status))


# ---------------- registrations ----------------
@router.post("/events/{event_id}/register", response_model=Envelope[RegistrationOut], status_code=201)
def register(event_id: int, db: DB, user: CurrentUser, body: RegisterEventIn | None = None):
    return ok(RegistrationService(db, user).register(event_id, body.notes if body else None))


@router.get("/events/{event_id}/registrations", response_model=Envelope[Page[RegistrationOut]])
def event_registrations(event_id: int, db: DB, user: CurrentUser, pg: Pg, status: RegistrationStatus | None = None,
                        search: str | None = None, sort: str | None = None):
    return ok(RegistrationService(db, user).list_for_event(event_id, pg.page, pg.page_size,
                                                           status=status.value if status else None, search=search, sort=sort))


@router.get("/registrations", response_model=Envelope[Page[RegistrationOut]])
def list_registrations(db: DB, user: CurrentUser, pg: Pg, event_id: int | None = None, status: RegistrationStatus | None = None,
                       user_id: int | None = None, organization_id: int | None = None, date_from: datetime | None = None,
                       date_to: datetime | None = None, search: str | None = None, sort: str | None = None):
    return ok(RegistrationService(db, user).list(pg.page, pg.page_size, event_id=event_id, status=status.value if status else None,
                                                  user_id=user_id, organization_id=organization_id, date_from=date_from,
                                                  date_to=date_to, search=search, sort=sort))


@router.get("/registrations/{reg_id}", response_model=Envelope[RegistrationOut])
def get_registration(reg_id: int, db: DB, user: CurrentUser):
    return ok(RegistrationService(db, user).get(reg_id))


@router.post("/registrations/{reg_id}/cancel", response_model=Envelope[RegistrationOut])
def cancel_registration(reg_id: int, db: DB, user: CurrentUser):
    return ok(RegistrationService(db, user).cancel(reg_id))


@router.post("/registrations/{reg_id}/approve", response_model=Envelope[RegistrationOut])
def approve_registration(reg_id: int, db: DB, user: CurrentUser):
    return ok(RegistrationService(db, user).approve(reg_id))


@router.post("/registrations/{reg_id}/reject", response_model=Envelope[RegistrationOut])
def reject_registration(reg_id: int, db: DB, user: CurrentUser, body: RegistrationDecision | None = None):
    return ok(RegistrationService(db, user).reject(reg_id, body.reason if body else None))


# ---------------- sessions ----------------
@router.post("/events/{event_id}/sessions", response_model=Envelope[SessionOut], status_code=201)
def create_session(event_id: int, body: SessionBase, db: DB, user: CurrentUser):
    return ok(SessionService(db, user).create(event_id, body.model_dump()))


@router.get("/events/{event_id}/sessions", response_model=Envelope[list[SessionOut]])
def list_sessions(event_id: int, db: DB, user: CurrentUser):
    return ok(SessionService(db, user).list_for_event(event_id))


@router.get("/sessions/{session_id}", response_model=Envelope[SessionOut])
def get_session(session_id: int, db: DB, user: CurrentUser):
    return ok(SessionService(db, user).get(session_id))


@router.patch("/sessions/{session_id}", response_model=Envelope[SessionOut])
def update_session(session_id: int, body: SessionUpdate, db: DB, user: CurrentUser):
    return ok(SessionService(db, user).update(session_id, body.model_dump(exclude_unset=True)))


@router.delete("/sessions/{session_id}", response_model=Envelope[Message])
def delete_session(session_id: int, db: DB, user: CurrentUser):
    SessionService(db, user).delete(session_id)
    return ok({"message": "Session deleted."})


# ---------------- attendance ----------------
@router.post("/events/{event_id}/attendance", response_model=Envelope[AttendanceOut], status_code=201)
def mark_attendance(event_id: int, body: AttendanceIn, db: DB, user: CurrentUser):
    return ok(AttendanceService(db, user).mark(event_id, body.user_id, body.status))


@router.get("/events/{event_id}/attendance", response_model=Envelope[Page[AttendanceOut]])
def list_attendance(event_id: int, db: DB, user: CurrentUser, pg: Pg, status: AttendanceStatus | None = None):
    return ok(AttendanceService(db, user).list(event_id, pg.page, pg.page_size, status.value if status else None))


@router.patch("/attendance/{att_id}", response_model=Envelope[AttendanceOut])
def update_attendance(att_id: int, body: AttendanceUpdate, db: DB, user: CurrentUser):
    return ok(AttendanceService(db, user).update(att_id, body.status))


@router.get("/events/{event_id}/attendance/export", summary="CSV attendance report")
def export_attendance(event_id: int, db: DB, user: CurrentUser):
    csv_text = AttendanceService(db, user).export_csv(event_id)
    return Response(csv_text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="attendance_{event_id}.csv"'})


# ---------------- files ----------------
@router.post("/files", response_model=Envelope[AttachmentOut], status_code=201)
async def upload_file(db: DB, user: CurrentUser, background: BackgroundTasks, event_id: int = Form(...),
                      entity_type: str = Form("event"), entity_id: int | None = Form(None), file: UploadFile = File(...)):
    from app.core.config import settings
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    content = await file.read(limit + 1)  # never buffer unbounded uploads
    att = FileService(db, user).upload(file.filename, file.content_type, content, event_id, entity_type, entity_id)
    background.add_task(_post_process_file, att.id)
    return ok(att)


def _post_process_file(att_id: int):
    import logging
    logging.getLogger("files").info("Post-processing attachment %s (virus-scan/thumbnail hook)", att_id)


@router.get("/events/{event_id}/files", response_model=Envelope[list[AttachmentOut]])
def list_files(event_id: int, db: DB, user: CurrentUser, entity_type: str | None = None, entity_id: int | None = None):
    return ok(FileService(db, user).list(event_id, entity_type, entity_id))


@router.get("/files/{att_id}/download")
def download_file(att_id: int, db: DB, user: CurrentUser):
    att, path = FileService(db, user).get_for_download(att_id)
    return FileResponse(path, media_type=att.mime_type, filename=att.file_name)


@router.delete("/files/{att_id}", response_model=Envelope[Message])
def delete_file(att_id: int, db: DB, user: CurrentUser):
    FileService(db, user).delete(att_id)
    return ok({"message": "File deleted."})


# ---------------- comments ----------------
@router.post("/events/{event_id}/comments", response_model=Envelope[CommentOut], status_code=201)
def add_event_comment(event_id: int, body: CommentIn, db: DB, user: CurrentUser):
    return ok(CommentService(db, user).add(body.body, event_id=event_id))


@router.get("/events/{event_id}/comments", response_model=Envelope[Page[CommentOut]])
def list_event_comments(event_id: int, db: DB, user: CurrentUser, pg: Pg):
    return ok(CommentService(db, user).list(pg.page, pg.page_size, event_id=event_id))


@router.post("/sessions/{session_id}/comments", response_model=Envelope[CommentOut], status_code=201)
def add_session_comment(session_id: int, body: CommentIn, db: DB, user: CurrentUser):
    return ok(CommentService(db, user).add(body.body, session_id=session_id))


@router.get("/sessions/{session_id}/comments", response_model=Envelope[Page[CommentOut]])
def list_session_comments(session_id: int, db: DB, user: CurrentUser, pg: Pg):
    return ok(CommentService(db, user).list(pg.page, pg.page_size, session_id=session_id))


@router.patch("/comments/{comment_id}", response_model=Envelope[CommentOut])
def update_comment(comment_id: int, body: CommentIn, db: DB, user: CurrentUser):
    return ok(CommentService(db, user).update(comment_id, body.body))


@router.delete("/comments/{comment_id}", response_model=Envelope[Message])
def delete_comment(comment_id: int, db: DB, user: CurrentUser):
    CommentService(db, user).delete(comment_id)
    return ok({"message": "Comment deleted."})
