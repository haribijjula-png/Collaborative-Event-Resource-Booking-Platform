import { useState } from 'react'
import api, { errMsg, errCode } from '../api'
import { useRole, useStore } from '../store'
import { fmt, fromLocalInput, rules, toLocalInput, useFetch, validate } from '../utils'
import { Card, Empty, ErrorBox, Field, Modal, Spinner } from '../components/ui'

function SessionForm({ ev, session, onClose, onSaved }) {
  const { orgId } = useRole()
  const rooms = useFetch(() => api.get('/resources', { params: { organization_id: orgId, page_size: 100, status: 'active' } }).then((r) => r.data.data.items), [orgId])
  const speakers = useFetch(() => api.get('/speakers', { params: { organization_id: orgId, page_size: 100 } }).then((r) => r.data.data.items), [orgId])
  const [v, setV] = useState({ title: session?.title || '', description: session?.description || '', room_id: session?.room_id || '', capacity: session?.capacity || '',
    start_time: toLocalInput(session?.start_time || ev.start_time), end_time: toLocalInput(session?.end_time || ev.end_time), speaker_ids: session?.speakers?.map((s) => s.id) || [] })
  const [errors, setErrors] = useState({}), [err, setErr] = useState(null)
  const set = (k) => (e) => setV({ ...v, [k]: e.target.value })
  const save = async () => {
    const e = validate(v, {
      title: [rules.required, rules.min(2)], start_time: rules.required,
      end_time: [rules.required, (x, a) => (new Date(x) <= new Date(a.start_time) ? 'Must be after start' : null)],
      capacity: (x) => (x === '' || rules.positiveInt(x) === null ? null : 'Must be a positive number'),
    })
    if (!e.start_time && new Date(v.start_time) < new Date(toLocalInput(ev.start_time))) e.start_time = 'Before the event starts'
    if (!e.end_time && new Date(v.end_time) > new Date(toLocalInput(ev.end_time))) e.end_time = 'After the event ends'
    setErrors(e); if (Object.keys(e).length) return
    const body = { ...v, room_id: v.room_id ? Number(v.room_id) : null, capacity: v.capacity ? Number(v.capacity) : null, start_time: fromLocalInput(v.start_time), end_time: fromLocalInput(v.end_time) }
    try { const r = session ? await api.patch(`/sessions/${session.id}`, body) : await api.post(`/events/${ev.id}/sessions`, body); onSaved(r.data.data) }
    catch (x) { setErr(errMsg(x)) }
  }
  return (
    <Modal title={session ? 'Edit session' : 'New session'} onClose={onClose} footer={<button className="btn primary" onClick={save}>Save</button>}>
      <ErrorBox error={err} />
      <Field label="Title" error={errors.title}><input value={v.title} onChange={set('title')} /></Field>
      <Field label="Description"><textarea rows={2} value={v.description} onChange={set('description')} /></Field>
      <div className="two">
        <Field label="Starts" error={errors.start_time}><input type="datetime-local" value={v.start_time} onChange={set('start_time')} /></Field>
        <Field label="Ends" error={errors.end_time}><input type="datetime-local" value={v.end_time} onChange={set('end_time')} /></Field>
      </div>
      <div className="two">
        <Field label="Room"><select value={v.room_id} onChange={set('room_id')}><option value="">— none —</option>{rooms.data?.map((r) => <option key={r.id} value={r.id}>{r.name}{r.capacity ? ` (${r.capacity})` : ''}</option>)}</select></Field>
        <Field label="Capacity" error={errors.capacity}><input type="number" min="1" value={v.capacity} onChange={set('capacity')} /></Field>
      </div>
      <Field label="Speakers (ctrl/cmd-click for several)"><select multiple size={4} value={v.speaker_ids.map(String)} onChange={(e) => setV({ ...v, speaker_ids: [...e.target.selectedOptions].map((o) => Number(o.value)) })}>{speakers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
    </Modal>
  )
}

function SpeakerManager({ onClose }) {
  const { orgId } = useRole(), toast = useStore((s) => s.toast)
  const { data, loading, reload } = useFetch(() => api.get('/speakers', { params: { organization_id: orgId, page_size: 100 } }).then((r) => r.data.data.items), [orgId])
  const [v, setV] = useState({ name: '', email: '' }), [err, setErr] = useState(null)
  const add = async () => {
    const e = validate(v, { name: [rules.required, rules.min(2)] }); if (e.name) return setErr(e.name)
    if (v.email && rules.email(v.email)) return setErr('Invalid email')
    try { await api.post('/speakers', { organization_id: orgId, name: v.name, email: v.email || null }); setV({ name: '', email: '' }); setErr(null); reload() } catch (x) { setErr(errMsg(x)) }
  }
  return (
    <Modal title="Speakers" onClose={onClose}>
      <ErrorBox error={err} />
      <div className="row"><input placeholder="Name" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /><input placeholder="Email (optional)" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} /><button className="btn primary" onClick={add}>Add</button></div>
      {loading ? <Spinner /> : !data?.length ? <Empty title="No speakers yet" /> : <ul className="list">{data.map((s) => <li key={s.id}><span>{s.name} <span className="muted">{s.email}</span></span>
        <button className="btn sm danger" onClick={async () => { try { await api.delete(`/speakers/${s.id}`); reload() } catch (x) { toast(errMsg(x), 'error') } }}>Delete</button></li>)}</ul>}
    </Modal>
  )
}

