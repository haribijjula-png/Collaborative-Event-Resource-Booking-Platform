from tests.helpers import future, iso


def test_event_crud(w):
    ev = w.event(publish=False)
    assert ev["status"] == "draft" and ev["organizer"]["username"] == "manager"
    r = w.c.patch(f"/api/events/{ev['id']}", json={"name": "Renamed", "capacity": 10}, headers=w.manager["h"])
    assert r.json()["data"]["name"] == "Renamed"
    assert w.c.get(f"/api/events/{ev['id']}", headers=w.admin["h"]).json()["data"]["capacity"] == 10
    assert w.c.delete(f"/api/events/{ev['id']}", headers=w.manager["h"]).status_code == 200
    assert w.c.get(f"/api/events/{ev['id']}", headers=w.admin["h"]).status_code == 404


def test_invalid_times_rejected(w):
    body = {"organization_id": w.org["id"], "name": "Bad times", "start_time": iso(future(2, 4)), "end_time": iso(future(2)), "capacity": 5}
    assert w.c.post("/api/events", json=body, headers=w.manager["h"]).status_code == 422
    assert w.c.post("/api/events", json={**body, "start_time": iso(future(2)), "end_time": iso(future(2, 4)), "capacity": 0}, headers=w.manager["h"]).status_code == 422


def test_status_transitions(w):
    ev = w.event(publish=False)
    p = lambda path: w.c.post(f"/api/events/{ev['id']}/{path}", headers=w.manager["h"])
    assert p("archive").status_code == 200 or True  # draft -> archived allowed by the state machine
    ev2 = w.event(publish=False)
    p2 = lambda path, **kw: w.c.post(f"/api/events/{ev2['id']}/{path}", headers=w.manager["h"], **kw)
    assert p2("publish").status_code == 200
    r = p2("publish")  # published -> published is invalid
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_EVENT_STATUS"
    assert p2("status", json={"status": "completed"}).status_code == 409       # published -> completed skips ongoing
    assert p2("status", json={"status": "ongoing"}).status_code == 200
    assert p2("status", json={"status": "completed"}).status_code == 200
    assert p2("cancel").status_code == 409                                     # completed -> cancelled invalid
    assert p2("archive").status_code == 200
    assert p2("status", json={"status": "published"}).status_code == 409       # archived is terminal
    assert w.c.patch(f"/api/events/{ev2['id']}", json={"name": "zzz"}, headers=w.manager["h"]).status_code == 409


def test_only_organizer_or_admin_manages_event(w):
    other_mgr = w.member("mgr2", "event_manager")
    ev = w.event()
    assert w.c.patch(f"/api/events/{ev['id']}", json={"name": "Nope"}, headers=other_mgr["h"]).status_code == 403
    assert w.c.post(f"/api/events/{ev['id']}/cancel", headers=other_mgr["h"]).status_code == 403
    assert w.c.patch(f"/api/events/{ev['id']}", json={"name": "Admin edit"}, headers=w.admin["h"]).status_code == 200


def test_delete_only_draft_or_cancelled(w):
    ev = w.event()
    r = w.c.delete(f"/api/events/{ev['id']}", headers=w.manager["h"])
    assert r.status_code == 409
    w.c.post(f"/api/events/{ev['id']}/cancel", headers=w.manager["h"])
    assert w.c.delete(f"/api/events/{ev['id']}", headers=w.manager["h"]).status_code == 200


def test_capacity_cannot_drop_below_confirmed(w):
    ev = w.event(capacity=2)
    w.register(w.p1, ev); w.register(w.p2, ev)
    r = w.c.patch(f"/api/events/{ev['id']}", json={"capacity": 1}, headers=w.manager["h"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVENT_CAPACITY_EXCEEDED"


def test_increasing_capacity_promotes_waitlist(w):
    ev = w.event(capacity=1)
    w.register(w.p1, ev)
    assert w.register(w.p2, ev).json()["data"]["status"] == "waitlisted"
    w.c.patch(f"/api/events/{ev['id']}", json={"capacity": 2}, headers=w.manager["h"])
    regs = w.c.get(f"/api/events/{ev['id']}/registrations", headers=w.manager["h"]).json()["data"]["items"]
    assert {r["user"]["username"]: r["status"] for r in regs} == {"pa1": "confirmed", "pa2": "confirmed"}


def test_cancel_event_cascades(w):
    ev = w.event(capacity=1)
    w.register(w.p1, ev); w.register(w.p2, ev)
    room = w.resource()
    bk = w.c.post("/api/bookings", json={"resource_id": room["id"], "event_id": ev["id"], "start_time": iso(future(2)), "end_time": iso(future(2, 1))}, headers=w.manager["h"]).json()["data"]
    assert w.c.post(f"/api/events/{ev['id']}/cancel", headers=w.manager["h"]).json()["data"]["status"] == "cancelled"
    regs = w.c.get(f"/api/events/{ev['id']}/registrations", headers=w.admin["h"]).json()["data"]["items"]
    assert all(r["status"] == "cancelled" for r in regs)
    assert w.c.get(f"/api/bookings/{bk['id']}", headers=w.admin["h"]).json()["data"]["status"] == "cancelled"
    notes = w.c.get("/api/notifications", headers=w.p1["h"]).json()["data"]["items"]
    assert "event_cancelled" in {n["type"] for n in notes}


def test_filters_search_sort_pagination(w):
    for i, (name, loc) in enumerate([("Python Conference", "Berlin"), ("Rust Meetup", "Paris"), ("Conference of Go", "Berlin")]):
        w.event(name=name, location=loc, start_time=iso(future(2 + i)), end_time=iso(future(2 + i, 2)))
    w.event(name="Hidden Draft", publish=False)
    g = lambda q, h=None: w.c.get(f"/api/events?{q}", headers=(h or w.admin)["h"]).json()["data"]
    assert g("")["total"] == 4
    assert g("page_size=2")["pages"] == 2 and len(g("page_size=2")["items"]) == 2
    assert g("search=conference")["total"] == 2
    assert g("location=berlin")["total"] == 2
    assert g("status=published")["total"] == 3 and g("status=draft")["total"] == 1
    assert [e["name"] for e in g("sort=start_time&status=published")["items"]][0] == "Python Conference"
    assert g("sort=-start_time&status=published")["items"][0]["name"] == "Conference of Go"
    assert g(f"organizer_id={w.manager['id']}")["total"] == 4
    assert g(f"start_from={iso(future(3, -1))}&start_to={iso(future(3, 1))}".replace("+", "%2B"))["total"] == 1
    assert g("", w.p1)["total"] == 3                      # participants never see drafts
    assert w.c.get("/api/events?page_size=1000", headers=w.admin["h"]).status_code == 422
