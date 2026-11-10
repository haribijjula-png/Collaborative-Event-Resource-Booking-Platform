import csv
import io
import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BadRequest, E, NotFound
from app.models import models as m
from app.models.enums import AttendanceStatus, NotificationType, OrgRole
from app.repositories.repos import (AttachmentRepo, AttendanceRepo, CommentRepo, EventRepo, NotificationRepo, OrgRepo,
                                    RegistrationRepo, UserRepo)
from app.services.common import Access, audit, broadcast, forbidden, notify, utcnow
from app.services.events import load_event, require_manage, can_manage_event


# ===================== Attendance =====================
class AttendanceService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = AttendanceRepo(db)
        self.access = Access(db, user)

    def _open(self, ev: m.Event):
        if ev.status not in ("ongoing", "completed"):
            raise E(409, "INVALID_EVENT_STATUS", "Attendance can only be recorded for ongoing or completed events.")

    def _sync(self, att: m.Attendance, status: str):
        att.status = status
        att.checked_in_at = utcnow() if status == "attended" else None
        reg = self.db.get(m.Registration, att.registration_id) if att.registration_id else None
        if reg and reg.status in ("confirmed", "attended", "no_show"):
            reg.status = {"attended": "attended", "no_show": "no_show"}.get(status, "confirmed")

    def mark(self, event_id: int, user_id: int, status: AttendanceStatus):
        ev = load_event(self.db, self.access, event_id, OrgRole.STAFF)
        self._open(ev)
        reg = RegistrationRepo(self.db).active_for(ev.id, user_id)
        if not reg or reg.status not in ("confirmed", "attended", "no_show"):
            raise E(409, "NOT_REGISTERED", "This user does not have a confirmed registration for the event.")
        att = self.repo.for_user_event(ev.id, user_id) or self.repo.add(
            m.Attendance(event_id=ev.id, user_id=user_id, registration_id=reg.id))
        self._sync(att, status.value)
        audit(self.db, self.user, ev.organization_id, "attendance.marked", "attendance", att.id, {"status": status.value})
        broadcast(self.db, self.access.orgs.active_member_ids(ev.organization_id, ("org_admin", "event_manager", "staff")) + [user_id],
                  "attendance.updated", {"event_id": ev.id, "user_id": user_id, "status": status.value})
        self.db.commit()
        self.db.refresh(att)
        return att

    def update(self, att_id: int, status: AttendanceStatus):
        att = self.repo.get(att_id)
        if not att:
            raise NotFound("Attendance record not found.", code="ATTENDANCE_NOT_FOUND")
        ev = load_event(self.db, self.access, att.event_id, OrgRole.STAFF)
        self._open(ev)
        self._sync(att, status.value)
        audit(self.db, self.user, ev.organization_id, "attendance.updated", "attendance", att.id, {"status": status.value})
        broadcast(self.db, self.access.orgs.active_member_ids(ev.organization_id, ("org_admin", "event_manager", "staff")) + [att.user_id],
                  "attendance.updated", {"event_id": ev.id, "user_id": att.user_id, "status": status.value})
        self.db.commit()
        self.db.refresh(att)
        return att

    def list(self, event_id: int, page, page_size, status=None):
        ev = load_event(self.db, self.access, event_id)
        res = self.repo.list(ev.id, page, page_size, status)
        if not self.access.has(ev.organization_id, OrgRole.STAFF):  # participants: own record only
            res["items"] = [a for a in res["items"] if a.user_id == self.user.id]
            res["total"] = len(res["items"])
            res["pages"] = 1 if res["items"] else 0
        return res

    def export_csv(self, event_id: int) -> str:
        ev = load_event(self.db, self.access, event_id, OrgRole.STAFF)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["user_id", "full_name", "email", "status", "checked_in_at"])
        for a in self.repo.all_for_event(ev.id):
            w.writerow([a.user_id, a.user.full_name, self.db.get(m.User, a.user_id).email, a.status, a.checked_in_at or ""])
        return buf.getvalue()


# ===================== Files =====================
# extension -> (allowed detected types)
ALLOWED = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"},
    ".gif": {"image/gif"},
    ".txt": {"text/plain"}, ".csv": {"text/csv", "text/plain"}, ".md": {"text/plain"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
}
ENTITY_TYPES = {"event", "session", "speaker", "registration"}


