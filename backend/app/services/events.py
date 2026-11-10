from sqlalchemy.orm import Session

from app.core.errors import BadRequest, E, NotFound
from app.models import models as m
from app.models.enums import EVENT_TRANSITIONS, EventStatus, OrgRole, NotificationType
from app.repositories.repos import BookingRepo, EventRepo, OrgRepo, RegistrationRepo, SessionRepo
from app.services.common import Access, audit, broadcast, forbidden, notify, utcnow


def load_event(db: Session, access: Access, event_id: int, min_role: OrgRole = OrgRole.PARTICIPANT, for_update=False) -> m.Event:
    """Fetch an event and enforce organization-level access. 404 (not 403) for events in other organizations
    so existence is not leaked across tenants."""
    ev = EventRepo(db).get(event_id, for_update=for_update)
    if not ev:
        raise NotFound("Event not found.", code="EVENT_NOT_FOUND")
    role = access.role(ev.organization_id)
    if role is None:
        raise NotFound("Event not found.", code="EVENT_NOT_FOUND")
    if role == OrgRole.PARTICIPANT and ev.status in ("draft", "archived"):
        raise NotFound("Event not found.", code="EVENT_NOT_FOUND")
    access.require(ev.organization_id, min_role)
    return ev


def can_manage_event(access: Access, ev: m.Event) -> bool:
    """Event-level authorization: org admins, or the event manager who organizes this event."""
    role = access.role(ev.organization_id)
    return role == OrgRole.ORG_ADMIN or (role == OrgRole.EVENT_MANAGER and ev.organizer_id == access.user.id)


def require_manage(access: Access, ev: m.Event):
    if not can_manage_event(access, ev):
        raise forbidden("Only the event organizer or an organization admin can do this.")


