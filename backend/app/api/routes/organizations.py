from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser, Pg, ok
from app.models.enums import OrgRole
from app.repositories.repos import AuditRepo
from app.schemas.schemas import (AuditOut, Envelope, MemberAdd, MemberOut, MemberRoleIn, Message, OrgCreate, OrgOut, OrgUpdate,
                                 OrgWithRole, Page)
from app.services.common import Access
from app.services.organizations import OrganizationService

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.post("", response_model=Envelope[OrgOut], status_code=201)
def create_org(body: OrgCreate, db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).create(body.name, body.description))


@router.get("", response_model=Envelope[list[OrgWithRole]])
def my_orgs(db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).list_mine())


@router.get("/{org_id}", response_model=Envelope[OrgWithRole])
def get_org(org_id: int, db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).get(org_id))


@router.patch("/{org_id}", response_model=Envelope[OrgOut])
def update_org(org_id: int, body: OrgUpdate, db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).update(org_id, body.model_dump(exclude_unset=True)))


@router.get("/{org_id}/members", response_model=Envelope[Page[MemberOut]])
def list_members(org_id: int, db: DB, user: CurrentUser, pg: Pg, search: str | None = None,
                 role: OrgRole | None = None, is_active: bool | None = None):
    return ok(OrganizationService(db, user).list_members(org_id, pg.page, pg.page_size, search=search,
                                                         role=role.value if role else None, is_active=is_active))


@router.post("/{org_id}/members", response_model=Envelope[MemberOut], status_code=201)
def add_member(org_id: int, body: MemberAdd, db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).add_member(org_id, body.email, body.role))


@router.delete("/{org_id}/members/{member_id}", response_model=Envelope[Message])
def remove_member(org_id: int, member_id: int, db: DB, user: CurrentUser):
    OrganizationService(db, user).remove_member(org_id, member_id)
    return ok({"message": "Member removed."})


@router.patch("/{org_id}/members/{member_id}/role", response_model=Envelope[MemberOut])
def change_role(org_id: int, member_id: int, body: MemberRoleIn, db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).change_role(org_id, member_id, body.role))


@router.post("/{org_id}/members/{member_id}/activate", response_model=Envelope[MemberOut])
def activate_member(org_id: int, member_id: int, db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).set_active(org_id, member_id, True))


@router.post("/{org_id}/members/{member_id}/deactivate", response_model=Envelope[MemberOut])
def deactivate_member(org_id: int, member_id: int, db: DB, user: CurrentUser):
    return ok(OrganizationService(db, user).set_active(org_id, member_id, False))


@router.get("/{org_id}/audit-logs", response_model=Envelope[Page[AuditOut]])
def audit_logs(org_id: int, db: DB, user: CurrentUser, pg: Pg, action: str | None = None):
    Access(db, user).require(org_id, OrgRole.ORG_ADMIN)
    return ok(AuditRepo(db).list(org_id, pg.page, pg.page_size, action))
