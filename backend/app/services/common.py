import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import E, Forbidden, NotFound
from app.models import models as m
from app.models.enums import ROLE_RANK, OrgRole
from app.repositories.repos import AuditRepo, NotificationRepo, OrgRepo
from app.services import realtime

log = logging.getLogger("app.notify")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def org_denied() -> Forbidden:
    return E(403, "ORGANIZATION_ACCESS_DENIED", "You do not have access to this organization.")  # type: ignore[return-value]


def forbidden(msg="You do not have permission to perform this action.") -> Forbidden:
    return E(403, "FORBIDDEN", msg)  # type: ignore[return-value]


class Access:
    """Organization-level authorization. The single source of truth for 'who may do what in which org'."""

    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.orgs = OrgRepo(db)
        self._cache: dict[int, OrgRole | None] = {}

    def role(self, org_id: int) -> OrgRole | None:
        if self.user.is_super_admin:
            return OrgRole.ORG_ADMIN
        if org_id not in self._cache:
            mem = self.orgs.membership(org_id, self.user.id)
            self._cache[org_id] = OrgRole(mem.role) if mem and mem.is_active else None
        return self._cache[org_id]

    def require(self, org_id: int, min_role: OrgRole = OrgRole.PARTICIPANT) -> OrgRole:
        org = self.orgs.get(org_id)
        if not org:
            raise NotFound("Organization not found.")
        role = self.role(org_id)
        if role is None:
            raise org_denied()
        if ROLE_RANK[role] < ROLE_RANK[min_role]:
            raise forbidden(f"This action requires the '{min_role.value}' role or higher.")
        return role

    def has(self, org_id: int, min_role: OrgRole) -> bool:
        r = self.role(org_id)
        return r is not None and ROLE_RANK[r] >= ROLE_RANK[min_role]

    def org_ids(self) -> list[int]:
        return [o.id for o, _ in self.orgs.for_user(self.user.id, self.user.is_super_admin)]

    def privileged_org_ids(self) -> set[int]:
        return {o.id for o, r in self.orgs.for_user(self.user.id, self.user.is_super_admin) if r == "super_admin" or ROLE_RANK[OrgRole(r)] >= ROLE_RANK[OrgRole.STAFF]}


def audit(db: Session, user: m.User | None, org_id: int | None, action: str, entity_type: str, entity_id: int | None, details: dict | None = None):
    AuditRepo(db).add(m.AuditLog(user_id=user.id if user else None, organization_id=org_id, action=action,
                                 entity_type=entity_type, entity_id=entity_id, details=details))


def notify(db: Session, user_ids, ntype: str, title: str, message: str, data: dict | None = None):
    """Persist notifications and queue a websocket push (sent after commit). Also 'emails' via log (stub)."""
    repo = NotificationRepo(db)
    for uid in dict.fromkeys(user_ids):
        n = repo.add(m.Notification(user_id=uid, type=str(ntype), title=title, message=message, data=data))
        realtime.publish(db, [uid], {"type": "notification", "notification": {
            "id": n.id, "type": n.type, "title": title, "message": message, "data": data, "is_read": False}})
        log.info("EMAIL(stub) to user=%s subject=%s", uid, title)


def broadcast(db: Session, user_ids, kind: str, data: dict):
    realtime.publish(db, user_ids, {"type": kind, "data": data})
