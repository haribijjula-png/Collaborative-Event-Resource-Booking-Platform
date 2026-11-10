from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, E
from app.models import models as m
from app.models.enums import OrgRole
from app.repositories.repos import OrgRepo, UserRepo
from app.services.common import Access, audit, notify


class OrganizationService:
    def __init__(self, db: Session, user: m.User):
        self.db, self.user = db, user
        self.repo = OrgRepo(db)
        self.access = Access(db, user)

    def create(self, name, description):
        try:
            org = self.repo.add(m.Organization(name=name, description=description, created_by=self.user.id))
        except IntegrityError:
            self.db.rollback()
            raise Conflict("An organization with this name already exists.", code="ORGANIZATION_EXISTS")
        self.repo.add(m.OrganizationMember(organization_id=org.id, user_id=self.user.id, role=OrgRole.ORG_ADMIN.value))
        audit(self.db, self.user, org.id, "organization.created", "organization", org.id, {"name": name})
        self.db.commit()
        return org

    def list_mine(self):
        out = []
        for org, role in self.repo.for_user(self.user.id, self.user.is_super_admin):
            org.my_role = role
            out.append(org)
        return out

    def get(self, org_id):
        self.access.require(org_id)
        org = self.repo.get(org_id)
        org.my_role = self.access.role(org_id).value
        return org

    def update(self, org_id, data: dict):
        self.access.require(org_id, OrgRole.ORG_ADMIN)
        org = self.repo.get(org_id)
        for k, v in data.items():
            setattr(org, k, v)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise Conflict("An organization with this name already exists.", code="ORGANIZATION_EXISTS")
        audit(self.db, self.user, org_id, "organization.updated", "organization", org_id, data)
        self.db.commit()
        return org

    # ---- members ----
    def list_members(self, org_id, page, page_size, **filters):
        self.access.require(org_id, OrgRole.STAFF)
        return self.repo.members(org_id, page, page_size, **filters)

    def _member(self, org_id, member_id) -> m.OrganizationMember:
        mem = self.repo.member(member_id, org_id)
        if not mem:
            raise NotFound("Member not found.")
        return mem

    def add_member(self, org_id, email, role: OrgRole):
        self.access.require(org_id, OrgRole.ORG_ADMIN)
        user = UserRepo(self.db).by_email(email)
        if not user:
            raise NotFound("No registered user with that email.", code="USER_NOT_FOUND")
        if self.repo.membership(org_id, user.id):
            raise Conflict("User is already a member of this organization.", code="MEMBER_EXISTS")
        mem = self.repo.add(m.OrganizationMember(organization_id=org_id, user_id=user.id, role=role.value))
        audit(self.db, self.user, org_id, "member.added", "member", mem.id, {"user_id": user.id, "role": role.value})
        self.db.commit()
        return mem

    def _guard_last_admin(self, org_id, mem):
        if mem.role == OrgRole.ORG_ADMIN.value and mem.is_active and self.repo.count_active_admins(org_id) <= 1:
            raise E(409, "LAST_ADMIN", "An organization must keep at least one active administrator.")

    def remove_member(self, org_id, member_id):
        self.access.require(org_id, OrgRole.ORG_ADMIN)
        mem = self._member(org_id, member_id)
        self._guard_last_admin(org_id, mem)
        audit(self.db, self.user, org_id, "member.removed", "member", mem.id, {"user_id": mem.user_id})
        self.repo.delete(mem)
        self.db.commit()

    def change_role(self, org_id, member_id, role: OrgRole):
        self.access.require(org_id, OrgRole.ORG_ADMIN)
        mem = self._member(org_id, member_id)
        if role != OrgRole.ORG_ADMIN:
            self._guard_last_admin(org_id, mem)
        mem.role = role.value
        audit(self.db, self.user, org_id, "member.role_changed", "member", mem.id, {"role": role.value})
        self.db.commit()
        return mem

    def set_active(self, org_id, member_id, active: bool):
        self.access.require(org_id, OrgRole.ORG_ADMIN)
        mem = self._member(org_id, member_id)
        if not active:
            self._guard_last_admin(org_id, mem)
        mem.is_active = active
        audit(self.db, self.user, org_id, "member.activated" if active else "member.deactivated", "member", mem.id)
        self.db.commit()
        return mem
