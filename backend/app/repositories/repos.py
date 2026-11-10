"""Repositories: all SQL lives here. Services never build queries directly."""
from datetime import datetime
from typing import Generic, TypeVar

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import models as m
from app.models.enums import (ACTIVE_REG_STATUSES, BLOCKING_BOOKING, SEAT_STATUSES, BookingStatus, EventStatus,
                              RegistrationStatus)

M = TypeVar("M")


def paginate(db: Session, stmt, page: int, page_size: int, unique: bool = False):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size))
    items = list(rows.unique().scalars()) if unique else list(rows.scalars())
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if page_size else 0}


def apply_sort(stmt, model, sort: str | None, allowed: set[str], default):
    if not sort:
        return stmt.order_by(default)
    desc = sort.startswith("-")
    name = sort.lstrip("-+")
    if name not in allowed:
        return stmt.order_by(default)
    col = getattr(model, name)
    return stmt.order_by(col.desc() if desc else col.asc(), model.id)


class BaseRepo(Generic[M]):
    model: type[M]

    def __init__(self, db: Session):
        self.db = db

    def get(self, id_: int, for_update: bool = False):
        stmt = select(self.model).where(self.model.id == id_)
        if for_update:
            stmt = stmt.with_for_update(of=self.model)
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    def delete(self, obj):
        self.db.delete(obj)
        self.db.flush()


class UserRepo(BaseRepo[m.User]):
    model = m.User

    def by_email(self, email: str):
        return self.db.scalar(select(m.User).where(func.lower(m.User.email) == email.lower()))

    def by_username(self, username: str):
        return self.db.scalar(select(m.User).where(func.lower(m.User.username) == username.lower()))

    def by_usernames(self, names: list[str]):
        if not names:
            return []
        return list(self.db.scalars(select(m.User).where(func.lower(m.User.username).in_([n.lower() for n in names]))))


class RefreshTokenRepo(BaseRepo[m.RefreshToken]):
    model = m.RefreshToken

    def by_jti(self, jti: str, for_update: bool = False):
        stmt = select(m.RefreshToken).where(m.RefreshToken.jti == jti)
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.scalar(stmt)

    def revoke_all(self, user_id: int):
        for t in self.db.scalars(select(m.RefreshToken).where(m.RefreshToken.user_id == user_id, m.RefreshToken.revoked.is_(False))):
            t.revoked = True
        self.db.flush()


class OrgRepo(BaseRepo[m.Organization]):
    model = m.Organization

    def membership(self, org_id: int, user_id: int):
        return self.db.scalar(select(m.OrganizationMember).where(
            m.OrganizationMember.organization_id == org_id, m.OrganizationMember.user_id == user_id))

    def member(self, member_id: int, org_id: int):
        return self.db.scalar(select(m.OrganizationMember).where(
            m.OrganizationMember.id == member_id, m.OrganizationMember.organization_id == org_id))

    def count_active_admins(self, org_id: int) -> int:
        return self.db.scalar(select(func.count()).select_from(m.OrganizationMember).where(
            m.OrganizationMember.organization_id == org_id, m.OrganizationMember.role == "org_admin",
            m.OrganizationMember.is_active.is_(True))) or 0

    def for_user(self, user_id: int, is_super: bool):
        if is_super:
            return [(o, "super_admin") for o in self.db.scalars(select(m.Organization).order_by(m.Organization.name))]
        rows = self.db.execute(select(m.Organization, m.OrganizationMember.role).join(m.OrganizationMember).where(
            m.OrganizationMember.user_id == user_id, m.OrganizationMember.is_active.is_(True)).order_by(m.Organization.name))
        return [(o, r) for o, r in rows]

    def members(self, org_id: int, page, page_size, search=None, role=None, is_active=None):
        stmt = select(m.OrganizationMember).join(m.User).where(m.OrganizationMember.organization_id == org_id)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(m.User.full_name.ilike(like), m.User.email.ilike(like), m.User.username.ilike(like)))
        if role:
            stmt = stmt.where(m.OrganizationMember.role == role)
        if is_active is not None:
            stmt = stmt.where(m.OrganizationMember.is_active == is_active)
        return paginate(self.db, stmt.order_by(m.User.full_name), page, page_size, unique=True)

    def active_member_ids(self, org_id: int, roles: tuple[str, ...] | None = None) -> list[int]:
        stmt = select(m.OrganizationMember.user_id).where(
            m.OrganizationMember.organization_id == org_id, m.OrganizationMember.is_active.is_(True))
        if roles:
            stmt = stmt.where(m.OrganizationMember.role.in_(roles))
        return list(self.db.scalars(stmt))


