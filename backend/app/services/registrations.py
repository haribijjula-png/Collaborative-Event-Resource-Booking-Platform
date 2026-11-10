from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import E, NotFound
from app.models import models as m
from app.models.enums import NotificationType, OrgRole, RegistrationStatus as RS
from app.repositories.repos import AttendanceRepo, EventRepo, OrgRepo, RegistrationRepo
from app.services.common import Access, audit, broadcast, forbidden, notify, utcnow
from app.services.events import load_event


class RegistrationService:
    """All seat accounting happens while holding a row lock on the event (SELECT ... FOR UPDATE),
    which serialises concurrent register / cancel / approve operations per event."""

    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.events = EventRepo(db)
        self.regs = RegistrationRepo(db)
        self.access = Access(db, user)

    # ---------- helpers ----------
    def _load(self, reg_id: int, min_role=OrgRole.PARTICIPANT) -> m.Registration:
        reg = self.regs.get(reg_id)
        if not reg:
            raise NotFound("Registration not found.", code="REGISTRATION_NOT_FOUND")
        ev = self.events.get(reg.event_id)
        role = self.access.role(ev.organization_id)
        if role is None:
            raise NotFound("Registration not found.", code="REGISTRATION_NOT_FOUND")
        privileged = self.access.has(ev.organization_id, OrgRole.STAFF)
        if not privileged and reg.user_id != self.user.id:
            raise forbidden("You can only access your own registrations.")
        if min_role != OrgRole.PARTICIPANT:
            self.access.require(ev.organization_id, min_role)
        return reg

    def _confirm(self, ev: m.Event, reg: m.Registration):
        reg.status = RS.CONFIRMED.value
        self.regs.remove_waitlist(reg.id)
        att = AttendanceRepo(self.db)
        if not att.for_user_event(ev.id, reg.user_id):
            att.add(m.Attendance(event_id=ev.id, user_id=reg.user_id, registration_id=reg.id, status="registered"))
        notify(self.db, [reg.user_id], NotificationType.REGISTRATION_CONFIRMED, "Registration confirmed",
               f"You're confirmed for '{ev.name}'.", {"event_id": ev.id, "registration_id": reg.id})
        broadcast(self.db, [reg.user_id], "registration.updated", {"registration_id": reg.id, "status": reg.status, "event_id": ev.id})

    def _waitlist(self, ev: m.Event, reg: m.Registration):
        reg.status = RS.WAITLISTED.value
        self.regs.add_waitlist(ev.id, reg.id)
        notify(self.db, [reg.user_id], NotificationType.REGISTRATION_WAITLISTED, "Added to waitlist",
               f"'{ev.name}' is full. You're on the waitlist.", {"event_id": ev.id, "registration_id": reg.id})

    def promote_waitlist(self, ev: m.Event) -> list[m.Registration]:
        """Automatic waitlist promotion. Caller must hold the event row lock."""
        promoted = []
        if ev.status not in ("published", "ongoing"):
            return promoted
        while self.events.seat_count(ev.id) < ev.capacity:
            nxt = self.regs.next_waitlisted(ev.id)
            if not nxt:
                break
            self._confirm(ev, nxt)
            self.db.flush()
            promoted.append(nxt)
        return promoted

    # ---------- use cases ----------
    def register(self, event_id: int, notes: str | None) -> m.Registration:
        ev = load_event(self.db, self.access, event_id, for_update=True)
        if ev.status == "cancelled":
            raise E(409, "EVENT_CANCELLED", "This event has been cancelled.")
        if ev.status != "published":
            raise E(409, "INVALID_EVENT_STATUS", f"Registration is not open for {ev.status} events.")
        now = utcnow()
        if now >= (ev.registration_deadline or ev.start_time):
            raise E(409, "REGISTRATION_CLOSED", "Registration for this event has closed.")
        if self.regs.active_for(ev.id, self.user.id):
            raise E(409, "DUPLICATE_REGISTRATION", "You are already registered for this event.")
        reg = m.Registration(event_id=ev.id, user_id=self.user.id, notes=notes, status=RS.PENDING.value)
        try:
            self.regs.add(reg)
        except IntegrityError:
            self.db.rollback()
            raise E(409, "DUPLICATE_REGISTRATION", "You are already registered for this event.")
        if ev.requires_approval:
            audit(self.db, self.user, ev.organization_id, "registration.pending", "registration", reg.id)
        elif self.events.seat_count(ev.id) < ev.capacity:
            self._confirm(ev, reg)
        else:
            self._waitlist(ev, reg)
        audit(self.db, self.user, ev.organization_id, f"registration.{reg.status}", "registration", reg.id, {"event_id": ev.id})
        staff_ids = OrgRepo(self.db).active_member_ids(ev.organization_id, (OrgRole.ORG_ADMIN.value, OrgRole.EVENT_MANAGER.value, OrgRole.STAFF.value))
        broadcast(self.db, staff_ids, "registration.created", {"registration_id": reg.id, "event_id": ev.id, "status": reg.status})
        self.db.commit()
        self.db.refresh(reg)
        return reg

    def cancel(self, reg_id: int) -> m.Registration:
        reg = self._load(reg_id)
        ev = self.events.get(reg.event_id, for_update=True)
        self.db.refresh(reg)  # re-read under lock
        if reg.status not in (RS.PENDING.value, RS.CONFIRMED.value, RS.WAITLISTED.value):
            raise E(409, "INVALID_REGISTRATION_STATUS", f"A {reg.status} registration cannot be cancelled.")
        held_seat = reg.status == RS.CONFIRMED.value
        reg.status = RS.CANCELLED.value
        self.regs.remove_waitlist(reg.id)
        att = AttendanceRepo(self.db).for_user_event(ev.id, reg.user_id)
        if att and att.status == "registered":
            self.db.delete(att)
        self.db.flush()
        notify(self.db, [reg.user_id], NotificationType.REGISTRATION_CANCELLED, "Registration cancelled",
               f"Your registration for '{ev.name}' was cancelled.", {"event_id": ev.id, "registration_id": reg.id})
        if held_seat:
            self.promote_waitlist(ev)  # cancelled registrations release capacity
        audit(self.db, self.user, ev.organization_id, "registration.cancelled", "registration", reg.id)
        self.db.commit()
        self.db.refresh(reg)
        return reg

    def approve(self, reg_id: int) -> m.Registration:
        reg = self._load(reg_id, OrgRole.STAFF)
        ev = self.events.get(reg.event_id, for_update=True)
        self.db.refresh(reg)
        if ev.status == "cancelled":
            raise E(409, "EVENT_CANCELLED", "This event has been cancelled.")
        if reg.status != RS.PENDING.value:
            raise E(409, "INVALID_REGISTRATION_STATUS", "Only pending registrations can be approved.")
        if self.events.seat_count(ev.id) < ev.capacity:
            self._confirm(ev, reg)
        else:
            self._waitlist(ev, reg)
        audit(self.db, self.user, ev.organization_id, "registration.approved", "registration", reg.id, {"result": reg.status})
        self.db.commit()
        self.db.refresh(reg)
        return reg

    def reject(self, reg_id: int, reason: str | None) -> m.Registration:
        reg = self._load(reg_id, OrgRole.STAFF)
        ev = self.events.get(reg.event_id, for_update=True)
        self.db.refresh(reg)
        if reg.status not in (RS.PENDING.value, RS.WAITLISTED.value):
            raise E(409, "INVALID_REGISTRATION_STATUS", "Only pending or waitlisted registrations can be rejected.")
        reg.status = RS.REJECTED.value
        self.regs.remove_waitlist(reg.id)
        notify(self.db, [reg.user_id], NotificationType.REGISTRATION_REJECTED, "Registration rejected",
               f"Your registration for '{ev.name}' was rejected." + (f" Reason: {reason}" if reason else ""),
               {"event_id": ev.id, "registration_id": reg.id})
        audit(self.db, self.user, ev.organization_id, "registration.rejected", "registration", reg.id, {"reason": reason})
        self.db.commit()
        self.db.refresh(reg)
        return reg

    def get(self, reg_id: int) -> m.Registration:
        reg = self._load(reg_id)
        return reg

    def list_for_event(self, event_id: int, page, page_size, **f):
        ev = load_event(self.db, self.access, event_id)
        return self.list(page, page_size, event_id=ev.id, **f)

    def list(self, page, page_size, **f):
        return self.regs.list(page, page_size, scope_org_ids=self.access.org_ids(),
                              privileged_org_ids=self.access.privileged_org_ids(), scope_user_id=self.user.id, **f)
