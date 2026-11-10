# EventHub – Collaborative Event & Resource Booking Platform

React + FastAPI + PostgreSQL platform for organizations to run events, manage participants, rooms and resources, schedules, registrations/waitlists, approvals, documents, notifications and audit trails, with authorization enforced at **organization, role and resource/event level on the server**.

* **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL 16, PyJWT, bcrypt
* **Frontend:** React 18, React Router 6, Axios, Zustand, Vite (custom calendar, no UI framework)
* **Extras included:** WebSockets, Docker + Compose, CSV attendance export, dark mode, CI workflow, in-process scheduler, audit log

## Quick start

### Option A – Docker (one command)
```bash
docker compose up --build
# App: http://localhost:8080   API docs: http://localhost:8000/docs
# Super admin: admin@example.com / ChangeMe123!   (override via env, see .env.example)
```
The backend container runs `alembic upgrade head` and seeds the super admin on start.

### Option B – local
```bash
# 1. PostgreSQL (needs the btree_gist extension, which ships with postgresql-contrib)
createdb eventdb && createdb eventdb_test

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # adjust DATABASE_URL / SECRET_KEY
alembic upgrade head
python -m app.scripts.seed --demo # super admin + demo org (password Demo12345)
uvicorn app.main:app --reload     # http://localhost:8000/docs

# 3. Frontend (new terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxies /api → :8000)
```
Demo logins after `--demo`: `org_admin@demo.test`, `event_manager@demo.test`, `staff@demo.test`, `participant@demo.test` (all `Demo12345`).

### Tests
```bash
cd backend && pytest -q        # needs the eventdb_test database; 81 tests
```
Tests run against **real PostgreSQL** (not SQLite) because correctness depends on row locks and exclusion constraints. They include true concurrency tests (20 simultaneous registrations for 3 seats; 15 simultaneous bookings of one slot; concurrent cancellations promoting exactly one waitlisted user) and a test that bypasses the service layer to prove the database itself rejects overlapping bookings.

| Area | Covered |
|---|---|
| Auth | register, login, invalid credentials, expired access/refresh token, rotation, reuse detection, logout, change-password, inactive users |
| Authorization | role matrix, organization isolation (events, resources, bookings, files, comments, attendance), resource-level access, unauthenticated access |
| Events | CRUD, every status transition (valid + invalid), capacity rules, cancel cascade, filters/search/sort/pagination |
| Registrations | duplicate, capacity, waitlist FIFO, cancel releases seat, auto-promotion, approval workflow, closed/cancelled, concurrency |
| Bookings | lifecycle, overlap (incl. the 10:00–11:00 vs 10:30–11:30 example), approval, cancel, filters, concurrency, DB constraint |
| Sessions | creation, room conflict, speaker conflict, outside event window, room capacity, cancelled event |
| Files | valid upload/download/delete, invalid extension, spoofed content, MIME mismatch, oversize, path traversal, permissions |
| Notifications | creation, read / read-all, mentions, reminders, WebSocket push |

## Project layout
```
backend/app/{api,services,repositories,models,schemas,core,db,scripts}   alembic/   tests/   scripts/
frontend/src/{pages,components,api.js,store.js,utils.js}
docs/ARCHITECTURE.md  docs/DATABASE_DESIGN.md  docs/ER_DIAGRAM.md
postman/EventHub.postman_collection.json
```
* **ER diagram:** `docs/ER_DIAGRAM.md` (Mermaid, generated from the models: `python backend/scripts/gen_er_diagram.py`)
* **Architecture diagram + authorization matrix + concurrency strategy:** `docs/ARCHITECTURE.md`
* **API documentation:** interactive at `/docs` (Swagger) and `/redoc`; 75 operations
* **Postman:** import `postman/EventHub.postman_collection.json`; run *register* then *login* – tokens are saved automatically. Regenerate any time: `python backend/scripts/gen_postman.py`

## API conventions
Success: `{"success": true, "data": …}`. Lists: `data = {items,total,page,page_size,pages}`. Errors:
```json
{"success": false, "error": {"code": "RESOURCE_ALREADY_BOOKED", "message": "The selected resource is already booked for this time period."}}
```
Handled: 400, 401, 403, 404, 409, 413, 415, 422 (with per-field `details`), 500. Domain codes include `EVENT_CAPACITY_EXCEEDED`, `DUPLICATE_REGISTRATION`, `RESOURCE_ALREADY_BOOKED`, `INVALID_EVENT_STATUS`, `SESSION_TIME_CONFLICT`, `SPEAKER_TIME_CONFLICT`, `ORGANIZATION_ACCESS_DENIED`, `REGISTRATION_CLOSED`, `EVENT_CANCELLED`.

Key endpoints beyond the brief's list: `POST /events/{id}/status` (ongoing/completed), `POST /registrations/{id}/approve|reject`, `POST /bookings/{id}/approve|reject`, `POST /resources/{id}/activate|deactivate`, `GET /events/{id}/attendance/export` (CSV), `GET /organizations/{id}/audit-logs`, `GET /dashboard?organization_id=`, `WS /api/ws?token=`.

## Design decisions & interpretations (please read)
* **Roles are per organization**; `users.is_super_admin` is the global role. Any registered user can create an organization and becomes its admin; admins add existing users by email.
* **Event-level rule:** an Event Manager can modify only events they organize; Org Admins can modify any.
* **"Assigned events" (Staff dashboard)** is interpreted as the organization's published/ongoing events – the brief defines no staff-assignment model.
* **Registration flow:** auto-confirm while seats remain, otherwise waitlist. If an event sets `requires_approval`, registrations start `pending` and don't hold a seat until staff approve (approval into a full event waitlists).
* **Registration closes** at `registration_deadline`, or at event start if none is set.
* **Attendance** can be recorded only for `ongoing`/`completed` events and only for confirmed registrants; it keeps `registrations.status` in sync.
* **Cancelling an event** cancels all live registrations and active bookings and notifies registrants, atomically.
* **Participants never see drafts/archived events**; cross-organization access returns 404 to avoid leaking existence.
* **Files:** extension allow-list + magic-byte content sniffing + declared-MIME check + size cap; stored under random names; original name sanitised. Download is authorized per event/registration.
* **Refresh tokens** are stored server-side (by `jti`), rotated on every use; reuse revokes all of the user's tokens. Changing password revokes all sessions.

## Known limitations / honest notes
* **Docker files were written but not executed** in the environment this was built in (no Docker daemon). The non-Docker path, migrations (up/down/up), API, and test suite were all run against real PostgreSQL 16.
* **The React UI was compiled (`npm run build` passes) and every API it calls is covered by backend tests, but it was not click-tested in a browser** and has no frontend unit tests. Expect to find minor UI polish issues.
* **Scheduler is in-process** (asyncio loop, every 60 s) for auto start/complete, reminders and booking completion; with multiple API replicas, move it to Celery beat (reminders use `FOR UPDATE SKIP LOCKED`, so duplicates are already avoided). Celery/Redis are not included.
* **Emails are stubbed** (logged). WebSocket push is per-process; multi-replica fan-out would need Redis pub/sub.
* No rate limiting or Redis caching. Calendar has no drag-and-drop.
* Sessions page uses an event picker; per-session file/speaker attachment uploads are supported by the API (`entity_type`) but the UI only uploads event-level documents.
* Set a strong `SECRET_KEY` and change the super-admin password before deploying anywhere real.
