from tests.helpers import future, iso


def test_unauthenticated_access_blocked(client):
    for path in ("/api/events", "/api/organizations", "/api/resources", "/api/bookings", "/api/notifications"):
        assert client.get(path).status_code == 401


def test_organization_isolation_events(w):
    ev = w.event()
    # Admin of another org cannot read, update, cancel or register: 404 (existence not leaked)
    for call in (lambda: w.c.get(f"/api/events/{ev['id']}", headers=w.admin_b["h"]),
                 lambda: w.c.patch(f"/api/events/{ev['id']}", json={"name": "Hacked"}, headers=w.admin_b["h"]),
                 lambda: w.c.post(f"/api/events/{ev['id']}/cancel", headers=w.admin_b["h"]),
                 lambda: w.register(w.admin_b, ev)):
        assert call().status_code == 404
    # and the other org's event list doesn't leak ours
    r = w.c.get("/api/events", headers=w.admin_b["h"])
    assert r.json()["data"]["total"] == 0
    # non-member can't use organization endpoints either
    assert w.c.get(f"/api/organizations/{w.org['id']}", headers=w.outsider["h"]).json()["error"]["code"] == "ORGANIZATION_ACCESS_DENIED"
    assert w.c.get(f"/api/organizations/{w.org['id']}/members", headers=w.admin_b["h"]).status_code == 403


def test_cannot_create_event_in_foreign_org(w):
    r = w.c.post("/api/events", json={"organization_id": w.org["id"], "name": "x y", "start_time": iso(future(2)), "end_time": iso(future(2, 2)), "capacity": 5}, headers=w.admin_b["h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "ORGANIZATION_ACCESS_DENIED"


def test_role_permissions_matrix(w):
    body = {"organization_id": w.org["id"], "name": "Role Test", "start_time": iso(future(3)), "end_time": iso(future(3, 2)), "capacity": 5}
    assert w.c.post("/api/events", json=body, headers=w.p1["h"]).status_code == 403          # participant
    assert w.c.post("/api/events", json=body, headers=w.staff["h"]).status_code == 403        # staff
    assert w.c.post("/api/events", json=body, headers=w.manager["h"]).status_code == 201      # manager
    assert w.c.post("/api/events", json=body, headers=w.admin["h"]).status_code == 201        # admin
    res = {"organization_id": w.org["id"], "name": "Van", "type": "vehicle"}
    assert w.c.post("/api/resources", json=res, headers=w.manager["h"]).status_code == 403    # only admins define resources
    assert w.c.post("/api/resources", json=res, headers=w.admin["h"]).status_code == 201


def test_only_admin_manages_members(w):
    url = f"/api/organizations/{w.org['id']}/members"
    assert w.c.post(url, json={"email": w.outsider["email"], "role": "staff"}, headers=w.manager["h"]).status_code == 403
    assert w.c.post(url, json={"email": w.outsider["email"], "role": "staff"}, headers=w.admin["h"]).status_code == 201
    assert w.c.patch(f"{url}/{w.p1['member_id']}/role", json={"role": "staff"}, headers=w.staff["h"]).status_code == 403
    assert w.c.get(url, headers=w.p1["h"]).status_code == 403  # participants can't list members


def test_member_lifecycle_and_last_admin_guard(w):
    url = f"/api/organizations/{w.org['id']}/members"
    r = w.c.patch(f"{url}/{w.p1['member_id']}/role", json={"role": "staff"}, headers=w.admin["h"])
    assert r.json()["data"]["role"] == "staff"
    assert w.c.post(f"{url}/{w.p1['member_id']}/deactivate", headers=w.admin["h"]).json()["data"]["is_active"] is False
    # deactivated member loses organization access
    assert w.c.get(f"/api/organizations/{w.org['id']}", headers=w.p1["h"]).status_code == 403
    assert w.c.post(f"{url}/{w.p1['member_id']}/activate", headers=w.admin["h"]).json()["data"]["is_active"] is True
    assert w.c.delete(f"{url}/{w.p2['member_id']}", headers=w.admin["h"]).status_code == 200
    admin_member = [m for m in w.c.get(url, headers=w.admin["h"]).json()["data"]["items"] if m["role"] == "org_admin"][0]
    r = w.c.delete(f"{url}/{admin_member['id']}", headers=w.admin["h"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_ADMIN"
    assert w.c.post(f"{url}/{w.p3['member_id']}/role", headers=w.admin["h"]).status_code in (404, 405)


def test_resource_level_authorization_on_bookings(w):
    room = w.resource()
    b = {"resource_id": room["id"], "start_time": iso(future(2)), "end_time": iso(future(2, 1)), "purpose": "x"}
    booking = w.c.post("/api/bookings", json=b, headers=w.staff["h"]).json()["data"]
    # participant can't book; other org can't see or touch it
    assert w.c.post("/api/bookings", json=b, headers=w.p1["h"]).status_code == 403
    assert w.c.post("/api/bookings", json=b, headers=w.admin_b["h"]).status_code == 404
    assert w.c.get(f"/api/bookings/{booking['id']}", headers=w.admin_b["h"]).status_code == 404
    assert w.c.post(f"/api/bookings/{booking['id']}/cancel", headers=w.admin_b["h"]).status_code == 404
    # staff can't approve their own booking; manager can
    assert w.c.post(f"/api/bookings/{booking['id']}/approve", headers=w.staff["h"]).status_code == 403
    assert w.c.post(f"/api/bookings/{booking['id']}/approve", headers=w.manager["h"]).status_code == 200
    assert w.c.get("/api/resources", headers=w.admin_b["h"]).json()["data"]["total"] == 0


def test_validation_error_envelope(w):
    r = w.c.post("/api/events", json={"organization_id": w.org["id"]}, headers=w.manager["h"])
    body = r.json()
    assert r.status_code == 422 and body["success"] is False and body["error"]["details"]
    assert w.c.get("/api/events/999999", headers=w.admin["h"]).json()["error"]["code"] == "EVENT_NOT_FOUND"