def sniff_mime(content: bytes, ext: str) -> str | None:
    """Detect the real type from the bytes themselves; never trust the client's header or filename."""
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content.startswith(b"PK\x03\x04"):  # OOXML containers
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = z.namelist()
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if "xl/workbook.xml" in names:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if "ppt/presentation.xml" in names:
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return None
    if b"\x00" not in content[:8192]:
        try:
            content[:65536].decode("utf-8")
            return "text/csv" if ext == ".csv" else "text/plain"
        except UnicodeDecodeError:
            return None
    return None


class FileService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = AttachmentRepo(db)
        self.access = Access(db, user)
        self.root = Path(settings.UPLOAD_DIR)

    def upload(self, filename: str, client_mime: str | None, content: bytes, event_id: int, entity_type: str, entity_id: int | None):
        if entity_type not in ENTITY_TYPES:
            raise BadRequest(f"entity_type must be one of {sorted(ENTITY_TYPES)}.", code="INVALID_ENTITY_TYPE")
        ev = load_event(self.db, self.access, event_id)
        role = self.access.role(ev.organization_id)
        if entity_type == "registration":  # participants may only attach to their own registration
            reg = self.db.get(m.Registration, entity_id) if entity_id else None
            if not reg or reg.event_id != ev.id:
                raise NotFound("Registration not found.", code="REGISTRATION_NOT_FOUND")
            if reg.user_id != self.user.id and not self.access.has(ev.organization_id, OrgRole.STAFF):
                raise forbidden("You can only attach files to your own registration.")
        else:
            if entity_type in ("session", "speaker") and not entity_id:
                raise BadRequest("entity_id is required for this entity_type.", code="ENTITY_ID_REQUIRED")
            if entity_type == "session":
                s = self.db.get(m.EventSession, entity_id)
                if not s or s.event_id != ev.id:
                    raise NotFound("Session not found.", code="SESSION_NOT_FOUND")
            if entity_type == "speaker":
                sp = self.db.get(m.Speaker, entity_id)
                if not sp or sp.organization_id != ev.organization_id:
                    raise NotFound("Speaker not found.", code="SPEAKER_NOT_FOUND")
            if not can_manage_event(self.access, ev) and not self.access.has(ev.organization_id, OrgRole.STAFF):
                raise forbidden("Only staff and event managers can upload event documents.")
        if not content:
            raise BadRequest("The uploaded file is empty.", code="EMPTY_FILE")
        if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise E(413, "FILE_TOO_LARGE", f"File exceeds the {settings.MAX_UPLOAD_MB} MB limit.")
        safe_name = os.path.basename(filename or "").replace("\x00", "")
        safe_name = re.sub(r"[^\w.\- ]", "_", safe_name)[:200]
        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED:
            raise E(415, "INVALID_FILE_EXTENSION", f"Files with extension '{ext or '(none)'}' are not allowed.")
        detected = sniff_mime(content, ext)
        if detected is None or detected not in ALLOWED[ext]:
            raise E(415, "INVALID_FILE_TYPE", "The file content does not match its extension or is not an allowed type.")
        if client_mime and client_mime.split(";")[0].strip() not in (detected, "application/octet-stream") and detected != "text/plain":
            raise E(415, "INVALID_MIME_TYPE", "The declared content type does not match the file content.")
        self.root.mkdir(parents=True, exist_ok=True)
        stored = f"{uuid.uuid4().hex}{ext}"
        (self.root / stored).write_bytes(content)
        att = self.repo.add(m.Attachment(event_id=ev.id, entity_type=entity_type, entity_id=entity_id, file_name=safe_name,
                                         mime_type=detected, file_size=len(content), storage_path=stored, uploaded_by=self.user.id))
        audit(self.db, self.user, ev.organization_id, "file.uploaded", "attachment", att.id, {"name": safe_name})
        self.db.commit()
        return att

    def list(self, event_id, entity_type=None, entity_id=None):
        ev = load_event(self.db, self.access, event_id)
        items = self.repo.for_event(ev.id, entity_type, entity_id)
        if not self.access.has(ev.organization_id, OrgRole.STAFF):  # participants: shared docs + their own
            own_regs = {r.id for r in self.db.scalars(select(m.Registration).where(m.Registration.event_id == ev.id, m.Registration.user_id == self.user.id))}
            items = [a for a in items if a.entity_type != "registration" or a.entity_id in own_regs]
        return items

    def get_for_download(self, att_id: int):
        att = self.repo.get(att_id)
        if not att:
            raise NotFound("File not found.", code="FILE_NOT_FOUND")
        ev = load_event(self.db, self.access, att.event_id)
        if att.entity_type == "registration" and not self.access.has(ev.organization_id, OrgRole.STAFF):
            reg = self.db.get(m.Registration, att.entity_id)
            if not reg or reg.user_id != self.user.id:
                raise forbidden("You cannot access this file.")
        return att, self.root / att.storage_path

    def delete(self, att_id: int):
        att = self.repo.get(att_id)
        if not att:
            raise NotFound("File not found.", code="FILE_NOT_FOUND")
        ev = load_event(self.db, self.access, att.event_id)
        if att.uploaded_by != self.user.id and not can_manage_event(self.access, ev):
            raise forbidden("Only the uploader or the event manager can delete this file.")
        path = self.root / att.storage_path
        self.repo.delete(att)
        self.db.commit()
        path.unlink(missing_ok=True)


