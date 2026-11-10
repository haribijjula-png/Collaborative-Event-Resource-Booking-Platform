from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Conflict, E, NotFound
from app.models import models as m
from app.models.enums import NotificationType, OrgRole
from app.repositories.repos import BookingRepo, EventRepo, ResourceRepo, SessionRepo, SpeakerRepo
from app.services.common import Access, audit, broadcast, notify
from app.services.events import load_event, require_manage


class SessionService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = SessionRepo(db)
        self.access = Access(db, user)

    def _attach(self, s: m.EventSession) -> m.EventSession:
        s.speakers = self.repo.speakers(s.id)
        return s

    def _load(self, sid: int, min_role=OrgRole.PARTICIPANT, for_update=False):
        s = self.repo.get(sid, for_update=for_update)
        if not s:
            raise NotFound("Session not found.", code="SESSION_NOT_FOUND")
        ev = load_event(self.db, self.access, s.event_id, min_role)
        return s, ev

    def _writable(self, ev: m.Event):
        if ev.status == "cancelled":
            raise E(409, "EVENT_CANCELLED", "Cancelled events cannot receive new sessions.")
        if ev.status in ("completed", "archived"):
            raise E(409, "INVALID_EVENT_STATUS", f"Sessions cannot be changed on a {ev.status} event.")

    def _validate(self, ev: m.Event, *, start, end, room_id, capacity, speaker_ids, exclude_id=None):
        if start < ev.start_time or end > ev.end_time:
            raise BadRequest("A session cannot start before or end after its event.", code="SESSION_OUTSIDE_EVENT")
        if room_id:
            room = ResourceRepo(self.db).get(room_id, for_update=True)  # serialise per room
            if not room or room.organization_id != ev.organization_id:
                raise NotFound("Room not found in this organization.", code="RESOURCE_NOT_FOUND")
            if room.status != "active":
                raise E(409, "RESOURCE_INACTIVE", "This room is not active.")
            if capacity and room.capacity and capacity > room.capacity:
                raise BadRequest(f"Session capacity ({capacity}) exceeds room capacity ({room.capacity}).", code="SESSION_CAPACITY_EXCEEDS_ROOM")
            if self.repo.room_overlap(room_id, start, end, exclude_id):
                raise E(409, "SESSION_TIME_CONFLICT", "Another session is already scheduled in this room at that time.")
            if BookingRepo(self.db).overlapping_other_event(room_id, start, end, ev.id):
                raise E(409, "RESOURCE_ALREADY_BOOKED", "The room is booked by another request for this time period.")
        if speaker_ids:
            spk_repo = SpeakerRepo(self.db)
            for sid in sorted(set(speaker_ids)):  # fixed lock order avoids deadlocks
                spk = self.db.execute(select(m.Speaker).where(m.Speaker.id == sid).with_for_update()).scalar_one_or_none()
                if not spk or spk.organization_id != ev.organization_id:
                    raise NotFound(f"Speaker {sid} not found in this organization.", code="SPEAKER_NOT_FOUND")
                if self.repo.speaker_overlap(sid, start, end, exclude_id):
                    raise E(409, "SPEAKER_TIME_CONFLICT", f"Speaker '{spk.name}' is already assigned to an overlapping session.")

    def _flush(self):
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if "ex_session_room_overlap" in str(exc.orig):
                raise E(409, "SESSION_TIME_CONFLICT", "Another session is already scheduled in this room at that time.")
            raise

    def create(self, event_id: int, data: dict) -> m.EventSession:
        ev = load_event(self.db, self.access, event_id, OrgRole.EVENT_MANAGER, for_update=True)
        require_manage(self.access, ev)
        self._writable(ev)
        speaker_ids = data.pop("speaker_ids", [])
        self._validate(ev, start=data["start_time"], end=data["end_time"], room_id=data.get("room_id"),
                       capacity=data.get("capacity"), speaker_ids=speaker_ids)
        s = self.repo.add(m.EventSession(event_id=ev.id, **data))
        self._flush()
        self.repo.set_speakers(s.id, speaker_ids)
        audit(self.db, self.user, ev.organization_id, "session.created", "session", s.id, {"event_id": ev.id})
        broadcast(self.db, self.access.orgs.active_member_ids(ev.organization_id), "session.created", {"session_id": s.id, "event_id": ev.id})
        self.db.commit()
        self.db.refresh(s)
        return self._attach(s)

    def list_for_event(self, event_id: int):
        ev = load_event(self.db, self.access, event_id)
        return [self._attach(s) for s in self.repo.for_event(ev.id)]

    def get(self, sid: int):
        s, _ = self._load(sid)
        return self._attach(s)

    def update(self, sid: int, data: dict) -> m.EventSession:
        s, ev = self._load(sid, OrgRole.EVENT_MANAGER, for_update=True)
        load_event(self.db, self.access, ev.id, OrgRole.EVENT_MANAGER, for_update=True)
        require_manage(self.access, ev)
        self._writable(ev)
        speaker_ids = data.pop("speaker_ids", None)
        merged = {"start_time": s.start_time, "end_time": s.end_time, "room_id": s.room_id, "capacity": s.capacity, **data}
        if merged["end_time"] <= merged["start_time"]:
            raise BadRequest("end_time must be after start_time.", code="INVALID_SESSION_TIME")
        effective_speakers = speaker_ids if speaker_ids is not None else self.repo.speaker_ids(s.id)
        self._validate(ev, start=merged["start_time"], end=merged["end_time"], room_id=merged["room_id"],
                       capacity=merged["capacity"], speaker_ids=effective_speakers, exclude_id=s.id)
        for k, v in data.items():
            setattr(s, k, v)
        self._flush()
        if speaker_ids is not None:
            self.repo.set_speakers(s.id, speaker_ids)
        self._notify_change(ev, s)
        audit(self.db, self.user, ev.organization_id, "session.updated", "session", s.id)
        self.db.commit()
        self.db.refresh(s)
        return self._attach(s)

    def _notify_change(self, ev, s):
        ids = [r.user_id for r in self.db.scalars(select(m.Registration).where(
            m.Registration.event_id == ev.id, m.Registration.status.in_(["confirmed", "attended"])))]
        notify(self.db, ids, NotificationType.SESSION_UPDATED, "Session updated",
               f"Session '{s.title}' of '{ev.name}' was updated.", {"event_id": ev.id, "session_id": s.id})

    def delete(self, sid: int):
        s, ev = self._load(sid, OrgRole.EVENT_MANAGER)
        require_manage(self.access, ev)
        audit(self.db, self.user, ev.organization_id, "session.deleted", "session", s.id)
        self.repo.delete(s)
        self.db.commit()