class EventRepo(BaseRepo[m.Event]):
    model = m.Event

    def list(self, org_ids: list[int], page, page_size, *, privileged_org_ids: set[int], status=None, organizer_id=None,
             start_from=None, start_to=None, location=None, search=None, sort=None, organization_id=None):
        stmt = select(m.Event).where(m.Event.organization_id.in_(org_ids))
        # Participants only see published/ongoing/completed events of their orgs.
        visible = or_(m.Event.organization_id.in_(privileged_org_ids or [-1]),
                      m.Event.status.in_(["published", "ongoing", "completed", "cancelled"]))
        stmt = stmt.where(visible)
        if organization_id:
            stmt = stmt.where(m.Event.organization_id == organization_id)
        if status:
            stmt = stmt.where(m.Event.status == status)
        if organizer_id:
            stmt = stmt.where(m.Event.organizer_id == organizer_id)
        if start_from:
            stmt = stmt.where(m.Event.start_time >= start_from)
        if start_to:
            stmt = stmt.where(m.Event.start_time <= start_to)
        if location:
            stmt = stmt.where(m.Event.location.ilike(f"%{location}%"))
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(m.Event.name.ilike(like), m.Event.description.ilike(like), m.Event.location.ilike(like)))
        stmt = apply_sort(stmt, m.Event, sort, {"name", "start_time", "end_time", "created_at", "capacity", "status"}, m.Event.start_time.desc())
        return paginate(self.db, stmt, page, page_size, unique=True)

    def seat_count(self, event_id: int) -> int:
        return self.db.scalar(select(func.count()).select_from(m.Registration).where(
            m.Registration.event_id == event_id, m.Registration.status.in_([s.value for s in SEAT_STATUSES]))) or 0

    def waitlist_count(self, event_id: int) -> int:
        return self.db.scalar(select(func.count()).select_from(m.Registration).where(
            m.Registration.event_id == event_id, m.Registration.status == "waitlisted")) or 0

    def due_for_reminder(self, window_end: datetime, now: datetime):
        return list(self.db.scalars(select(m.Event).where(
            m.Event.status == "published", m.Event.reminder_sent.is_(False),
            m.Event.start_time > now, m.Event.start_time <= window_end).with_for_update(skip_locked=True, of=m.Event)).unique())

    def due_to_start(self, now):
        return list(self.db.scalars(select(m.Event).where(m.Event.status == "published", m.Event.start_time <= now, m.Event.end_time > now)))

    def due_to_complete(self, now):
        return list(self.db.scalars(select(m.Event).where(m.Event.status == "ongoing", m.Event.end_time <= now)))


