import enum


class StrEnum(str, enum.Enum):
    def __str__(self):
        return self.value


class OrgRole(StrEnum):
    ORG_ADMIN = "org_admin"
    EVENT_MANAGER = "event_manager"
    STAFF = "staff"
    PARTICIPANT = "participant"


ROLE_RANK = {OrgRole.PARTICIPANT: 1, OrgRole.STAFF: 2, OrgRole.EVENT_MANAGER: 3, OrgRole.ORG_ADMIN: 4}


class EventStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


EVENT_TRANSITIONS = {
    EventStatus.DRAFT: {EventStatus.PUBLISHED, EventStatus.CANCELLED, EventStatus.ARCHIVED},
    EventStatus.PUBLISHED: {EventStatus.ONGOING, EventStatus.CANCELLED},
    EventStatus.ONGOING: {EventStatus.COMPLETED, EventStatus.CANCELLED},
    EventStatus.COMPLETED: {EventStatus.ARCHIVED},
    EventStatus.CANCELLED: {EventStatus.ARCHIVED},
    EventStatus.ARCHIVED: set(),
}


class RegistrationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ATTENDED = "attended"
    NO_SHOW = "no_show"


# statuses that occupy a seat
SEAT_STATUSES = (RegistrationStatus.CONFIRMED, RegistrationStatus.ATTENDED, RegistrationStatus.NO_SHOW)
# statuses that count as "registered" for duplicate detection
ACTIVE_REG_STATUSES = (RegistrationStatus.PENDING, RegistrationStatus.CONFIRMED, RegistrationStatus.WAITLISTED,
                       RegistrationStatus.ATTENDED, RegistrationStatus.NO_SHOW)


class ResourceStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ResourceType(StrEnum):
    MEETING_ROOM = "meeting_room"
    CONFERENCE_HALL = "conference_hall"
    PROJECTOR = "projector"
    CAMERA = "camera"
    VEHICLE = "vehicle"
    EQUIPMENT = "equipment"


class BookingStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


BLOCKING_BOOKING = (BookingStatus.REQUESTED, BookingStatus.APPROVED)


class AttendanceStatus(StrEnum):
    REGISTERED = "registered"
    ATTENDED = "attended"
    NO_SHOW = "no_show"


class NotificationType(StrEnum):
    EVENT_PUBLISHED = "event_published"
    REGISTRATION_CONFIRMED = "registration_confirmed"
    REGISTRATION_WAITLISTED = "registration_waitlisted"
    REGISTRATION_REJECTED = "registration_rejected"
    REGISTRATION_CANCELLED = "registration_cancelled"
    BOOKING_APPROVED = "booking_approved"
    BOOKING_REJECTED = "booking_rejected"
    EVENT_CANCELLED = "event_cancelled"
    SESSION_UPDATED = "session_updated"
    USER_MENTIONED = "user_mentioned"
    EVENT_STARTING_SOON = "event_starting_soon"
    NEW_REGISTRATION = "new_registration"


def values(enum_cls, *members):
    return [m.value for m in (members or enum_cls)]