class SpeakerService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = SpeakerRepo(db)
        self.access = Access(db, user)

    def _load(self, spid, min_role=OrgRole.PARTICIPANT):
        sp = self.repo.get(spid)
        if not sp or self.access.role(sp.organization_id) is None:
            raise NotFound("Speaker not found.", code="SPEAKER_NOT_FOUND")
        self.access.require(sp.organization_id, min_role)
        return sp

    def create(self, data: dict):
        self.access.require(data["organization_id"], OrgRole.EVENT_MANAGER)
        sp = self.repo.add(m.Speaker(**data))
        audit(self.db, self.user, sp.organization_id, "speaker.created", "speaker", sp.id)
        self.db.commit()
        return sp

    def list(self, page, page_size, **f):
        return self.repo.list(self.access.org_ids(), page, page_size, **f)

    def get(self, spid): return self._load(spid)

    def update(self, spid, data: dict):
        sp = self._load(spid, OrgRole.EVENT_MANAGER)
        for k, v in data.items():
            setattr(sp, k, v)
        audit(self.db, self.user, sp.organization_id, "speaker.updated", "speaker", sp.id)
        self.db.commit()
        return sp

    def delete(self, spid):
        sp = self._load(spid, OrgRole.EVENT_MANAGER)
        audit(self.db, self.user, sp.organization_id, "speaker.deleted", "speaker", sp.id)
        self.repo.delete(sp)
        self.db.commit()