class RegistrationRepo(BaseRepo[m.Registration]):
    model = m.Registration

    def active_for(self, event_id: int, user_id: int):
        return self.db.scalar(select(m.Registration).where(
            m.Registration.event_id == event_id, m.Registration.user_id == user_id,
            m.Registration.status.in_([s.value for s in ACTIVE_REG_STATUSES])))

    def list(self, page, page_size, *, scope_org_ids, privileged_org_ids, scope_user_id, event_id=None, status=None,
             user_id=None, date_from=None, date_to=None, search=None, sort=None, organization_id=None):
        """Staff+ see every registration in their orgs; everyone else only their own."""
        stmt = (select(m.Registration).join(m.User, m.User.id == m.Registration.user_id)
                .join(m.Event, m.Event.id == m.Registration.event_id)
                .where(m.Event.organization_id.in_(scope_org_ids or [-1]))
                .where(or_(m.Event.organization_id.in_(privileged_org_ids or [-1]), m.Registration.user_id == scope_user_id)))
        if organization_id:
            stmt = stmt.where(m.Event.organization_id == organization_id)
        if event_id:
            stmt = stmt.where(m.Registration.event_id == event_id)
        if status:
            stmt = stmt.where(m.Registration.status == status)
        if user_id:
            stmt = stmt.where(m.Registration.user_id == user_id)
        if date_from:
            stmt = stmt.where(m.Registration.created_at >= date_from)
        if date_to:
            stmt = stmt.where(m.Registration.created_at <= date_to)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(m.User.full_name.ilike(like), m.User.email.ilike(like)))
        stmt = apply_sort(stmt, m.Registration, sort, {"created_at", "status", "updated_at"}, m.Registration.created_at.asc())
        return paginate(self.db, stmt, page, page_size, unique=True)

    def next_waitlisted(self, event_id: int):
        return self.db.execute(
            select(m.Registration).join(m.WaitlistEntry, m.WaitlistEntry.registration_id == m.Registration.id)
            .where(m.WaitlistEntry.event_id == event_id, m.Registration.status == "waitlisted")
            .order_by(m.WaitlistEntry.created_at, m.WaitlistEntry.id).limit(1).with_for_update(of=m.WaitlistEntry)
        ).unique().scalar_one_or_none()

    def add_waitlist(self, event_id: int, registration_id: int):
        self.db.add(m.WaitlistEntry(event_id=event_id, registration_id=registration_id))
        self.db.flush()

    def remove_waitlist(self, registration_id: int):
        for w in self.db.scalars(select(m.WaitlistEntry).where(m.WaitlistEntry.registration_id == registration_id)):
            self.db.delete(w)
        self.db.flush()

    def waitlist_position(self, reg: m.Registration) -> int | None:
        w = self.db.scalar(select(m.WaitlistEntry).where(m.WaitlistEntry.registration_id == reg.id))
        if not w:
            return None
        return self.db.scalar(select(func.count()).select_from(m.WaitlistEntry).where(
            m.WaitlistEntry.event_id == reg.event_id,
            or_(m.WaitlistEntry.created_at < w.created_at, and_(m.WaitlistEntry.created_at == w.created_at, m.WaitlistEntry.id <= w.id)))) 

    def for_event_active(self, event_id: int):
        return list(self.db.scalars(select(m.Registration).where(
            m.Registration.event_id == event_id, m.Registration.status.in_([s.value for s in ACTIVE_REG_STATUSES])).order_by(m.Registration.id)).unique())


class ResourceRepo(BaseRepo[m.Resource]):
    model = m.Resource

    def by_name(self, org_id: int, name: str):
        return self.db.scalar(select(m.Resource).where(m.Resource.organization_id == org_id, func.lower(m.Resource.name) == name.lower()))

    def list(self, org_ids, page, page_size, *, organization_id=None, type=None, status=None, search=None, sort=None):
        stmt = select(m.Resource).where(m.Resource.organization_id.in_(org_ids or [-1]))
        if organization_id:
            stmt = stmt.where(m.Resource.organization_id == organization_id)
        if type:
            stmt = stmt.where(m.Resource.type == type)
        if status:
            stmt = stmt.where(m.Resource.status == status)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(m.Resource.name.ilike(like), m.Resource.location.ilike(like), m.Resource.description.ilike(like)))
        stmt = apply_sort(stmt, m.Resource, sort, {"name", "type", "capacity", "status", "created_at"}, m.Resource.name.asc())
        return paginate(self.db, stmt, page, page_size)