class EventService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = EventRepo(db)
        self.access = Access(db, user)

    # ---------- CRUD ----------
    def create(self, data: dict) -> m.Event:
        org_id = data.pop("organization_id")
        self.access.require(org_id, OrgRole.EVENT_MANAGER)
        ev = self.repo.add(m.Event(organization_id=org_id, organizer_id=self.user.id, status=EventStatus.DRAFT.value, **data))
        audit(self.db, self.user, org_id, "event.created", "event", ev.id, {"name": ev.name})
        self.db.commit()
        self.db.refresh(ev)
        return ev

    def list(self, page, page_size, **f):
        return self.repo.list(self.access.org_ids(), page, page_size, privileged_org_ids=self.access.privileged_org_ids(), **f)

    def get(self, event_id: int) -> m.Event:
        ev = load_event(self.db, self.access, event_id)
        ev.confirmed_count = self.repo.seat_count(ev.id)
        ev.waitlist_count = self.repo.waitlist_count(ev.id)
        mine = RegistrationRepo(self.db).active_for(ev.id, self.user.id)
        ev.my_registration_status = mine.status if mine else None
        return ev

    def update(self, event_id: int, data: dict) -> m.Event:
        from app.services.registrations import RegistrationService
        ev = load_event(self.db, self.access, event_id, OrgRole.EVENT_MANAGER, for_update=True)
        require_manage(self.access, ev)
        if ev.status in ("cancelled", "completed", "archived"):
            raise E(409, "INVALID_EVENT_STATUS", f"A {ev.status} event cannot be modified.")
        start = data.get("start_time", ev.start_time)
        end = data.get("end_time", ev.end_time)
        if end <= start:
            raise BadRequest("end_time must be after start_time.", code="INVALID_EVENT_TIME")
        deadline = data.get("registration_deadline", ev.registration_deadline)
        if deadline and deadline > end:
            raise BadRequest("registration_deadline must be before the event ends.", code="INVALID_EVENT_TIME")
        if "start_time" in data or "end_time" in data:
            for s in SessionRepo(self.db).for_event(ev.id):
                if s.start_time < start or s.end_time > end:
                    raise E(409, "SESSION_OUTSIDE_EVENT", "Existing sessions would fall outside the new event time range.")
        new_cap = data.get("capacity")
        if new_cap is not None and new_cap < self.repo.seat_count(ev.id):
            raise E(409, "EVENT_CAPACITY_EXCEEDED", "Capacity cannot be lower than the number of confirmed registrations.")
        for k, v in data.items():
            setattr(ev, k, v)
        self.db.flush()
        if new_cap is not None:  # more seats may now be available
            RegistrationService(self.db, self.user).promote_waitlist(ev)
        audit(self.db, self.user, ev.organization_id, "event.updated", "event", ev.id, {k: str(v) for k, v in data.items()})
        self.db.commit()
        self.db.refresh(ev)
        return ev

    def delete(self, event_id: int):
        ev = load_event(self.db, self.access, event_id, OrgRole.EVENT_MANAGER, for_update=True)
        require_manage(self.access, ev)
        if ev.status not in ("draft", "cancelled"):
            raise E(409, "INVALID_EVENT_STATUS", "Only draft or cancelled events can be deleted.")
        audit(self.db, self.user, ev.organization_id, "event.deleted", "event", ev.id, {"name": ev.name})
        self.repo.delete(ev)
        self.db.commit()

    # ---------- status machine ----------
    def transition(self, event_id: int, target: EventStatus) -> m.Event:
        ev = load_event(self.db, self.access, event_id, OrgRole.EVENT_MANAGER, for_update=True)
        require_manage(self.access, ev)
        self._apply(ev, target)
        self.db.commit()
        self.db.refresh(ev)
        return ev

    def _apply(self, ev: m.Event, target: EventStatus, actor: m.User | None = None):
        current = EventStatus(ev.status)
        if target not in EVENT_TRANSITIONS[current]:
            raise E(409, "INVALID_EVENT_STATUS", f"Cannot change event status from '{current.value}' to '{target.value}'.")
        if target == EventStatus.PUBLISHED and ev.end_time <= utcnow():
            raise E(409, "INVALID_EVENT_STATUS", "An event that has already ended cannot be published.")
        ev.status = target.value
        self.db.flush()
        actor = actor or self.user
        audit(self.db, actor, ev.organization_id, f"event.{target.value}", "event", ev.id, {"from": current.value})
        orgs = OrgRepo(self.db)
        if target == EventStatus.PUBLISHED:
            notify(self.db, orgs.active_member_ids(ev.organization_id), NotificationType.EVENT_PUBLISHED, "New event published",
                   f"'{ev.name}' is now open for registration.", {"event_id": ev.id})
        elif target == EventStatus.CANCELLED:
            self._cascade_cancel(ev)
        broadcast(self.db, orgs.active_member_ids(ev.organization_id), "event.status_changed", {"event_id": ev.id, "status": ev.status})

    def _cascade_cancel(self, ev: m.Event):
        regs = RegistrationRepo(self.db)
        affected = []
        for r in regs.for_event_active(ev.id):
            r.status = "cancelled"
            regs.remove_waitlist(r.id)
            affected.append(r.user_id)
        for a in self.db.query(m.Attendance).filter(m.Attendance.event_id == ev.id, m.Attendance.status == "registered"):
            self.db.delete(a)
        for b in BookingRepo(self.db).for_event(ev.id):
            if b.status in ("requested", "approved"):
                b.status = "cancelled"
        notify(self.db, affected, NotificationType.EVENT_CANCELLED, "Event cancelled",
               f"'{ev.name}' has been cancelled.", {"event_id": ev.id})
        self.db.flush()

    # ---------- scheduler hooks ----------
    def auto_progress(self):
        now = utcnow()
        for ev in self.repo.due_to_start(now):
            self._auto(ev, EventStatus.ONGOING)
        for ev in self.repo.due_to_complete(now):
            self._auto(ev, EventStatus.COMPLETED)
        for b in BookingRepo(self.db).due_complete(now):
            b.status = "completed"
        self.db.commit()

    def _auto(self, ev, target):
        ev.status = target.value
        audit(self.db, None, ev.organization_id, f"event.{target.value}", "event", ev.id, {"auto": True})
        broadcast(self.db, OrgRepo(self.db).active_member_ids(ev.organization_id), "event.status_changed", {"event_id": ev.id, "status": ev.status})
