import asyncio

import httpx

from tests.helpers import future, iso


def status_of(w, ev, user):
    r = w.register(user, ev)
    return r.status_code, (r.json()["data"]["status"] if r.status_code == 201 else r.json()["error"]["code"])


def test_register_confirmed_then_waitlisted(w):
    ev = w.event(capacity=2)
    assert status_of(w, ev, w.p1) == (201, "confirmed")
    assert status_of(w, ev, w.p2) == (201, "confirmed")
    assert status_of(w, ev, w.p3) == (201, "waitlisted")
    d = w.c.get(f"/api/events/{ev['id']}", headers=w.p1["h"]).json()["data"]
    assert d["confirmed_count"] == 2 and d["waitlist_count"] == 1 and d["my_registration_status"] == "confirmed"


def test_duplicate_registration_prevented(w):
    ev = w.event()
    assert status_of(w, ev, w.p1)[0] == 201
    assert status_of(w, ev, w.p1) == (409, "DUPLICATE_REGISTRATION")


def test_cannot_register_for_cancelled_draft_or_non_member(w):
    draft = w.event(publish=False)
    assert w.register(w.p1, draft).status_code == 404            # participants can't even see drafts
    ev = w.event()
    w.c.post(f"/api/events/{ev['id']}/cancel", headers=w.manager["h"])
    assert status_of(w, ev, w.p1) == (409, "EVENT_CANCELLED")
    ev2 = w.event()
    assert w.register(w.outsider, ev2).status_code == 404         # not a member of the org


def test_registration_closed_after_deadline(w):
    from app.db.session import SessionLocal
    from app.models.models import Event
    from datetime import datetime, timedelta, timezone
    ev = w.event()
    with SessionLocal() as db:
        db.query(Event).filter(Event.id == ev["id"]).update({"registration_deadline": datetime.now(timezone.utc) - timedelta(hours=1)})
        db.commit()
    assert status_of(w, ev, w.p1) == (409, "REGISTRATION_CLOSED")


def test_cancel_promotes_waitlist_in_fifo_order(w):
    ev = w.event(capacity=2)
    a = w.register(w.p1, ev).json()["data"]
    w.register(w.p2, ev)
    w.register(w.p3, ev)                                          # waitlisted
    extra = w.member("pa4", "participant"); w.register(extra, ev)  # waitlisted behind p3
    assert w.c.post(f"/api/registrations/{a['id']}/cancel", headers=w.p1["h"]).json()["data"]["status"] == "cancelled"
    regs = {r["user"]["username"]: r["status"] for r in w.c.get(f"/api/events/{ev['id']}/registrations", headers=w.admin["h"]).json()["data"]["items"]}
    assert regs["pa3"] == "confirmed" and regs["pa4"] == "waitlisted" and regs["pa1"] == "cancelled"
    notes = [n["type"] for n in w.c.get("/api/notifications", headers=w.p3["h"]).json()["data"]["items"]]
    assert "registration_waitlisted" in notes and "registration_confirmed" in notes


def test_cancelling_twice_and_cancelling_others(w):
    ev = w.event()
    r = w.register(w.p1, ev).json()["data"]
    assert w.c.post(f"/api/registrations/{r['id']}/cancel", headers=w.p2["h"]).status_code == 403
    assert w.c.post(f"/api/registrations/{r['id']}/cancel", headers=w.p1["h"]).status_code == 200
    assert w.c.post(f"/api/registrations/{r['id']}/cancel", headers=w.p1["h"]).json()["error"]["code"] == "INVALID_REGISTRATION_STATUS"
    assert status_of(w, ev, w.p1) == (201, "confirmed")           # can re-register after cancelling


def test_cancelled_registration_releases_capacity(w):
    ev = w.event(capacity=1)
    r = w.register(w.p1, ev).json()["data"]
    w.c.post(f"/api/registrations/{r['id']}/cancel", headers=w.p1["h"])
    assert status_of(w, ev, w.p2) == (201, "confirmed")


