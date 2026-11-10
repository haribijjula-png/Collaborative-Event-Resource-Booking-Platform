from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser, Pg, ok
from app.models.enums import BookingStatus, ResourceStatus, ResourceType
from app.schemas.schemas import (BookingCreate, BookingOut, BookingUpdate, Envelope, Message, Page, ResourceCreate, ResourceOut,
                                 ResourceUpdate, SpeakerIn, SpeakerOut, SpeakerUpdate)
from app.services.resources import BookingService, ResourceService
from app.services.sessions import SpeakerService

router = APIRouter(tags=["Resources & Bookings"])


@router.post("/resources", response_model=Envelope[ResourceOut], status_code=201)
def create_resource(body: ResourceCreate, db: DB, user: CurrentUser):
    return ok(ResourceService(db, user).create(body.model_dump()))


@router.get("/resources", response_model=Envelope[Page[ResourceOut]])
def list_resources(db: DB, user: CurrentUser, pg: Pg, organization_id: int | None = None, type: ResourceType | None = None,
                   status: ResourceStatus | None = None, search: str | None = None, sort: str | None = None):
    return ok(ResourceService(db, user).list(pg.page, pg.page_size, organization_id=organization_id, type=type.value if type else None,
                                             status=status.value if status else None, search=search, sort=sort))


@router.get("/resources/{rid}", response_model=Envelope[ResourceOut])
def get_resource(rid: int, db: DB, user: CurrentUser):
    return ok(ResourceService(db, user).get(rid))


@router.patch("/resources/{rid}", response_model=Envelope[ResourceOut])
def update_resource(rid: int, body: ResourceUpdate, db: DB, user: CurrentUser):
    return ok(ResourceService(db, user).update(rid, body.model_dump(exclude_unset=True)))


@router.post("/resources/{rid}/activate", response_model=Envelope[ResourceOut])
def activate_resource(rid: int, db: DB, user: CurrentUser):
    return ok(ResourceService(db, user).set_status(rid, True))


@router.post("/resources/{rid}/deactivate", response_model=Envelope[ResourceOut])
def deactivate_resource(rid: int, db: DB, user: CurrentUser):
    return ok(ResourceService(db, user).set_status(rid, False))


# ---------------- bookings ----------------
@router.post("/bookings", response_model=Envelope[BookingOut], status_code=201)
def create_booking(body: BookingCreate, db: DB, user: CurrentUser):
    return ok(BookingService(db, user).create(body.model_dump()))


@router.get("/bookings", response_model=Envelope[Page[BookingOut]])
def list_bookings(db: DB, user: CurrentUser, pg: Pg, resource_id: int | None = None, status: BookingStatus | None = None,
                  date_from: datetime | None = None, date_to: datetime | None = None, requested_by: int | None = None,
                  event_id: int | None = None, organization_id: int | None = None, sort: str | None = Query(None)):
    return ok(BookingService(db, user).list(pg.page, pg.page_size, resource_id=resource_id, status=status.value if status else None,
                                            date_from=date_from, date_to=date_to, requested_by=requested_by, event_id=event_id,
                                            organization_id=organization_id, sort=sort))


@router.get("/bookings/{bid}", response_model=Envelope[BookingOut])
def get_booking(bid: int, db: DB, user: CurrentUser):
    return ok(BookingService(db, user).get(bid))


@router.patch("/bookings/{bid}", response_model=Envelope[BookingOut])
def update_booking(bid: int, body: BookingUpdate, db: DB, user: CurrentUser):
    return ok(BookingService(db, user).update(bid, body.model_dump(exclude_unset=True)))


@router.post("/bookings/{bid}/approve", response_model=Envelope[BookingOut])
def approve_booking(bid: int, db: DB, user: CurrentUser):
    return ok(BookingService(db, user).decide(bid, True))


@router.post("/bookings/{bid}/reject", response_model=Envelope[BookingOut])
def reject_booking(bid: int, db: DB, user: CurrentUser):
    return ok(BookingService(db, user).decide(bid, False))


@router.post("/bookings/{bid}/cancel", response_model=Envelope[BookingOut])
def cancel_booking(bid: int, db: DB, user: CurrentUser):
    return ok(BookingService(db, user).cancel(bid))


# ---------------- speakers ----------------
@router.post("/speakers", response_model=Envelope[SpeakerOut], status_code=201)
def create_speaker(body: SpeakerIn, db: DB, user: CurrentUser):
    return ok(SpeakerService(db, user).create(body.model_dump()))


@router.get("/speakers", response_model=Envelope[Page[SpeakerOut]])
def list_speakers(db: DB, user: CurrentUser, pg: Pg, organization_id: int | None = None, search: str | None = None):
    return ok(SpeakerService(db, user).list(pg.page, pg.page_size, organization_id=organization_id, search=search))


@router.get("/speakers/{spid}", response_model=Envelope[SpeakerOut])
def get_speaker(spid: int, db: DB, user: CurrentUser):
    return ok(SpeakerService(db, user).get(spid))


@router.patch("/speakers/{spid}", response_model=Envelope[SpeakerOut])
def update_speaker(spid: int, body: SpeakerUpdate, db: DB, user: CurrentUser):
    return ok(SpeakerService(db, user).update(spid, body.model_dump(exclude_unset=True)))


@router.delete("/speakers/{spid}", response_model=Envelope[Message])
def delete_speaker(spid: int, db: DB, user: CurrentUser):
    SpeakerService(db, user).delete(spid)
    return ok({"message": "Speaker deleted."})
