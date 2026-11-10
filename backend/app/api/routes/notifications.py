import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.api.deps import DB, CurrentUser, Pg, ok
from app.core.errors import AppError
from app.db.session import SessionLocal
from app.repositories.repos import NotificationRepo
from app.schemas.schemas import Envelope, Message, NotificationOut, NotificationPage
from app.services.auth import AuthService
from app.services.common import Access
from app.services.misc import DashboardService, NotificationService
from app.services.realtime import manager

router = APIRouter(tags=["Notifications & Dashboard"])


@router.get("/notifications", response_model=Envelope[NotificationPage])
def list_notifications(db: DB, user: CurrentUser, pg: Pg, is_read: bool | None = None):
    res = NotificationRepo(db).list(user.id, pg.page, pg.page_size, is_read)
    res["unread_count"] = NotificationRepo(db).unread_count(user.id)
    return {"success": True, "data": res}


@router.patch("/notifications/read-all", response_model=Envelope[Message])
def read_all(db: DB, user: CurrentUser):
    n = NotificationService(db, user).mark_all()
    return ok({"message": f"{n} notifications marked as read."})


@router.patch("/notifications/{nid}/read", response_model=Envelope[NotificationOut])
def read_one(nid: int, db: DB, user: CurrentUser):
    return ok(NotificationService(db, user).mark_read(nid))


@router.get("/dashboard")
def dashboard(db: DB, user: CurrentUser, organization_id: int = Query(...)):
    return ok(DashboardService(db, user).build(organization_id))


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    """Real-time channel. Connect with /api/ws?token=<access_token>. REST endpoints remain the source of truth."""
    def _auth():
        with SessionLocal() as db:
            return AuthService(db).authenticate_access(token).id
    try:
        user_id = await run_in_threadpool(_auth)
    except AppError:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    await manager.connect(user_id, websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, websocket)