def test_approval_workflow(w):
    ev = w.event(capacity=1, requires_approval=True)
    r1 = w.register(w.p1, ev).json()["data"]; r2 = w.register(w.p2, ev).json()["data"]
    assert r1["status"] == r2["status"] == "pending"
    assert w.c.post(f"/api/registrations/{r1['id']}/approve", headers=w.p1["h"]).status_code == 403   # participants can't approve
    assert w.c.post(f"/api/registrations/{r1['id']}/approve", headers=w.staff["h"]).json()["data"]["status"] == "confirmed"
    assert w.c.post(f"/api/registrations/{r2['id']}/approve", headers=w.staff["h"]).json()["data"]["status"] == "waitlisted"  # full
    assert w.c.post(f"/api/registrations/{r1['id']}/approve", headers=w.staff["h"]).status_code == 409                       # not pending
    r3 = w.register(w.p3, ev).json()["data"]
    rej = w.c.post(f"/api/registrations/{r3['id']}/reject", json={"reason": "no"}, headers=w.manager["h"]).json()["data"]
    assert rej["status"] == "rejected"
    assert "registration_rejected" in [n["type"] for n in w.c.get("/api/notifications", headers=w.p3["h"]).json()["data"]["items"]]


def test_visibility_of_registrations(w):
    ev = w.event(capacity=5)
    r1 = w.register(w.p1, ev).json()["data"]; w.register(w.p2, ev)
    assert w.c.get(f"/api/registrations/{r1['id']}", headers=w.p2["h"]).status_code == 403
    assert w.c.get(f"/api/registrations/{r1['id']}", headers=w.staff["h"]).status_code == 200
    mine = w.c.get(f"/api/events/{ev['id']}/registrations", headers=w.p1["h"]).json()["data"]
    assert mine["total"] == 1                                       # participants see only their own
    assert w.c.get(f"/api/events/{ev['id']}/registrations", headers=w.staff["h"]).json()["data"]["total"] == 2
    g = lambda q: w.c.get(f"/api/registrations?{q}", headers=w.admin["h"]).json()["data"]["total"]
    assert g(f"event_id={ev['id']}") == 2 and g("status=waitlisted") == 0 and g(f"user_id={w.p1['id']}") == 1
    assert w.c.get("/api/registrations", headers=w.admin_b["h"]).json()["data"]["total"] == 0


def test_concurrent_registrations_never_exceed_capacity(w):
    """20 simultaneous requests for 3 seats: exactly 3 confirmed, 17 waitlisted, zero errors."""
    from app.main import app
    ev = w.event(capacity=3)
    users = [w.member(f"cc{i}", "participant") for i in range(20)]

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
            return await asyncio.gather(*[ac.post(f"/api/events/{ev['id']}/register", headers=u["h"]) for u in users])
    results = asyncio.run(run())
    assert all(r.status_code == 201 for r in results), [r.text for r in results if r.status_code != 201]
    statuses = [r.json()["data"]["status"] for r in results]
    assert statuses.count("confirmed") == 3 and statuses.count("waitlisted") == 17


def test_concurrent_duplicate_registration_creates_one(w):
    from app.main import app
    ev = w.event(capacity=10)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
            return await asyncio.gather(*[ac.post(f"/api/events/{ev['id']}/register", headers=w.p1["h"]) for _ in range(8)])
    codes = sorted(r.status_code for r in asyncio.run(run()))
    assert codes == [201] + [409] * 7


def test_concurrent_cancel_promotes_exactly_one(w):
    from app.main import app
    ev = w.event(capacity=1)
    r1 = w.register(w.p1, ev).json()["data"]
    w.register(w.p2, ev); w.register(w.p3, ev)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
            return await asyncio.gather(*[ac.post(f"/api/registrations/{r1['id']}/cancel", headers=w.p1["h"]) for _ in range(4)])
    codes = sorted(r.status_code for r in asyncio.run(run()))
    assert codes == [200, 409, 409, 409]
    regs = {r["user"]["username"]: r["status"] for r in w.c.get(f"/api/events/{ev['id']}/registrations", headers=w.admin["h"]).json()["data"]["items"]}
    assert sorted(regs.values()) == ["cancelled", "confirmed", "waitlisted"] and regs["pa2"] == "confirmed"
