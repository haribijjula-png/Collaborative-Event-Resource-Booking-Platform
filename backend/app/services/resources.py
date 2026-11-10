from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Conflict, E, NotFound
from app.models import models as m
from app.models.enums import NotificationType, OrgRole
from app.repositories.repos import BookingRepo, EventRepo, ResourceRepo
from app.services.common import Access, audit, broadcast, forbidden, notify, utcnow


class ResourceService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = ResourceRepo(db)
        self.access = Access(db, user)

    def _load(self, rid: int, min_role=OrgRole.PARTICIPANT, for_update=False) -> m.Resource:
        r = self.repo.get(rid, for_update=for_update)
        if not r or self.access.role(r.organization_id) is None:
            raise NotFound("Resource not found.", code="RESOURCE_NOT_FOUND")
        self.access.require(r.organization_id, min_role)
        return r

    def create(self, data: dict) -> m.Resource:
        org_id = data.pop("organization_id")
        self.access.require(org_id, OrgRole.ORG_ADMIN)
        data["type"] = data["type"].value
        if self.repo.by_name(org_id, data["name"]):
            raise Conflict("A resource with this name already exists.", code="RESOURCE_EXISTS")
        r = self.repo.add(m.Resource(organization_id=org_id, **data))
        audit(self.db, self.user, org_id, "resource.created", "resource", r.id, {"name": r.name})
        self.db.commit()
        return r

    def list(self, page, page_size, **f):
        return self.repo.list(self.access.org_ids(), page, page_size, **f)

    def get(self, rid): return self._load(rid)

    def update(self, rid, data: dict):
        r = self._load(rid, OrgRole.ORG_ADMIN)
        if "type" in data and data["type"] is not None:
            data["type"] = data["type"].value
        if "name" in data and data["name"].lower() != r.name.lower() and self.repo.by_name(r.organization_id, data["name"]):
            raise Conflict("A resource with this name already exists.", code="RESOURCE_EXISTS")
        for k, v in data.items():
            setattr(r, k, v)
        audit(self.db, self.user, r.organization_id, "resource.updated", "resource", r.id)
        self.db.commit()
        return r

    def set_status(self, rid, active: bool):
        r = self._load(rid, OrgRole.ORG_ADMIN)
        r.status = "active" if active else "inactive"
        audit(self.db, self.user, r.organization_id, "resource.activated" if active else "resource.deactivated", "resource", r.id)
        self.db.commit()
        return r