export function SessionsPanel({ ev, manage }) {
  const toast = useStore((s) => s.toast)
  const [form, setForm] = useState(null), [spk, setSpk] = useState(false)
  const { data, loading, error, reload } = useFetch(() => api.get(`/events/${ev.id}/sessions`).then((r) => r.data.data), [ev.id])
  const canEdit = manage && !['cancelled', 'completed', 'archived'].includes(ev.status)
  return (
    <Card title="Schedule" actions={canEdit && <><button className="btn sm" onClick={() => setSpk(true)}>Speakers</button><button className="btn sm primary" onClick={() => setForm({})}>+ Session</button></>}>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.length ? <Empty title="No sessions scheduled" /> : <div className="table-wrap"><table>
        <thead><tr><th>Title</th><th>Time</th><th>Room</th><th>Speakers</th><th /></tr></thead>
        <tbody>{data.map((s) => <tr key={s.id}><td><b>{s.title}</b><br /><span className="muted">{s.description}</span></td><td>{fmt(s.start_time)}<br />→ {fmt(s.end_time)}</td><td>{s.room?.name || '—'}{s.capacity ? ` · cap ${s.capacity}` : ''}</td><td>{s.speakers.map((p) => p.name).join(', ') || '—'}</td>
          <td className="row">{canEdit && <><button className="btn sm" onClick={() => setForm(s)}>Edit</button><button className="btn sm danger" onClick={async () => { if (!window.confirm('Delete session?')) return; try { await api.delete(`/sessions/${s.id}`); reload() } catch (x) { toast(errMsg(x), 'error') } }}>Delete</button></>}</td></tr>)}</tbody></table></div>}
      {form && <SessionForm ev={ev} session={form.id ? form : null} onClose={() => setForm(null)} onSaved={() => { setForm(null); toast('Session saved', 'success'); reload() }} />}
      {spk && <SpeakerManager onClose={() => setSpk(false)} />}
    </Card>
  )
}

/** Stand-alone "Sessions" page: pick an event, then manage its schedule. */
export default function Sessions() {
  const { orgId, can } = useRole(), user = useStore((s) => s.user)
  const [evId, setEvId] = useState('')
  const events = useFetch(() => orgId ? api.get('/events', { params: { organization_id: orgId, page_size: 100, sort: 'start_time' } }).then((r) => r.data.data.items) : Promise.resolve([]), [orgId])
  const ev = events.data?.find((e) => String(e.id) === String(evId))
  if (!orgId) return <Empty title="Select an organization" />
  return (
    <>
      <div className="page-h"><h2>Sessions</h2></div>
      <div className="filters"><select value={evId} onChange={(e) => setEvId(e.target.value)}><option value="">Choose an event…</option>{events.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></div>
      <ErrorBox error={events.error} onRetry={events.reload} />
      {ev ? <SessionsPanel ev={ev} manage={can('org_admin') || (can('event_manager') && ev.organizer_id === user.id)} /> : <Empty title="Pick an event" hint="Its sessions, rooms and speakers will appear here." />}
    </>
  )
}