class BookingRepo(BaseRepo[m.ResourceBooking]):
    model = m.ResourceBooking

    def overlapping(self, resource_id: int, start, end, exclude_id: int | None = None):
        stmt = select(m.ResourceBooking).where(
            m.ResourceBooking.resource_id == resource_id,
            m.ResourceBooking.status.in_([s.value for s in BLOCKING_BOOKING]),
            m.ResourceBooking.start_time < end, m.ResourceBooking.end_time > start)
        if exclude_id:
            stmt = stmt.where(m.ResourceBooking.id != exclude_id)
        return self.db.execute(stmt.limit(1)).unique().scalar_one_or_none()

    def list(self, page, page_size, *, scope_org_ids, privileged_org_ids, scope_user_id, resource_id=None, status=None,
             date_from=None, date_to=None, requested_by=None, event_id=None, sort=None, organization_id=None):
        """Staff+ see all bookings in their orgs; others only their own."""
        stmt = (select(m.ResourceBooking).join(m.Resource, m.Resource.id == m.ResourceBooking.resource_id)
                .where(m.Resource.organization_id.in_(scope_org_ids or [-1]))
                .where(or_(m.Resource.organization_id.in_(privileged_org_ids or [-1]), m.ResourceBooking.requested_by == scope_user_id)))
        if organization_id:
            stmt = stmt.where(m.Resource.organization_id == organization_id)
        if resource_id:
            stmt = stmt.where(m.ResourceBooking.resource_id == resource_id)
        if status:
            stmt = stmt.where(m.ResourceBooking.status == status)
        if requested_by:
            stmt = stmt.where(m.ResourceBooking.requested_by == requested_by)
        if event_id:
            stmt = stmt.where(m.ResourceBooking.event_id == event_id)
        if date_from:
            stmt = stmt.where(m.ResourceBooking.end_time >= date_from)
        if date_to:
            stmt = stmt.where(m.ResourceBooking.start_time <= date_to)
        stmt = apply_sort(stmt, m.ResourceBooking, sort, {"start_time", "end_time", "status", "created_at"}, m.ResourceBooking.start_time.asc())
        return paginate(self.db, stmt, page, page_size, unique=True)

    def overlapping_other_event(self, resource_id: int, start, end, event_id: int):
        stmt = select(m.ResourceBooking).where(
            m.ResourceBooking.resource_id == resource_id,
            m.ResourceBooking.status.in_([s.value for s in BLOCKING_BOOKING]),
            m.ResourceBooking.start_time < end, m.ResourceBooking.end_time > start,
            or_(m.ResourceBooking.event_id.is_(None), m.ResourceBooking.event_id != event_id))
        return self.db.execute(stmt.limit(1)).unique().scalar_one_or_none()

    def for_event(self, event_id: int):
        return list(self.db.scalars(select(m.ResourceBooking).where(m.ResourceBooking.event_id == event_id)).unique())

    def due_complete(self, now):
        return list(self.db.scalars(select(m.ResourceBooking).where(m.ResourceBooking.status == "approved", m.ResourceBooking.end_time <= now)).unique())


class SessionRepo(BaseRepo[m.EventSession]):
    model = m.EventSession

    def for_event(self, event_id: int):
        return list(self.db.scalars(select(m.EventSession).where(m.EventSession.event_id == event_id).order_by(m.EventSession.start_time)).unique())

    def room_overlap(self, room_id: int, start, end, exclude_id=None):
        stmt = select(m.EventSession).where(m.EventSession.room_id == room_id, m.EventSession.start_time < end, m.EventSession.end_time > start)
        if exclude_id:
            stmt = stmt.where(m.EventSession.id != exclude_id)
        return self.db.execute(stmt.limit(1)).unique().scalar_one_or_none()

    def speaker_ids(self, session_id: int) -> list[int]:
        return list(self.db.scalars(select(m.SpeakerSession.speaker_id).where(m.SpeakerSession.session_id == session_id)))

    def speakers(self, session_id: int):
        return list(self.db.scalars(select(m.Speaker).join(m.SpeakerSession).where(m.SpeakerSession.session_id == session_id)))

    def set_speakers(self, session_id: int, speaker_ids: list[int]):
        for ss in self.db.scalars(select(m.SpeakerSession).where(m.SpeakerSession.session_id == session_id)):
            self.db.delete(ss)
        self.db.flush()
        for sid in dict.fromkeys(speaker_ids):
            self.db.add(m.SpeakerSession(speaker_id=sid, session_id=session_id))
        self.db.flush()

    def speaker_overlap(self, speaker_id: int, start, end, exclude_session_id=None):
        stmt = select(m.EventSession).join(m.SpeakerSession, m.SpeakerSession.session_id == m.EventSession.id).where(
            m.SpeakerSession.speaker_id == speaker_id, m.EventSession.start_time < end, m.EventSession.end_time > start)
        if exclude_session_id:
            stmt = stmt.where(m.EventSession.id != exclude_session_id)
        return self.db.execute(stmt.limit(1)).unique().scalar_one_or_none()


