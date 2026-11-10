# Database design

See [ER_DIAGRAM.md](ER_DIAGRAM.md) (generated from the models).

## Tables (18 incl. `alembic_version`)
`users`, `organizations`, `organization_members` (role lives here), `events`, `event_sessions`, `speakers`, `speaker_sessions`, `registrations`, `waitlist_entries`, `resources`, `resource_bookings`, `attendance`, `comments`, `attachments`, `notifications`, `audit_logs`, `refresh_tokens`.

**Roles.** The brief lists a `roles` table. Roles are a closed set that drive code paths, so they are modelled as a `CHECK`-constrained column (`organization_members.role`) plus `users.is_super_admin`, rather than a lookup table that code would have to hard-code anyway. Roles are per-organization: one user can be admin of one org and participant in another.

## Integrity rules (all in the migration)
* **Foreign keys** with explicit cascade rules: deleting an organization/event cascades to children; user-owned history (`events.organizer_id`, bookings, uploads) is `RESTRICT`; audit `user_id` is `SET NULL`.
* **Unique:** `users.email/username`, `(organization_id,user_id)`, `(organization_id,name)` for resources, `(speaker_id,session_id)`, `(event_id,user_id)` attendance, `refresh_tokens.jti`, one live registration per user/event (partial index).
* **Check:** `end_time > start_time` (events, sessions, bookings), positive capacities, status/role/type values, comment targets exactly one of event/session.
* **Exclusion (GiST, needs `btree_gist`):** no overlapping active bookings per resource; no overlapping sessions per room.
* **Indexes:** FK columns, `(organization_id,status,start_time)` for event lists, `(event_id,status)` for seat counts, `(user_id,is_read)` for notification badges.
* **Timestamps:** `created_at` / `updated_at` (server default + `onupdate`) on mutable tables; all datetimes are `timestamptz` (UTC).

## Status machines
Events: `draft→published|cancelled|archived`, `published→ongoing|cancelled`, `ongoing→completed|cancelled`, `completed|cancelled→archived`; anything else is `409 INVALID_EVENT_STATUS`.
Registrations: `pending→confirmed|waitlisted|rejected|cancelled`, `waitlisted→confirmed|rejected|cancelled`, `confirmed→cancelled|attended|no_show`.
