"""Seed a super admin and (optionally) a demo organization.

    python -m app.scripts.seed            # super admin only
    python -m app.scripts.seed --demo     # + demo org, users, event, resources
"""
import sys
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import models as m


def get_or_create_user(db, email, username, name, password, **kw):
    u = db.query(m.User).filter(m.User.email == email).one_or_none()
    if not u:
        u = m.User(email=email, username=username, full_name=name, hashed_password=hash_password(password), **kw)
        db.add(u); db.flush()
    return u


def main(demo: bool):
    with SessionLocal() as db:
        get_or_create_user(db, settings.SUPERADMIN_EMAIL, settings.SUPERADMIN_USERNAME, "Super Admin", settings.SUPERADMIN_PASSWORD, is_super_admin=True)
        if demo and not db.query(m.Organization).filter(m.Organization.name == "Demo Org").first():
            pw = "Demo12345"
            people = {r: get_or_create_user(db, f"{r}@demo.test", f"demo_{r}", r.replace("_", " ").title(), pw) for r in ("org_admin", "event_manager", "staff", "participant")}
            org = m.Organization(name="Demo Org", description="Sample data", created_by=people["org_admin"].id)
            db.add(org); db.flush()
            for role, u in people.items():
                db.add(m.OrganizationMember(organization_id=org.id, user_id=u.id, role=role))
            start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=3, hours=1)
            db.add(m.Event(organization_id=org.id, organizer_id=people["event_manager"].id, name="Demo Conference", description="Welcome!",
                           location="Main Hall", start_time=start, end_time=start + timedelta(hours=6), capacity=2, status="published"))
            db.add(m.Resource(organization_id=org.id, name="Room A", type="meeting_room", capacity=40, location="Floor 1"))
            db.add(m.Resource(organization_id=org.id, name="Projector 1", type="projector"))
            print("Demo users (password Demo12345): " + ", ".join(f"{r}@demo.test" for r in people))
        db.commit()
    print(f"Super admin: {settings.SUPERADMIN_EMAIL}")


if __name__ == "__main__":
    main("--demo" in sys.argv)
