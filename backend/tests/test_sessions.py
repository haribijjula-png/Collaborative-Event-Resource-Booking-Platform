from tests.helpers import future, iso


def mk_session(w, ev, start_h, end_h, user=None, **kw):
    body = {"title": "Keynote", "start_time": iso(future(2, start_h)), "end_time": iso(future(2, end_h)), **kw}
    return w.c.post(f"/api/events/{ev['id']}/sessions", json=body, headers=(user or w.manager)["h"])


def speaker(w, name="Dr Who"):
    return w.c.post("/api/speakers", json={"organization_id": w.org["id"], "name": name, "email": "s@example.com"}, headers=w.manager["h"]).json()["data"]


def test_session_create_list_update_delete(w):
    ev = w.event()
    room = w.resource(capacity=100)
    sp = speaker(w)
    r = mk_session(w, ev, 0, 1, room_id=room["id"], capacity=50, speaker_ids=[sp["id"]])
    assert r.status_code == 201
    s = r.json()["data"]
    assert s["speakers"][0]["name"] == "Dr Who" and s["room"]["name"] == "Room A"
    assert len(w.c.get(f"/api/events/{ev['id']}/sessions", headers=w.p1["h"]).json()["data"]) == 1
    u = w.c.patch(f"/api/sessions/{s['id']}", json={"title": "Opening Keynote", "end_time": iso(future(2, 2))}, headers=w.manager["h"])
    assert u.json()["data"]["title"] == "Opening Keynote"
    assert w.c.delete(f"/api/sessions/{s['id']}", headers=w.manager["h"]).status_code == 200
    assert w.c.get(f"/api/sessions/{s['id']}", headers=w.manager["h"]).status_code == 404


def test_session_must_be_inside_event(w):
    ev = w.event()   # runs +2d .. +2d4h
    for s, e in [(-1, 1), (3, 6), (-2, -1)]:
        r = mk_session(w, ev, s, e)
        assert r.status_code == 400 and r.json()["error"]["code"] == "SESSION_OUTSIDE_EVENT", (s, e)
    assert mk_session(w, ev, 0, 4).status_code == 201     # exactly the event window is fine
    assert mk_session(w, ev, 2, 1).status_code == 422     # end before start


def test_room_conflict_detected(w):
    ev = w.event(); room = w.resource()
    assert mk_session(w, ev, 0, 2, room_id=room["id"]).status_code == 201
    r = mk_session(w, ev, 1, 3, room_id=room["id"], title="Clash")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_TIME_CONFLICT"
    assert mk_session(w, ev, 2, 3, room_id=room["id"]).status_code == 201           # adjacent ok
    other = w.resource("Room B")
    assert mk_session(w, ev, 0, 2, room_id=other["id"]).status_code == 201          # another room ok
    # a different event in the same org also can't use the occupied room
    ev2 = w.event(name="Second Event")
    assert mk_session(w, ev2, 1, 2, room_id=room["id"]).json()["error"]["code"] == "SESSION_TIME_CONFLICT"


def test_room_booked_by_someone_else_blocks_session(w):
    ev = w.event(); room = w.resource()
    w.c.post("/api/bookings", json={"resource_id": room["id"], "start_time": iso(future(2, 0)), "end_time": iso(future(2, 2))}, headers=w.staff["h"])
    assert mk_session(w, ev, 1, 2, room_id=room["id"]).json()["error"]["code"] == "RESOURCE_ALREADY_BOOKED"


def test_session_capacity_cannot_exceed_room_capacity(w):
    ev = w.event(); room = w.resource(capacity=30)
    r = mk_session(w, ev, 0, 1, room_id=room["id"], capacity=31)
    assert r.status_code == 400 and r.json()["error"]["code"] == "SESSION_CAPACITY_EXCEEDS_ROOM"
    assert mk_session(w, ev, 0, 1, room_id=room["id"], capacity=30).status_code == 201


def test_speaker_conflict_detected(w):
    ev = w.event(); sp = speaker(w); other = speaker(w, "Ada L")
    assert mk_session(w, ev, 0, 2, speaker_ids=[sp["id"]]).status_code == 201
    r = mk_session(w, ev, 1, 3, speaker_ids=[sp["id"]], title="Overlap")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SPEAKER_TIME_CONFLICT"
    assert mk_session(w, ev, 1, 3, speaker_ids=[other["id"]]).status_code == 201
    assert mk_session(w, ev, 2, 3, speaker_ids=[sp["id"]]).status_code == 201


def test_cancelled_event_rejects_sessions(w):
    ev = w.event()
    w.c.post(f"/api/events/{ev['id']}/cancel", headers=w.manager["h"])
    r = mk_session(w, ev, 0, 1)
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVENT_CANCELLED"


def test_session_update_conflict_and_notification(w):
    ev = w.event(capacity=5); w.register(w.p1, ev)
    room = w.resource()
    a = mk_session(w, ev, 0, 1, room_id=room["id"]).json()["data"]
    mk_session(w, ev, 2, 3, room_id=room["id"])
    assert w.c.patch(f"/api/sessions/{a['id']}", json={"end_time": iso(future(2, 3))}, headers=w.manager["h"]).json()["error"]["code"] == "SESSION_TIME_CONFLICT"
    w.c.patch(f"/api/sessions/{a['id']}", json={"title": "Renamed"}, headers=w.manager["h"])
    assert "session_updated" in [n["type"] for n in w.c.get("/api/notifications", headers=w.p1["h"]).json()["data"]["items"]]


def test_session_permissions_and_isolation(w):
    ev = w.event()
    assert mk_session(w, ev, 0, 1, user=w.staff).status_code == 403
    assert mk_session(w, ev, 0, 1, user=w.p1).status_code == 403
    assert mk_session(w, ev, 0, 1, user=w.admin_b).status_code == 404
    sp_b = w.c.post("/api/speakers", json={"organization_id": w.org_b["id"], "name": "Foreign"}, headers=w.admin_b["h"]).json()["data"]
    assert mk_session(w, ev, 0, 1, speaker_ids=[sp_b["id"]]).status_code == 404   # speaker from another org


def test_speaker_crud(w):
    sp = speaker(w)
    assert w.c.patch(f"/api/speakers/{sp['id']}", json={"bio": "Hi"}, headers=w.manager["h"]).json()["data"]["bio"] == "Hi"
    assert w.c.get("/api/speakers?search=who", headers=w.p1["h"]).json()["data"]["total"] == 1
    assert w.c.get(f"/api/speakers/{sp['id']}", headers=w.admin_b["h"]).status_code == 404
    assert w.c.delete(f"/api/speakers/{sp['id']}", headers=w.p1["h"]).status_code == 403
    assert w.c.delete(f"/api/speakers/{sp['id']}", headers=w.manager["h"]).status_code == 200
