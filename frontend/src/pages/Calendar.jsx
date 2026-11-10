import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useRole } from '../store'
import { useFetch } from '../utils'
import Calendar, { rangeFor } from '../components/Calendar'
import { Empty, ErrorBox, Modal, Badge } from '../components/ui'
import { fmt } from '../utils'

export default function CalendarPage() {
  const { orgId, can } = useRole(), nav = useNavigate()
  const [view, setView] = useState('month'), [cursor, setCursor] = useState(new Date()), [sel, setSel] = useState(null)
  const [from, to] = rangeFor(view, cursor)
  const { data, error, reload } = useFetch(async () => {
    if (!orgId) return []
    const p = { organization_id: orgId, page_size: 100 }
    const range = { start_from: from.toISOString(), start_to: to.toISOString() }
    const evs = (await api.get('/events', { params: { ...p, ...range } })).data.data.items
    const items = evs.filter((e) => e.status !== 'archived').map((e) => ({ id: e.id, kind: 'event', title: e.name, start: e.start_time, end: e.end_time, status: e.status, onClick: () => setSel({ type: 'event', e }) }))
    const sess = await Promise.all(evs.filter((e) => !['draft', 'cancelled'].includes(e.status) || can('staff')).slice(0, 30).map((e) => api.get(`/events/${e.id}/sessions`).then((r) => r.data.data.map((s) => ({ id: s.id, kind: 'session', title: `${s.title} · ${e.name}`, start: s.start_time, end: s.end_time, onClick: () => nav(`/events/${e.id}`) }))).catch(() => [])))
    items.push(...sess.flat())
    if (can('staff')) {
      const b = (await api.get('/bookings', { params: { ...p, date_from: from.toISOString(), date_to: to.toISOString() } })).data.data.items
      items.push(...b.filter((x) => ['requested', 'approved'].includes(x.status)).map((x) => ({ id: x.id, kind: 'booking', title: `${x.resource.name} (${x.status})`, start: x.start_time, end: x.end_time, onClick: () => nav('/bookings') })))
    }
    return items
  }, [orgId, view, from.getTime()]) // eslint-disable-line
  useEffect(() => { const h = () => reload(); window.addEventListener('eh:realtime', h); return () => window.removeEventListener('eh:realtime', h) }, [reload])
  if (!orgId) return <Empty title="Select an organization" />
  return (
    <>
      <div className="page-h"><h2>Calendar</h2></div>
      <ErrorBox error={error} onRetry={reload} />
      <Calendar items={data || []} view={view} setView={setView} cursor={cursor} setCursor={setCursor} />
      {sel && <Modal title={sel.e.name} onClose={() => setSel(null)} footer={<button className="btn primary" onClick={() => nav(`/events/${sel.e.id}`)}>Open event</button>}>
        <p><Badge value={sel.e.status} /></p><p>{fmt(sel.e.start_time)} → {fmt(sel.e.end_time)}</p><p>{sel.e.location || 'No location'} · capacity {sel.e.capacity}</p><p>{sel.e.description}</p></Modal>}
    </>
  )
}
