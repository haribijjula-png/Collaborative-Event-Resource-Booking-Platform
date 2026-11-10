from tests.helpers import future, iso


def notes(w, user, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return w.c.get(f"/api/notifications?{qs}", headers=user["h"]).json()["data"]


def test_publish_notifies_members_and_mark_read(w):
    w.event()
    n = notes(w, w.p1)
    assert n["unread_count"] == 1 and n["items"][0]["type"] == "event_published" and n["items"][0]["is_read"] is False
    assert notes(w, w.outsider)["total"] == 0 and notes(w, w.admin_b)["total"] == 0     # other orgs not notified
    nid = n["items"][0]["id"]
    assert w.c.patch(f"/api/notifications/{nid}/read", headers=w.p1["h"]).json()["data"]["is_read"] is True
    assert notes(w, w.p1)["unread_count"] == 0
    assert notes(w, w.p1, is_read="false")["total"] == 0


def test_cannot_read_someone_elses_notification(w):
    w.event()
    nid = notes(w, w.p1)["items"][0]["id"]
    assert w.c.patch(f"/api/notifications/{nid}/read", headers=w.p2["h"]).status_code == 404
    assert notes(w, w.p1)["unread_count"] == 1


def test_read_all(w):
    w.event(); w.event(name="Second")
    assert notes(w, w.p1)["unread_count"] == 2
    r = w.c.patch("/api/notifications/read-all", headers=w.p1["h"])
    assert r.status_code == 200
    assert notes(w, w.p1)["unread_count"] == 0 and notes(w, w.p2)["unread_count"] == 2


def test_mention_creates_notification(w):
    ev = w.event()
    r = w.c.post(f"/api/events/{ev['id']}/comments", json={"body": "Hey @pa2 and @staff please review. @ghost nobody, @outsider not a member"}, headers=w.p1["h"])
    assert r.status_code == 201
    mentioned = lambda u: [n for n in notes(w, u)["items"] if n["type"] == "user_mentioned"]
    assert len(mentioned(w.p2)) == 1 and len(mentioned(w.staff)) == 1
    assert mentioned(w.outsider) == [] and mentioned(w.p1) == []         # non-members / author not notified


def test_edit_comment_only_notifies_new_mentions(w):
    ev = w.event()
    c = w.c.post(f"/api/events/{ev['id']}/comments", json={"body": "hi @pa2"}, headers=w.p1["h"]).json()["data"]
    w.c.patch(f"/api/comments/{c['id']}", json={"body": "hi @pa2 and @pa3"}, headers=w.p1["h"])
    count = lambda u: len([n for n in notes(w, u)["items"] if n["type"] == "user_mentioned"])
    assert count(w.p2) == 1 and count(w.p3) == 1


def test_comment_permissions(w):
    ev = w.event()
    c = w.c.post(f"/api/events/{ev['id']}/comments", json={"body": "mine"}, headers=w.p1["h"]).json()["data"]
    assert w.c.patch(f"/api/comments/{c['id']}", json={"body": "hacked"}, headers=w.p2["h"]).status_code == 403
    assert w.c.delete(f"/api/comments/{c['id']}", headers=w.admin["h"]).status_code == 403     # own comments only
    assert w.c.post(f"/api/events/{ev['id']}/comments", json={"body": "x"}, headers=w.admin_b["h"]).status_code == 404
    assert w.c.post(f"/api/events/{ev['id']}/comments", json={"body": ""}, headers=w.p1["h"]).status_code == 422
    assert w.c.get(f"/api/events/{ev['id']}/comments", headers=w.p2["h"]).json()["data"]["total"] == 1
    assert w.c.delete(f"/api/comments/{c['id']}", headers=w.p1["h"]).status_code == 200


def test_session_comments(w):
    ev = w.event()
    s = w.c.post(f"/api/events/{ev['id']}/sessions", json={"title": "Talk", "start_time": iso(future(2)), "end_time": iso(future(2, 1))}, headers=w.manager["h"]).json()["data"]
    assert w.c.post(f"/api/sessions/{s['id']}/comments", json={"body": "great"}, headers=w.p1["h"]).status_code == 201
    assert w.c.get(f"/api/sessions/{s['id']}/comments", headers=w.p2["h"]).json()["data"]["total"] == 1
    assert w.c.get(f"/api/sessions/{s['id']}/comments", headers=w.admin_b["h"]).status_code == 404


def test_reminder_generation_and_websocket_push(w):
    from app.db.session import SessionLocal
    from app.models.models import Event
    from app.services.misc import generate_event_reminders
    from datetime import datetime, timedelta, timezone
    ev = w.event(); w.register(w.p1, ev)
    with SessionLocal() as db:
        db.query(Event).filter(Event.id == ev["id"]).update({"start_time": datetime.now(timezone.utc) + timedelta(minutes=30)})
        db.commit()
    with SessionLocal() as db:
        assert generate_event_reminders(db) == 1
    with SessionLocal() as db:
        assert generate_event_reminders(db) == 0              # idempotent
    assert "event_starting_soon" in [n["type"] for n in notes(w, w.p1)["items"]]


def test_websocket_receives_realtime_notification(w):
    token = w.p1["tokens"]["access_token"]
    with w.c.websocket_connect(f"/api/ws?token={token}") as ws:
        ws.send_text("ping"); assert ws.receive_text() == "pong"
        w.event()                                              # publishing notifies every member
        msg = ws.receive_json()
        assert msg["type"] in ("notification", "event.status_changed")
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with w.c.websocket_connect("/api/ws?token=bad"):
            pass