# ===================== Comments =====================
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.-]{3,50})")


class CommentService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = CommentRepo(db)
        self.access = Access(db, user)

    def _target(self, event_id=None, session_id=None):
        if session_id:
            s = self.db.get(m.EventSession, session_id)
            if not s:
                raise NotFound("Session not found.", code="SESSION_NOT_FOUND")
            return load_event(self.db, self.access, s.event_id), None, s
        return load_event(self.db, self.access, event_id), None, None

    def _mentions(self, ev, body, only_new_vs: str | None = None):
        names = set(MENTION_RE.findall(body))
        if only_new_vs is not None:
            names -= set(MENTION_RE.findall(only_new_vs))
        members = set(OrgRepo(self.db).active_member_ids(ev.organization_id))
        users = [u for u in UserRepo(self.db).by_usernames(list(names)) if u.id in members and u.id != self.user.id]
        notify(self.db, [u.id for u in users], NotificationType.USER_MENTIONED, "You were mentioned",
               f"{self.user.full_name} mentioned you in a comment on '{ev.name}'.", {"event_id": ev.id})

    def add(self, body: str, event_id=None, session_id=None):
        ev, _, _s = self._target(event_id, session_id)
        c = self.repo.add(m.Comment(event_id=None if session_id else ev.id, session_id=session_id, user_id=self.user.id, body=body))
        self._mentions(ev, body)
        broadcast(self.db, self.access.orgs.active_member_ids(ev.organization_id), "comment.created",
                  {"comment_id": c.id, "event_id": ev.id, "session_id": session_id})
        self.db.commit()
        self.db.refresh(c)
        return c

    def list(self, page, page_size, event_id=None, session_id=None):
        self._target(event_id, session_id)
        return self.repo.list(page, page_size, event_id=None if session_id else event_id, session_id=session_id)

    def _own(self, cid):
        c = self.repo.get(cid)
        if not c:
            raise NotFound("Comment not found.", code="COMMENT_NOT_FOUND")
        eid = c.event_id or self.db.get(m.EventSession, c.session_id).event_id
        ev = load_event(self.db, self.access, eid)
        if c.user_id != self.user.id:
            raise forbidden("You can only modify your own comments.")
        return c, ev

    def update(self, cid, body):
        c, ev = self._own(cid)
        old, c.body = c.body, body
        self._mentions(ev, body, only_new_vs=old)
        self.db.commit()
        self.db.refresh(c)
        return c

    def delete(self, cid):
        c, _ = self._own(cid)
        self.repo.delete(c)
        self.db.commit()


# ===================== Notifications =====================
class NotificationService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user, self.repo = db, user, NotificationRepo(db)

    def mark_read(self, nid):
        n = self.repo.get(nid)
        if not n or n.user_id != self.user.id:
            raise NotFound("Notification not found.", code="NOTIFICATION_NOT_FOUND")
        n.is_read = True
        self.db.commit()
        return n

    def mark_all(self):
        n = self.repo.mark_all_read(self.user.id)
        self.db.commit()
        return n


