import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import api, { errMsg } from '../api'
import { useRole, useStore } from '../store'
import { fmt, useDebounced, useFetch } from '../utils'
import { Badge, Card, Empty, ErrorBox, Pagination, Spinner } from '../components/ui'

export default function Registrations() {
  const { orgId, can } = useRole(), toast = useStore((s) => s.toast), [sp] = useSearchParams()
  const [f, setF] = useState({ page: 1, status: sp.get('status') || '', event_id: '', search: '', date_from: '', date_to: '' })
  const q = useDebounced(f.search)
  const events = useFetch(() => orgId ? api.get('/events', { params: { organization_id: orgId, page_size: 100 } }).then((r) => r.data.data.items) : Promise.resolve([]), [orgId])
  const { data, loading, error, reload } = useFetch(() => orgId ? api.get('/registrations', { params: { organization_id: orgId, page: f.page, page_size: 10, status: f.status || undefined, event_id: f.event_id || undefined, search: q || undefined,
    date_from: f.date_from ? new Date(f.date_from).toISOString() : undefined, date_to: f.date_to ? new Date(f.date_to + 'T23:59:59').toISOString() : undefined } }).then((r) => r.data.data) : Promise.resolve(null), [orgId, f.page, f.status, f.event_id, q, f.date_from, f.date_to])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value, page: 1 })
  const act = async (id, a, msg) => { try { await api.post(`/registrations/${id}/${a}`, a === 'reject' ? {} : undefined); toast(msg, 'success'); reload() } catch (e) { toast(errMsg(e), 'error') } }
  if (!orgId) return <Empty title="Select an organization" />
  return (
    <>
      <div className="page-h"><h2>Registrations</h2></div>
      <div className="filters">
        <select value={f.event_id} onChange={set('event_id')}><option value="">All events</option>{events.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
        <select value={f.status} onChange={set('status')}><option value="">Any status</option>{['pending', 'confirmed', 'waitlisted', 'cancelled', 'rejected', 'attended', 'no_show'].map((s) => <option key={s}>{s}</option>)}</select>
        {can('staff') && <input placeholder="Search participant…" value={f.search} onChange={set('search')} />}
        <input type="date" aria-label="Registered from" value={f.date_from} onChange={set('date_from')} /><input type="date" aria-label="Registered to" value={f.date_to} onChange={set('date_to')} /></div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No registrations" hint="Register for a published event to see it here." /> : <Card><div className="table-wrap"><table>
        <thead><tr><th>Participant</th><th>Event</th><th>Status</th><th>Registered</th><th /></tr></thead>
        <tbody>{data.items.map((r) => <tr key={r.id}><td>{r.user.full_name}</td><td><Link to={`/events/${r.event_id}`}>#{r.event_id} {events.data?.find((e) => e.id === r.event_id)?.name}</Link></td><td><Badge value={r.status} /></td><td>{fmt(r.created_at)}</td>
          <td className="row">{can('staff') && r.status === 'pending' && <><button className="btn sm primary" onClick={() => act(r.id, 'approve', 'Approved')}>Approve</button><button className="btn sm danger" onClick={() => act(r.id, 'reject', 'Rejected')}>Reject</button></>}
            {['pending', 'confirmed', 'waitlisted'].includes(r.status) && <button className="btn sm" onClick={() => act(r.id, 'cancel', 'Cancelled')}>Cancel</button>}</td></tr>)}</tbody></table></div>
        <Pagination data={data} onPage={(p) => setF({ ...f, page: p })} /></Card>}
    </>
  )
}
