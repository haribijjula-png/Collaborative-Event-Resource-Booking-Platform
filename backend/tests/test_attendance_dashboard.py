def to_status(w, ev, status):
    return w.c.post(f"/api/events/{ev['id']}/status", json={"status": status}, headers=w.manager["h"])


def test_attendance_flow(w):
    ev = w.event(capacity=5)
    w.register(w.p1, ev); w.register(w.p2, ev)
    body = {"user_id": w.p1["id"], "status": "attended"}
    r = w.c.post(f"/api/events/{ev['id']}/attendance", json=body, headers=w.staff["h"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_EVENT_STATUS"       # event hasn't started
    to_status(w, ev, "ongoing")
    r = w.c.post(f"/api/events/{ev['id']}/attendance", json=body, headers=w.staff["h"])
    assert r.status_code == 201 and r.json()["data"]["status"] == "attended" and r.json()["data"]["checked_in_at"]
    items = w.c.get(f"/api/events/{ev['id']}/attendance", headers=w.staff["h"]).json()["data"]["items"]
    assert {i["user"]["username"]: i["status"] for i in items} == {"pa1": "attended", "pa2": "registered"}
    att2 = [i for i in items if i["user"]["username"] == "pa2"][0]
    assert w.c.patch(f"/api/attendance/{att2['id']}", json={"status": "no_show"}, headers=w.manager["h"]).json()["data"]["status"] == "no_show"
    regs = {r["user"]["username"]: r["status"] for r in w.c.get(f"/api/events/{ev['id']}/registrations", headers=w.admin["h"]).json()["data"]["items"]}
    assert regs == {"pa1": "attended", "pa2": "no_show"}                                         # registration status kept in sync
    csv = w.c.get(f"/api/events/{ev['id']}/attendance/export", headers=w.staff["h"])
    assert csv.status_code == 200 and "pa1@example.com" in csv.text


def test_attendance_authorization(w):
    ev = w.event(capacity=5)
    w.register(w.p1, ev); w.register(w.p2, ev)
    to_status(w, ev, "ongoing")
    body = {"user_id": w.p1["id"], "status": "attended"}
    assert w.c.post(f"/api/events/{ev['id']}/attendance", json=body, headers=w.p1["h"]).status_code == 403    # can't self check-in
    assert w.c.post(f"/api/events/{ev['id']}/attendance", json=body, headers=w.admin_b["h"]).status_code == 404
    aid = w.c.get(f"/api/events/{ev['id']}/attendance", headers=w.staff["h"]).json()["data"]["items"][0]["id"]
    assert w.c.patch(f"/api/attendance/{aid}", json={"status": "attended"}, headers=w.p1["h"]).status_code == 403
    assert w.c.patch(f"/api/attendance/{aid}", json={"status": "attended"}, headers=w.admin_b["h"]).status_code == 404
    assert w.c.get(f"/api/events/{ev['id']}/attendance/export", headers=w.p1["h"]).status_code == 403
    mine = w.c.get(f"/api/events/{ev['id']}/attendance", headers=w.p1["h"]).json()["data"]
    assert mine["total"] == 1 and mine["items"][0]["user"]["username"] == "pa1"                  # participants see only own


def test_attendance_requires_confirmed_registration(w):
    ev = w.event(capacity=1)
    w.register(w.p1, ev); w.register(w.p2, ev)           # p2 waitlisted
    to_status(w, ev, "ongoing")
    r = w.c.post(f"/api/events/{ev['id']}/attendance", json={"user_id": w.p2["id"], "status": "attended"}, headers=w.staff["h"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_REGISTERED"
    r = w.c.post(f"/api/events/{ev['id']}/attendance", json={"user_id": w.p3["id"], "status": "attended"}, headers=w.staff["h"])
    assert r.json()["error"]["code"] == "NOT_REGISTERED"


def test_dashboards_per_role(w):
    ev = w.event(capacity=1)
    w.register(w.p1, ev); w.register(w.p2, ev)
    w.resource()
    d = lambda u: w.c.get(f"/api/dashboard?organization_id={w.org['id']}", headers=u["h"]).json()["data"]
    a = d(w.admin)
    assert a["role"] == "org_admin" and a["cards"]["total_events"] == 1 and a["cards"]["published_events"] == 1
    assert a["cards"]["total_registrations"] == 2 and a["cards"]["active_resources"] == 1 and a["cards"]["total_members"] == 6
    assert a["charts"]["registrations_by_status"] == {"confirmed": 1, "waitlisted": 1}
    m = d(w.manager)
    assert m["role"] == "event_manager" and m["cards"]["my_events"] == 1 and m["cards"]["waitlisted_participants"] == 1
    s = d(w.staff)
    assert s["role"] == "staff" and "pending_registrations" in s["cards"] and "todays_sessions" in s["cards"]
    p = d(w.p1)
    assert p["role"] == "participant" and p["cards"]["registered_events"] == 1
    assert d(w.p2)["cards"]["waitlisted_events"] == 1
    assert w.c.get(f"/api/dashboard?organization_id={w.org['id']}", headers=w.admin_b["h"]).status_code == 403


def test_audit_log_admin_only(w):
    w.event()
    url = f"/api/organizations/{w.org['id']}/audit-logs"
    assert w.c.get(url, headers=w.manager["h"]).status_code == 403
    r = w.c.get(url, headers=w.admin["h"]).json()["data"]
    assert r["total"] > 0 and "event.created" in {i["action"] for i in r["items"]}
