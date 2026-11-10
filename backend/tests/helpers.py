from datetime import datetime, timedelta, timezone

PASSWORD = "Passw0rd!x"


def iso(dt: datetime) -> str:
    return dt.isoformat()


def future(days=2, hours=0):
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=days, hours=hours)


class World:
    def __init__(self, client):
        self.c = client
        self.admin = self.user("admin")
        self.org = self._ok(self.c.post("/api/organizations", json={"name": "Acme Org"}, headers=self.admin["h"]), 201)
        self.manager = self.member("manager", "event_manager")
        self.staff = self.member("staff", "staff")
        self.p1 = self.member("pa1", "participant")
        self.p2 = self.member("pa2", "participant")
        self.p3 = self.member("pa3", "participant")
        self.outsider = self.user("outsider")  # registered but in no org
        self.admin_b = self.user("adminb")
        self.org_b = self._ok(self.c.post("/api/organizations", json={"name": "Other Org"}, headers=self.admin_b["h"]), 201)

    @staticmethod
    def _ok(resp, code=200):
        assert resp.status_code == code, resp.text
        return resp.json()["data"]

    def user(self, name):
        r = self.c.post("/api/auth/register", json={"email": f"{name}@example.com", "username": name, "full_name": name.title(), "password": PASSWORD})
        assert r.status_code == 201, r.text
        data = self._ok(self.c.post("/api/auth/login", json={"email": f"{name}@example.com", "password": PASSWORD}))
        return {"id": data["user"]["id"], "email": f"{name}@example.com", "h": {"Authorization": f"Bearer {data['access_token']}"}, "tokens": data}

    def member(self, name, role):
        u = self.user(name)
        r = self.c.post(f"/api/organizations/{self.org['id']}/members", json={"email": u["email"], "role": role}, headers=self.admin["h"])
        u["member_id"] = self._ok(r, 201)["id"]
        return u

    def event(self, by=None, publish=True, **over):
        body = {"organization_id": self.org["id"], "name": "Tech Conf", "description": "d", "location": "Hall 1",
                "start_time": iso(future(2)), "end_time": iso(future(2, 4)), "capacity": 2, **over}
        by = by or self.manager
        ev = self._ok(self.c.post("/api/events", json=body, headers=by["h"]), 201)
        if publish:
            ev = self._ok(self.c.post(f"/api/events/{ev['id']}/publish", headers=by["h"]))
        return ev

    def resource(self, name="Room A", capacity=50, type="meeting_room"):
        return self._ok(self.c.post("/api/resources", json={"organization_id": self.org["id"], "name": name, "type": type, "capacity": capacity}, headers=self.admin["h"]), 201)

    def register(self, user, ev):
        return self.c.post(f"/api/events/{ev['id']}/register", headers=user["h"])
