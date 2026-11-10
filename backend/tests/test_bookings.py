import asyncio

import httpx

from tests.helpers import future, iso


def book(w, room, start_h, end_h, user=None, **extra):
    user = user or w.manager
    return w.c.post("/api/bookings", json={"resource_id": room["id"], "start_time": iso(future(2, start_h)), "end_time": iso(future(2, end_h)), **extra}, headers=user["h"])


def test_booking_lifecycle(w):
    room = w.resource()
    r = book(w, room, 0, 1, purpose="Kickoff")
    assert r.status_code == 201 and r.json()["data"]["status"] == "requested" and r.json()["data"]["resource"]["name"] == "Room A"
    bid = r.json()["data"]["id"]
    assert w.c.post(f"/api/bookings/{bid}/approve", headers=w.admin["h"]).json()["data"]["status"] == "approved"
    assert w.c.post(f"/api/bookings/{bid}/approve", headers=w.admin["h"]).json()["error"]["code"] == "INVALID_BOOKING_STATUS"
    assert w.c.post(f"/api/bookings/{bid}/cancel", headers=w.manager["h"]).json()["data"]["status"] == "cancelled"
    assert w.c.post(f"/api/bookings/{bid}/cancel", headers=w.manager["h"]).status_code == 409
    assert "booking_approved" in [n["type"] for n in w.c.get("/api/notifications", headers=w.manager["h"]).json()["data"]["items"]]


def test_rejected_booking_notifies_and_frees_slot(w):
    room = w.resource()
    bid = book(w, room, 0, 1, user=w.staff).json()["data"]["id"]
    assert w.c.post(f"/api/bookings/{bid}/reject", headers=w.manager["h"]).json()["data"]["status"] == "rejected"
    assert "booking_rejected" in [n["type"] for n in w.c.get("/api/notifications", headers=w.staff["h"]).json()["data"]["items"]]
    assert book(w, room, 0, 1).status_code == 201     # slot is free again


def test_overlapping_booking_rejected(w):
    room = w.resource()
    assert book(w, room, 10, 11).status_code == 201
    r = book(w, room, 10, 12)                              # 10:00-11:00 exists, 10:30-style overlap
    assert r.status_code == 409 and r.json()["error"]["code"] == "RESOURCE_ALREADY_BOOKED"
    assert book(w, room, 9, 10).status_code == 201         # back-to-back is fine (half-open ranges)
    assert book(w, room, 11, 12).status_code == 201
    assert book(w, room, 9, 13).json()["error"]["code"] == "RESOURCE_ALREADY_BOOKED"  # fully encloses others
    other = w.resource("Room B")
    assert book(w, other, 10, 11).status_code == 201       # different resource, same time


def test_exact_half_hour_overlap_example(w):
    room = w.resource()
    base = future(2)
    mk = lambda s, e: w.c.post("/api/bookings", json={"resource_id": room["id"], "start_time": iso(base.replace(hour=10, minute=s[0]) ), "end_time": iso(base.replace(hour=e[0], minute=e[1]))}, headers=w.manager["h"])
    assert mk((0, 0), (11, 0)).status_code == 201          # 10:00 -> 11:00
    assert mk((30, 0), (11, 30)).status_code == 409        # 10:30 -> 11:30 rejected


def test_booking_validation(w):
    room = w.resource()
    assert book(w, room, 3, 1).status_code == 422                                   # end before start
    past = w.c.post("/api/bookings", json={"resource_id": room["id"], "start_time": iso(future(-1)), "end_time": iso(future(-1, 1))}, headers=w.manager["h"])
    assert past.json()["error"]["code"] == "BOOKING_IN_THE_PAST"
    w.c.post(f"/api/resources/{room['id']}/deactivate", headers=w.admin["h"])
    assert book(w, room, 0, 1).json()["error"]["code"] == "RESOURCE_INACTIVE"
    w.c.post(f"/api/resources/{room['id']}/activate", headers=w.admin["h"])
    assert book(w, room, 0, 1).status_code == 201
    assert book(w, {"id": 9999}, 0, 1).status_code == 404


def test_patch_booking_rechecks_overlap(w):
    room = w.resource()
    a = book(w, room, 0, 1).json()["data"]; book(w, room, 2, 3)
    r = w.c.patch(f"/api/bookings/{a['id']}", json={"end_time": iso(future(2, 2, ))}, headers=w.manager["h"])
    assert r.status_code == 200                                                    # now 0-2 touches 2-3 but doesn't overlap
    r = w.c.patch(f"/api/bookings/{a['id']}", json={"end_time": iso(future(2, 3))}, headers=w.manager["h"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "RESOURCE_ALREADY_BOOKED"
    assert w.c.patch(f"/api/bookings/{a['id']}", json={"purpose": "new"}, headers=w.staff["h"]).status_code == 403  # not the requester


def test_booking_filters(w):
    r1, r2 = w.resource("R1"), w.resource("R2")
    book(w, r1, 0, 1); book(w, r2, 0, 1, user=w.staff)
    bid = book(w, r1, 2, 3).json()["data"]["id"]
    w.c.post(f"/api/bookings/{bid}/approve", headers=w.admin["h"])
    g = lambda q: w.c.get(f"/api/bookings?{q}", headers=w.admin["h"]).json()["data"]["total"]
    assert g("") == 3 and g(f"resource_id={r1['id']}") == 2 and g("status=approved") == 1
    assert g(f"requested_by={w.staff['id']}") == 1
    assert g(f"date_from={iso(future(2, 1, )).replace('+', '%2B')}&date_to={iso(future(2, 3)).replace('+', '%2B')}") >= 1
    assert w.c.get("/api/bookings?page_size=2", headers=w.admin["h"]).json()["data"]["pages"] == 2


def test_concurrent_bookings_cannot_double_book(w):
    """15 simultaneous requests for the same slot: exactly one succeeds."""
    from app.main import app
    room = w.resource()
    body = {"resource_id": room["id"], "start_time": iso(future(2, 5)), "end_time": iso(future(2, 6))}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
            return await asyncio.gather(*[ac.post("/api/bookings", json=body, headers=w.manager["h"]) for _ in range(15)])
    results = asyncio.run(run())
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 14, codes
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {"RESOURCE_ALREADY_BOOKED"}
    assert w.c.get(f"/api/bookings?resource_id={room['id']}", headers=w.admin["h"]).json()["data"]["total"] == 1


def test_database_constraint_blocks_overlap_even_without_service_check(w):
    """Defence in depth: bypass the service layer and insert directly."""
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.db.session import SessionLocal
    from app.models.models import ResourceBooking
    room = w.resource()
    t0, t1 = future(2, 1), future(2, 3)
    with SessionLocal() as db:
        db.add(ResourceBooking(resource_id=room["id"], requested_by=w.manager["id"], start_time=t0, end_time=t1, status="approved")); db.commit()
        db.add(ResourceBooking(resource_id=room["id"], requested_by=w.manager["id"], start_time=future(2, 2), end_time=future(2, 4), status="requested"))
        with pytest.raises(IntegrityError):
            db.commit()