# ===================== Dashboard =====================
class DashboardService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.access = Access(db, user)

    def _c(self, stmt) -> int:
        return self.db.scalar(stmt) or 0

    def build(self, org_id: int):
        role = self.access.require(org_id)
        now = utcnow()
        E_ = m.Event
        base_events = select(func.count()).select_from(E_).where(E_.organization_id == org_id)
        uid = self.user.id
        out = {"role": role.value, "organization_id": org_id}

        def upcoming_events(q, limit=5):
            rows = self.db.execute(q.where(E_.start_time >= now, E_.status.in_(["published", "ongoing"])).order_by(E_.start_time).limit(limit)).unique().scalars()
            return [{"id": e.id, "name": e.name, "start_time": e.start_time, "location": e.location, "status": e.status} for e in rows]

        def sessions_between(q, a, b):
            rows = self.db.execute(q.where(m.EventSession.start_time >= a, m.EventSession.start_time < b).order_by(m.EventSession.start_time).limit(20)).unique().scalars()
            return [{"id": s.id, "title": s.title, "event_id": s.event_id, "start_time": s.start_time, "end_time": s.end_time, "room": s.room.name if s.room else None} for s in rows]

        if role == OrgRole.ORG_ADMIN:
            regs_by_status = dict(self.db.execute(select(m.Registration.status, func.count()).join(E_, E_.id == m.Registration.event_id)
                                                  .where(E_.organization_id == org_id).group_by(m.Registration.status)).all())
            events_by_status = dict(self.db.execute(select(E_.status, func.count()).where(E_.organization_id == org_id).group_by(E_.status)).all())
            out["cards"] = {
                "total_events": self._c(base_events),
                "published_events": self._c(base_events.where(E_.status == "published")),
                "upcoming_events": self._c(base_events.where(E_.start_time >= now, E_.status.in_(["published", "ongoing"]))),
                "completed_events": self._c(base_events.where(E_.status == "completed")),
                "total_members": self._c(select(func.count()).select_from(m.OrganizationMember).where(m.OrganizationMember.organization_id == org_id, m.OrganizationMember.is_active.is_(True))),
                "total_registrations": sum(regs_by_status.values()),
                "active_resources": self._c(select(func.count()).select_from(m.Resource).where(m.Resource.organization_id == org_id, m.Resource.status == "active")),
                "current_bookings": self._c(select(func.count()).select_from(m.ResourceBooking).join(m.Resource).where(
                    m.Resource.organization_id == org_id, m.ResourceBooking.status == "approved", m.ResourceBooking.start_time <= now, m.ResourceBooking.end_time > now)),
            }
            out["charts"] = {"events_by_status": events_by_status, "registrations_by_status": regs_by_status}
            out["upcoming"] = upcoming_events(select(E_).where(E_.organization_id == org_id))
        elif role == OrgRole.EVENT_MANAGER:
            mine = select(E_.id).where(E_.organization_id == org_id, E_.organizer_id == uid)
            my_ids = list(self.db.scalars(mine))
            seats = self._c(select(func.count()).select_from(m.Registration).where(m.Registration.event_id.in_(my_ids or [-1]), m.Registration.status.in_(["confirmed", "attended", "no_show"])))
            attended = self._c(select(func.count()).select_from(m.Registration).where(m.Registration.event_id.in_(my_ids or [-1]), m.Registration.status == "attended"))
            marked = self._c(select(func.count()).select_from(m.Registration).where(m.Registration.event_id.in_(my_ids or [-1]), m.Registration.status.in_(["attended", "no_show"])))
            out["cards"] = {
                "my_events": len(my_ids),
                "upcoming_sessions": self._c(select(func.count()).select_from(m.EventSession).where(m.EventSession.event_id.in_(my_ids or [-1]), m.EventSession.start_time >= now)),
                "total_registrations": self._c(select(func.count()).select_from(m.Registration).where(m.Registration.event_id.in_(my_ids or [-1]), m.Registration.status.in_(["pending", "confirmed", "waitlisted", "attended", "no_show"]))),
                "waitlisted_participants": self._c(select(func.count()).select_from(m.Registration).where(m.Registration.event_id.in_(my_ids or [-1]), m.Registration.status == "waitlisted")),
                "attendance_rate": round(100 * attended / marked, 1) if marked else 0.0,
                "resource_bookings": self._c(select(func.count()).select_from(m.ResourceBooking).where(m.ResourceBooking.requested_by == uid, m.ResourceBooking.status.in_(["requested", "approved"]))),
                "confirmed_seats": seats,
            }
            out["upcoming"] = upcoming_events(select(E_).where(E_.organization_id == org_id, E_.organizer_id == uid))
        elif role == OrgRole.STAFF:
            day_end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            day_start = day_end - timedelta(days=1)
            sess_q = select(m.EventSession).join(E_, E_.id == m.EventSession.event_id).where(E_.organization_id == org_id)
            out["cards"] = {
                "assigned_events": self._c(base_events.where(E_.status.in_(["published", "ongoing"]))),
                "todays_sessions": len(sessions_between(sess_q, day_start, day_end)),
                "pending_registrations": self._c(select(func.count()).select_from(m.Registration).join(E_, E_.id == m.Registration.event_id).where(E_.organization_id == org_id, m.Registration.status == "pending")),
                "attendance_marked": self._c(select(func.count()).select_from(m.Attendance).join(E_, E_.id == m.Attendance.event_id).where(E_.organization_id == org_id, m.Attendance.status == "attended")),
            }
            out["todays_sessions"] = sessions_between(sess_q, day_start, day_end)
            out["upcoming_tasks"] = [{"type": "approve_registration", "registration_id": r.id, "event_id": r.event_id}
                                     for r in self.db.execute(select(m.Registration).join(E_, E_.id == m.Registration.event_id).where(
                                         E_.organization_id == org_id, m.Registration.status == "pending").order_by(m.Registration.created_at).limit(10)).unique().scalars()]
            out["upcoming"] = upcoming_events(select(E_).where(E_.organization_id == org_id))
        else:
            reg_q = select(m.Registration).join(E_, E_.id == m.Registration.event_id).where(E_.organization_id == org_id, m.Registration.user_id == uid)
            my_event_ids = list(self.db.scalars(select(m.Registration.event_id).join(E_, E_.id == m.Registration.event_id).where(
                E_.organization_id == org_id, m.Registration.user_id == uid, m.Registration.status.in_(["confirmed", "attended"]))))
            out["cards"] = {
                "registered_events": len(my_event_ids),
                "upcoming_events": self._c(base_events.where(E_.start_time >= now, E_.status == "published")),
                "upcoming_sessions": self._c(select(func.count()).select_from(m.EventSession).where(m.EventSession.event_id.in_(my_event_ids or [-1]), m.EventSession.start_time >= now)),
                "waitlisted_events": self._c(select(func.count()).select_from(m.Registration).join(E_, E_.id == m.Registration.event_id).where(E_.organization_id == org_id, m.Registration.user_id == uid, m.Registration.status == "waitlisted")),
            }
            hist = self.db.execute(select(m.Attendance).join(E_, E_.id == m.Attendance.event_id).where(E_.organization_id == org_id, m.Attendance.user_id == uid).order_by(m.Attendance.id.desc()).limit(10)).unique().scalars()
            out["attendance_history"] = [{"event_id": a.event_id, "status": a.status, "checked_in_at": a.checked_in_at} for a in hist]
            out["upcoming"] = upcoming_events(select(E_).where(E_.organization_id == org_id, E_.status == "published"))
        return out


# ===================== Reminders (scheduler) =====================
def generate_event_reminders(db: Session) -> int:
    now = utcnow()
    due = EventRepo(db).due_for_reminder(now + timedelta(minutes=settings.REMINDER_LEAD_MINUTES), now)
    for ev in due:
        ids = [r.user_id for r in db.scalars(select(m.Registration).where(m.Registration.event_id == ev.id, m.Registration.status == "confirmed"))]
        notify(db, ids + [ev.organizer_id], NotificationType.EVENT_STARTING_SOON, "Event starting soon",
               f"'{ev.name}' starts at {ev.start_time:%Y-%m-%d %H:%M} UTC.", {"event_id": ev.id})
        ev.reminder_sent = True
    db.commit()
    return len(due)
