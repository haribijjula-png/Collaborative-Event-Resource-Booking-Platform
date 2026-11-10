import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api, { errMsg } from '../api'
import { useRole, useStore } from '../store'
import { fmt, fromLocalInput, rules, toLocalInput, useDebounced, useFetch, validate } from '../utils'
import { Badge, Card, Empty, ErrorBox, Field, Modal, Pagination, Spinner } from '../components/ui'

export function EventForm({ event, orgId, onClose, onSaved }) {
  const [v, setV] = useState({
    name: event?.name || '', description: event?.description || '', location: event?.location || '',
    start_time: toLocalInput(event?.start_time), end_time: toLocalInput(event?.end_time), capacity: event?.capacity || 50,
    registration_deadline: toLocalInput(event?.registration_deadline), requires_approval: event?.requires_approval || false,
  })
  const [errors, setErrors] = useState({}), [err, setErr] = useState(null), [busy, setBusy] = useState(false)
  const set = (k) => (e) => setV({ ...v, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const save = async () => {
    const e = validate(v, {
      name: [rules.required, rules.min(2)], start_time: rules.required, end_time: [rules.required, (x, a) => (a.start_time && new Date(x) <= new Date(a.start_time) ? 'Must be after start' : null)],
      capacity: rules.positiveInt, registration_deadline: (x, a) => (x && a.end_time && new Date(x) > new Date(a.end_time) ? 'Must be before the event ends' : null),
    })
    setErrors(e); if (Object.keys(e).length) return
    setBusy(true); setErr(null)
    const body = { ...v, capacity: Number(v.capacity), start_time: fromLocalInput(v.start_time), end_time: fromLocalInput(v.end_time), registration_deadline: fromLocalInput(v.registration_deadline) }
    try {
      const r = event ? await api.patch(`/events/${event.id}`, body) : await api.post('/events', { ...body, organization_id: orgId })
      onSaved(r.data.data)
    } catch (x) { setErr(errMsg(x)) } finally { setBusy(false) }
  }
  return (
    <Modal title={event ? 'Edit event' : 'New event'} onClose={onClose} footer={<button className="btn primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>}>
      <ErrorBox error={err} />
      <Field label="Name" error={errors.name}><input value={v.name} onChange={set('name')} /></Field>
      <Field label="Description"><textarea rows={3} value={v.description} onChange={set('description')} /></Field>
      <Field label="Location"><input value={v.location} onChange={set('location')} /></Field>
      <div className="two">
        <Field label="Starts" error={errors.start_time}><input type="datetime-local" value={v.start_time} onChange={set('start_time')} /></Field>
        <Field label="Ends" error={errors.end_time}><input type="datetime-local" value={v.end_time} onChange={set('end_time')} /></Field>
      </div>
      <div className="two">
        <Field label="Capacity" error={errors.capacity}><input type="number" min="1" value={v.capacity} onChange={set('capacity')} /></Field>
        <Field label="Registration closes" error={errors.registration_deadline} hint="Optional; defaults to start time"><input type="datetime-local" value={v.registration_deadline} onChange={set('registration_deadline')} /></Field>
      </div>
      <label className="check"><input type="checkbox" checked={v.requires_approval} onChange={set('requires_approval')} /> Registrations require approval</label>
    </Modal>
  )
}

export default function Events() {
  const { orgId, can } = useRole(), toast = useStore((s) => s.toast), nav = useNavigate()
  const [f, setF] = useState({ page: 1, search: '', status: '', location: '', start_from: '', start_to: '', sort: '-start_time' })
  const q = useDebounced(f.search), loc = useDebounced(f.location)
  const [open, setOpen] = useState(false)
  const { data, loading, error, reload } = useFetch(() => orgId ? api.get('/events', { params: {
    organization_id: orgId, page: f.page, page_size: 10, search: q || undefined, status: f.status || undefined, location: loc || undefined,
    start_from: f.start_from ? new Date(f.start_from).toISOString() : undefined, start_to: f.start_to ? new Date(f.start_to + 'T23:59:59').toISOString() : undefined, sort: f.sort } }).then((r) => r.data.data) : Promise.resolve(null),
    [orgId, f.page, q, loc, f.status, f.start_from, f.start_to, f.sort])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value, page: 1 })
  if (!orgId) return <Empty title="Select an organization" />
  return (
    <>
      <div className="page-h"><h2>Events</h2>{can('event_manager') && <button className="btn primary" onClick={() => setOpen(true)}>+ New event</button>}</div>
      <div className="filters">
        <input placeholder="Search events…" value={f.search} onChange={set('search')} />
        <select value={f.status} onChange={set('status')}><option value="">All statuses</option>{['draft', 'published', 'ongoing', 'completed', 'cancelled', 'archived'].map((s) => <option key={s}>{s}</option>)}</select>
        <input placeholder="Location" value={f.location} onChange={set('location')} />
        <input type="date" aria-label="From" value={f.start_from} onChange={set('start_from')} />
        <input type="date" aria-label="To" value={f.start_to} onChange={set('start_to')} />
        <select value={f.sort} onChange={set('sort')}><option value="-start_time">Newest first</option><option value="start_time">Soonest first</option><option value="name">Name A–Z</option></select>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No events match" hint={can('event_manager') ? 'Create your first event.' : undefined} /> : (
        <Card><div className="table-wrap"><table>
          <thead><tr><th>Name</th><th>When</th><th>Location</th><th>Capacity</th><th>Organizer</th><th>Status</th></tr></thead>
          <tbody>{data.items.map((e) => (
            <tr key={e.id}><td><Link to={`/events/${e.id}`}>{e.name}</Link></td><td>{fmt(e.start_time)}</td><td>{e.location || '—'}</td><td>{e.capacity}</td><td>{e.organizer.full_name}</td><td><Badge value={e.status} /></td></tr>))}</tbody>
        </table></div><Pagination data={data} onPage={(p) => setF({ ...f, page: p })} /></Card>
      )}
      {open && <EventForm orgId={orgId} onClose={() => setOpen(false)} onSaved={(ev) => { toast('Event created', 'success'); nav(`/events/${ev.id}`) }} />}
    </>
  )
}
