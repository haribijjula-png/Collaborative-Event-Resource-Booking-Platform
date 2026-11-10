import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, events, notifications, organizations, resources
from app.core.config import settings
from app.core.errors import register_handlers
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scheduler")


def run_scheduled_jobs():
    """Lightweight in-process scheduler (swap for Celery beat in production)."""
    from app.services.events import EventService
    from app.services.misc import generate_event_reminders
    with SessionLocal() as db:
        EventService(db, None).auto_progress()  # type: ignore[arg-type]
    with SessionLocal() as db:
        generate_event_reminders(db)


async def _scheduler():
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, run_scheduled_jobs)
        except Exception:
            log.exception("scheduled job failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_scheduler()) if settings.ENABLE_SCHEDULER else None
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="Collaborative Event & Resource Booking Platform", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    register_handlers(app)
    api = APIRouter(prefix="/api")
    for r in (auth.router, organizations.router, events.router, resources.router, notifications.router):
        api.include_router(r)
    app.include_router(api)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
