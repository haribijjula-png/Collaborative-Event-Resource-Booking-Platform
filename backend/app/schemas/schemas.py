import re
from datetime import datetime, timezone
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import (AttendanceStatus, EventStatus, OrgRole, RegistrationStatus, ResourceStatus, ResourceType)


def _aware(v: datetime) -> datetime:
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


DT = Annotated[datetime, AfterValidator(_aware)]
T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(BaseModel):
    message: str


# ---------------- Auth / users ----------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")


def _strong_password(v: str) -> str:
    if len(v) < 8 or not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("Password must be at least 8 characters and include a letter and a digit.")
    return v


Password = Annotated[str, AfterValidator(_strong_password)]


class RegisterIn(BaseModel):
    email: EmailStr
    username: str
    full_name: str = Field(min_length=1, max_length=120)
    password: Password

    @field_validator("username")
    @classmethod
    def _u(cls, v):
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3-50 chars: letters, digits, _ . -")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: Password


class UserOut(ORM):
    id: int
    email: str
    username: str
    full_name: str
    is_active: bool
    is_super_admin: bool


class UserBrief(ORM):
    id: int
    username: str
    full_name: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class AuthOut(TokenOut):
    user: UserOut


# ---------------- Organizations ----------------
class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None
    is_active: bool | None = None


class OrgOut(ORM):
    id: int
    name: str
    description: str | None
    is_active: bool
    created_at: datetime


class OrgWithRole(OrgOut):
    my_role: str | None = None


class MemberAdd(BaseModel):
    email: EmailStr
    role: OrgRole = OrgRole.PARTICIPANT


class MemberRoleIn(BaseModel):
    role: OrgRole


class MemberOut(ORM):
    id: int
    organization_id: int
    user_id: int
    role: str
    is_active: bool
    user: UserBrief
    created_at: datetime


# ---------------- Events ----------------
class EventBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    location: str | None = Field(default=None, max_length=255)
    start_time: DT
    end_time: DT
    capacity: int = Field(gt=0, le=1_000_000)
    registration_deadline: DT | None = None
    requires_approval: bool = False

    @model_validator(mode="after")
    def _times(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.registration_deadline and self.registration_deadline > self.end_time:
            raise ValueError("registration_deadline must be before the event ends")
        return self


class EventCreate(EventBase):
    organization_id: int


class EventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    location: str | None = None
    start_time: DT | None = None
    end_time: DT | None = None
    capacity: int | None = Field(default=None, gt=0)
    registration_deadline: DT | None = None
    requires_approval: bool | None = None


class EventStatusIn(BaseModel):
    status: EventStatus


class EventOut(ORM):
    id: int
    organization_id: int
    organizer_id: int
    organizer: UserBrief
    name: str
    description: str | None
    location: str | None
    start_time: datetime
    end_time: datetime
    capacity: int
    registration_deadline: datetime | None
    requires_approval: bool
    status: str
    created_at: datetime
    updated_at: datetime


class EventDetail(EventOut):
    confirmed_count: int = 0
    waitlist_count: int = 0
    my_registration_status: str | None = None


# ---------------- Registrations ----------------
class RegisterEventIn(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)


class RegistrationOut(ORM):
    id: int
    event_id: int
    user_id: int
    user: UserBrief
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class RegistrationDecision(BaseModel):
    reason: str | None = None


# ---------------- Resources ----------------
class ResourceCreate(BaseModel):
    organization_id: int
    name: str = Field(min_length=2, max_length=150)
    type: ResourceType
    description: str | None = None
    location: str | None = None
    capacity: int | None = Field(default=None, gt=0)


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    type: ResourceType | None = None
    description: str | None = None
    location: str | None = None
    capacity: int | None = Field(default=None, gt=0)


class ResourceOut(ORM):
    id: int
    organization_id: int
    name: str
    type: str
    description: str | None
    location: str | None
    capacity: int | None
    status: str


# ---------------- Bookings ----------------
class BookingCreate(BaseModel):
    resource_id: int
    event_id: int | None = None
    start_time: DT
    end_time: DT
    purpose: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _t(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class BookingUpdate(BaseModel):
    start_time: DT | None = None
    end_time: DT | None = None
    purpose: str | None = None
    event_id: int | None = None


class BookingOut(ORM):
    id: int
    resource_id: int
    resource: ResourceOut
    event_id: int | None
    requested_by: int
    start_time: datetime
    end_time: datetime
    status: str
    purpose: str | None
    created_at: datetime
    updated_at: datetime


# ---------------- Sessions / speakers ----------------
class SessionBase(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    room_id: int | None = None
    start_time: DT
    end_time: DT
    capacity: int | None = Field(default=None, gt=0)
    speaker_ids: list[int] = []

    @model_validator(mode="after")
    def _t(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    room_id: int | None = None
    start_time: DT | None = None
    end_time: DT | None = None
    capacity: int | None = Field(default=None, gt=0)
    speaker_ids: list[int] | None = None


class SpeakerIn(BaseModel):
    organization_id: int
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr | None = None
    bio: str | None = None


class SpeakerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    email: EmailStr | None = None
    bio: str | None = None


class SpeakerOut(ORM):
    id: int
    organization_id: int
    name: str
    email: str | None
    bio: str | None


class SessionOut(ORM):
    id: int
    event_id: int
    title: str
    description: str | None
    room_id: int | None
    room: ResourceOut | None = None
    start_time: datetime
    end_time: datetime
    capacity: int | None
    speakers: list[SpeakerOut] = []


# ---------------- Attendance ----------------
class AttendanceIn(BaseModel):
    user_id: int
    status: AttendanceStatus = AttendanceStatus.ATTENDED


class AttendanceUpdate(BaseModel):
    status: AttendanceStatus


class AttendanceOut(ORM):
    id: int
    event_id: int
    user_id: int
    user: UserBrief
    registration_id: int | None
    status: str
    checked_in_at: datetime | None


# ---------------- Files / comments / notifications ----------------
class AttachmentOut(ORM):
    id: int
    event_id: int
    entity_type: str
    entity_id: int | None
    file_name: str
    mime_type: str
    file_size: int
    uploaded_by: int
    created_at: datetime


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(ORM):
    id: int
    event_id: int | None
    session_id: int | None
    user: UserBrief
    body: str
    created_at: datetime
    updated_at: datetime


class NotificationOut(ORM):
    id: int
    type: str
    title: str
    message: str
    data: dict | None
    is_read: bool
    created_at: datetime


class NotificationPage(Page[NotificationOut]):
    unread_count: int = 0


class AuditOut(ORM):
    id: int
    user_id: int | None
    organization_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    details: dict | None
    created_at: datetime
