"""WebSocket connection manager + after-commit push queue.

Services call `publish(db, user_ids, payload)`; messages are only delivered after the DB transaction commits,
so clients never see events for rolled-back work.
"""
import asyncio
import logging

from fastapi import WebSocket
from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("realtime")


class ConnectionManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, user_id: int, ws: WebSocket):
        self.loop = asyncio.get_running_loop()
        self.connections.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        self.connections.get(user_id, set()).discard(ws)

    async def _send(self, user_id: int, payload: dict):
        for ws in list(self.connections.get(user_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:  # connection died
                self.disconnect(user_id, ws)

    def push(self, user_id: int, payload: dict):
        """Thread-safe push (services run in worker threads)."""
        if self.loop and self.connections.get(user_id):
            asyncio.run_coroutine_threadsafe(self._send(user_id, payload), self.loop)


manager = ConnectionManager()


def publish(db: Session, user_ids, payload: dict) -> None:
    queue = db.info.setdefault("ws_queue", [])
    for uid in set(user_ids):
        queue.append((uid, payload))


@event.listens_for(Session, "after_commit")
def _flush_queue(session: Session):
    for uid, payload in session.info.pop("ws_queue", []):
        manager.push(uid, payload)


@event.listens_for(Session, "after_rollback")
def _drop_queue(session: Session):
    session.info.pop("ws_queue", None)