class BookingService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = BookingRepo(db)
        self.resources = ResourceRepo(db)
        self.access = Access(db, user)

    def _load(self, bid: int, for_update=False) -> m.ResourceBooking:
        b = self.repo.get(bid, for_update=for_update)
        if not b or self.access.role(b.resource.organization_id) is None:
            raise NotFound("Booking not found.", code="BOOKING_NOT_FOUND")
        if b.requested_by != self.user.id and not self.access.has(b.resource.organization_id, OrgRole.STAFF):
            raise forbidden("You can only access your own bookings.")
        return b

    def _check_free(self, resource_id, start, end, exclude_id=None):
        if self.repo.overlapping(resource_id, start, end, exclude_id):
            raise E(409, "RESOURCE_ALREADY_BOOKED", "The selected resource is already booked for this time period.")

    def _flush_or_conflict(self):
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if "ex_booking_overlap" in str(exc.orig):
                raise E(409, "RESOURCE_ALREADY_BOOKED", "The selected resource is already booked for this time period.")
            raise

    def create(self, data: dict) -> m.ResourceBooking:
        res = self.resources.get(data["resource_id"], for_update=True)  # serialise bookings per resource
        if not res or self.access.role(res.organization_id) is None:
            raise NotFound("Resource not found.", code="RESOURCE_NOT_FOUND")
        self.access.require(res.organization_id, OrgRole.STAFF)
        if res.status != "active":
            raise E(409, "RESOURCE_INACTIVE", "This resource is not available for booking.")
        if data["start_time"] < utcnow():
            raise BadRequest("Bookings cannot start in the past.", code="BOOKING_IN_THE_PAST")
        if data.get("event_id"):
            ev = EventRepo(self.db).get(data["event_id"])
            if not ev or ev.organization_id != res.organization_id:
                raise NotFound("Event not found in this organization.", code="EVENT_NOT_FOUND")
            if ev.status in ("cancelled", "archived", "completed"):
                raise E(409, "INVALID_EVENT_STATUS", f"Cannot book resources for a {ev.status} event.")
        self._check_free(res.id, data["start_time"], data["end_time"])
        b = self.repo.add(m.ResourceBooking(requested_by=self.user.id, status="requested", **data))
        self._flush_or_conflict()
        audit(self.db, self.user, res.organization_id, "booking.requested", "booking", b.id, {"resource_id": res.id})
        broadcast(self.db, self.access.orgs.active_member_ids(res.organization_id, ("org_admin", "event_manager")), "booking.created",
                  {"booking_id": b.id, "resource_id": res.id})
        self.db.commit()
        self.db.refresh(b)
        return b

    def get(self, bid): return self._load(bid)

    def list(self, page, page_size, **f):
        return self.repo.list(page, page_size, scope_org_ids=self.access.org_ids(),
                              privileged_org_ids=self.access.privileged_org_ids(), scope_user_id=self.user.id, **f)

    def update(self, bid: int, data: dict) -> m.ResourceBooking:
        b = self._load(bid, for_update=True)
        org = b.resource.organization_id
        is_admin = self.access.has(org, OrgRole.ORG_ADMIN)
        if b.requested_by != self.user.id and not is_admin:
            raise forbidden("Only the requester or an organization admin can modify this booking.")
        if b.status not in ("requested", "approved") or (b.status == "approved" and not is_admin):
            raise E(409, "INVALID_BOOKING_STATUS", f"A {b.status} booking cannot be modified.")
        self.resources.get(b.resource_id, for_update=True)
        start, end = data.get("start_time", b.start_time), data.get("end_time", b.end_time)
        if end <= start:
            raise BadRequest("end_time must be after start_time.", code="INVALID_BOOKING_TIME")
        if ("start_time" in data or "end_time" in data):
            if start < utcnow():
                raise BadRequest("Bookings cannot start in the past.", code="BOOKING_IN_THE_PAST")
            self._check_free(b.resource_id, start, end, exclude_id=b.id)
        for k, v in data.items():
            setattr(b, k, v)
        self._flush_or_conflict()
        audit(self.db, self.user, org, "booking.updated", "booking", b.id)
        self.db.commit()
        self.db.refresh(b)
        return b

    def decide(self, bid: int, approve: bool) -> m.ResourceBooking:
        b = self.repo.get(bid, for_update=True)
        if not b or self.access.role(b.resource.organization_id) is None:
            raise NotFound("Booking not found.", code="BOOKING_NOT_FOUND")
        self.access.require(b.resource.organization_id, OrgRole.EVENT_MANAGER)
        if b.status != "requested":
            raise E(409, "INVALID_BOOKING_STATUS", "Only requested bookings can be approved or rejected.")
        if approve and b.end_time <= utcnow():
            raise E(409, "INVALID_BOOKING_STATUS", "This booking is already in the past.")
        b.status = "approved" if approve else "rejected"
        ntype = NotificationType.BOOKING_APPROVED if approve else NotificationType.BOOKING_REJECTED
        notify(self.db, [b.requested_by], ntype, f"Booking {b.status}",
               f"Your booking for '{b.resource.name}' was {b.status}.", {"booking_id": b.id, "resource_id": b.resource_id})
        broadcast(self.db, [b.requested_by], "booking.updated", {"booking_id": b.id, "status": b.status})
        audit(self.db, self.user, b.resource.organization_id, f"booking.{b.status}", "booking", b.id)
        self.db.commit()
        self.db.refresh(b)
        return b

    def cancel(self, bid: int) -> m.ResourceBooking:
        b = self._load(bid, for_update=True)
        org = b.resource.organization_id
        if b.requested_by != self.user.id and not self.access.has(org, OrgRole.EVENT_MANAGER):
            raise forbidden("Only the requester or an event manager can cancel this booking.")
        if b.status not in ("requested", "approved"):
            raise E(409, "INVALID_BOOKING_STATUS", f"A {b.status} booking cannot be cancelled.")
        b.status = "cancelled"
        audit(self.db, self.user, org, "booking.cancelled", "booking", b.id)
        self.db.commit()
        self.db.refresh(b)
        return b