class SpeakerRepo(BaseRepo[m.Speaker]):
    model = m.Speaker

    def list(self, org_ids, page, page_size, organization_id=None, search=None):
        stmt = select(m.Speaker).where(m.Speaker.organization_id.in_(org_ids or [-1]))
        if organization_id:
            stmt = stmt.where(m.Speaker.organization_id == organization_id)
        if search:
            stmt = stmt.where(m.Speaker.name.ilike(f"%{search}%"))
        return paginate(self.db, stmt.order_by(m.Speaker.name), page, page_size)


class AttendanceRepo(BaseRepo[m.Attendance]):
    model = m.Attendance

    def for_user_event(self, event_id: int, user_id: int):
        return self.db.execute(select(m.Attendance).where(m.Attendance.event_id == event_id, m.Attendance.user_id == user_id)).unique().scalar_one_or_none()

    def list(self, event_id, page, page_size, status=None):
        stmt = select(m.Attendance).where(m.Attendance.event_id == event_id)
        if status:
            stmt = stmt.where(m.Attendance.status == status)
        return paginate(self.db, stmt.order_by(m.Attendance.id), page, page_size, unique=True)

    def all_for_event(self, event_id):
        return list(self.db.scalars(select(m.Attendance).where(m.Attendance.event_id == event_id).order_by(m.Attendance.id)).unique())


class CommentRepo(BaseRepo[m.Comment]):
    model = m.Comment

    def list(self, page, page_size, event_id=None, session_id=None):
        stmt = select(m.Comment)
        stmt = stmt.where(m.Comment.event_id == event_id) if event_id else stmt.where(m.Comment.session_id == session_id)
        return paginate(self.db, stmt.order_by(m.Comment.created_at.desc(), m.Comment.id.desc()), page, page_size, unique=True)


class AttachmentRepo(BaseRepo[m.Attachment]):
    model = m.Attachment

    def for_event(self, event_id, entity_type=None, entity_id=None):
        stmt = select(m.Attachment).where(m.Attachment.event_id == event_id)
        if entity_type:
            stmt = stmt.where(m.Attachment.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(m.Attachment.entity_id == entity_id)
        return list(self.db.scalars(stmt.order_by(m.Attachment.id.desc())))


class NotificationRepo(BaseRepo[m.Notification]):
    model = m.Notification

    def list(self, user_id, page, page_size, is_read=None):
        stmt = select(m.Notification).where(m.Notification.user_id == user_id)
        if is_read is not None:
            stmt = stmt.where(m.Notification.is_read == is_read)
        return paginate(self.db, stmt.order_by(m.Notification.created_at.desc(), m.Notification.id.desc()), page, page_size)

    def unread_count(self, user_id):
        return self.db.scalar(select(func.count()).select_from(m.Notification).where(m.Notification.user_id == user_id, m.Notification.is_read.is_(False))) or 0

    def mark_all_read(self, user_id) -> int:
        from sqlalchemy import update
        res = self.db.execute(update(m.Notification).where(m.Notification.user_id == user_id, m.Notification.is_read.is_(False)).values(is_read=True))
        return res.rowcount


class AuditRepo(BaseRepo[m.AuditLog]):
    model = m.AuditLog

    def list(self, org_id, page, page_size, action=None):
        stmt = select(m.AuditLog).where(m.AuditLog.organization_id == org_id)
        if action:
            stmt = stmt.where(m.AuditLog.action == action)
        return paginate(self.db, stmt.order_by(m.AuditLog.id.desc()), page, page_size)
