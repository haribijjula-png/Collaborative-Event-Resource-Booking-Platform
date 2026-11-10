import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import api, { errMsg } from '../api'
import { useRole, useStore } from '../store'
import { fmt, useFetch } from '../utils'
import { Badge, Card, Empty, ErrorBox, Field, Pagination, Spinner } from '../components/ui'
import { EventForm } from './Events'
import { SessionsPanel } from './Sessions'

const TABS = ['Overview', 'Registrations', 'Sessions', 'Attendance', 'Files', 'Discussion']

export default function EventDetails() {
  const { id } = useParams(), nav = useNavigate()
  const { user, toast } = useStore(), { can } = useRole()
  const [tab, setTab] = useState('Overview'), [edit, setEdit] = useState(false)
  const { data: ev, loading, error, reload } = useFetch(() => api.get(`/events/${id}`).then((r) => r.data.data), [id])
  if (loading && !ev) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!ev) return null
  const manage = can('org_admin') || (can('event_manager') && ev.organizer_id === user.id)
  const act = async (fn, msg) => { try { await fn(); toast(msg, 'success'); reload() } catch (e) { toast(errMsg(e), 'error') } }
  const post = (p, body) => api.post(`/events/${id}/${p}`, body)
  const mine = ev.my_registration_status
  const closed = ev.status !== 'published'

  return (
    <>
      <div className="page-h">
        <div><Link to="/events" className="muted">← Events</Link><h2>{ev.name} <Badge value={ev.status} /></h2></div>
        <div className="row wrap">
          {ev.status === 'published' && !mine && <button className="btn primary" onClick={() => act(() => post('register'), 'Registration submitted')}>Register</button>}
          {mine && <Badge value={mine} />}
          {manage && ev.status === 'draft' && <button className="btn" onClick={() => act(() => post('publish'), 'Published')}>Publish</button>}
          {manage && ev.status === 'published' && <button className="btn" onClick={() => act(() => post('status', { status: 'ongoing' }), 'Event started')}>Start</button>}
          {manage && ev.status === 'ongoing' && <button className="btn" onClick={() => act(() => post('status', { status: 'completed' }), 'Completed')}>Complete</button>}
          {manage && ['draft', 'published', 'ongoing'].includes(ev.status) && <button className="btn danger" onClick={() => window.confirm('Cancel this event? All registrations will be cancelled.') && act(() => post('cancel'), 'Event cancelled')}>Cancel event</button>}
          {manage && ['completed', 'cancelled', 'draft'].includes(ev.status) && <button className="btn" onClick={() => act(() => post('archive'), 'Archived')}>Archive</button>}
          {manage && !['cancelled', 'completed', 'archived'].includes(ev.status) && <button className="btn" onClick={() => setEdit(true)}>Edit</button>}
          {manage && ['draft', 'cancelled'].includes(ev.status) && <button className="btn danger" onClick={() => window.confirm('Delete permanently?') && act(async () => { await api.delete(`/events/${id}`); nav('/events') }, 'Deleted')}>Delete</button>}
        </div>
      </div>
      <div className="tabs" role="tablist">{TABS.filter((t) => t !== 'Attendance' || can('staff')).map((t) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
      {tab === 'Overview' && (
        <Card><dl className="dl">
          <dt>When</dt><dd>{fmt(ev.start_time)} → {fmt(ev.end_time)}</dd>
          <dt>Location</dt><dd>{ev.location || '—'}</dd>
          <dt>Organizer</dt><dd>{ev.organizer.full_name}</dd>
          <dt>Seats</dt><dd>{ev.confirmed_count} / {ev.capacity} confirmed · {ev.waitlist_count} waitlisted</dd>
          <dt>Registration</dt><dd>{ev.requires_approval ? 'Requires approval' : 'Automatic'} · closes {fmt(ev.registration_deadline || ev.start_time)}</dd>
          <dt>Description</dt><dd>{ev.description || '—'}</dd>
        </dl>{closed && ev.status !== 'draft' && <p className="muted">Registration is closed for {ev.status} events.</p>}</Card>
      )}
      {tab === 'Registrations' && <RegistrationsPanel ev={ev} onChange={reload} />}
      {tab === 'Sessions' && <SessionsPanel ev={ev} manage={manage} />}
      {tab === 'Attendance' && <AttendancePanel ev={ev} />}
      {tab === 'Files' && <FilesPanel ev={ev} />}
      {tab === 'Discussion' && <Discussion ev={ev} />}
      {edit && <EventForm event={ev} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); toast('Event updated', 'success'); reload() }} />}
    </>
  )
}

function RegistrationsPanel({ ev, onChange }) {
  const { can } = useRole(), toast = useStore((s) => s.toast)
  const [page, setPage] = useState(1), [status, setStatus] = useState('')
  const { data, loading, error, reload } = useFetch(() => api.get(`/events/${ev.id}/registrations`, { params: { page, page_size: 10, status: status || undefined } }).then((r) => r.data.data), [ev.id, page, status])
  const act = async (fn, msg) => { try { await fn(); toast(msg, 'success'); reload(); onChange() } catch (e) { toast(errMsg(e), 'error') } }
  return (
    <Card title="Registrations" actions={<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option value="">All</option>{['pending', 'confirmed', 'waitlisted', 'cancelled', 'rejected', 'attended', 'no_show'].map((s) => <option key={s}>{s}</option>)}</select>}>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No registrations" /> : <><div className="table-wrap"><table>
        <thead><tr><th>Participant</th><th>Status</th><th>Registered</th><th /></tr></thead>
        <tbody>{data.items.map((r) => <tr key={r.id}><td>{r.user.full_name}</td><td><Badge value={r.status} /></td><td>{fmt(r.created_at)}</td><td className="row">
          {can('staff') && r.status === 'pending' && <><button className="btn sm primary" onClick={() => act(() => api.post(`/registrations/${r.id}/approve`), 'Approved')}>Approve</button><button className="btn sm danger" onClick={() => act(() => api.post(`/registrations/${r.id}/reject`, {}), 'Rejected')}>Reject</button></>}
          {can('staff') && r.status === 'waitlisted' && <button className="btn sm danger" onClick={() => act(() => api.post(`/registrations/${r.id}/reject`, {}), 'Rejected')}>Reject</button>}
          {['pending', 'confirmed', 'waitlisted'].includes(r.status) && <button className="btn sm" onClick={() => act(() => api.post(`/registrations/${r.id}/cancel`), 'Cancelled')}>Cancel</button>}
        </td></tr>)}</tbody></table></div><Pagination data={data} onPage={setPage} /></>}
    </Card>
  )
}

function AttendancePanel({ ev }) {
  const toast = useStore((s) => s.toast)
  const { data, loading, error, reload } = useFetch(() => api.get(`/events/${ev.id}/attendance`, { params: { page_size: 100 } }).then((r) => r.data.data), [ev.id])
  const set = async (a, status) => { try { await api.patch(`/attendance/${a.id}`, { status }); reload() } catch (e) { toast(errMsg(e), 'error') } }
  const exportCsv = async () => {
    const r = await api.get(`/events/${ev.id}/attendance/export`, { responseType: 'blob' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = `attendance_${ev.id}.csv`; a.click()
  }
  return (
    <Card title="Attendance" actions={<button className="btn sm" onClick={exportCsv}>Export CSV</button>}>
      {!['ongoing', 'completed'].includes(ev.status) && <p className="alert">Attendance can be recorded once the event is ongoing.</p>}
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No confirmed attendees yet" /> : <div className="table-wrap"><table>
        <thead><tr><th>Participant</th><th>Status</th><th>Check-in</th><th /></tr></thead>
        <tbody>{data.items.map((a) => <tr key={a.id}><td>{a.user.full_name}</td><td><Badge value={a.status} /></td><td>{a.checked_in_at ? fmt(a.checked_in_at) : '—'}</td>
          <td className="row"><button className="btn sm primary" onClick={() => set(a, 'attended')}>Present</button><button className="btn sm" onClick={() => set(a, 'no_show')}>No-show</button></td></tr>)}</tbody></table></div>}
    </Card>
  )
}

function FilesPanel({ ev }) {
  const { can } = useRole(), toast = useStore((s) => s.toast), input = useRef()
  const { data, loading, error, reload } = useFetch(() => api.get(`/events/${ev.id}/files`).then((r) => r.data.data), [ev.id])
  const [busy, setBusy] = useState(false)
  const upload = async (e) => {
    const file = e.target.files[0]; if (!file) return
    if (file.size > 10 * 1024 * 1024) { toast('File is larger than 10 MB', 'error'); return }
    const fd = new FormData(); fd.append('file', file); fd.append('event_id', ev.id); fd.append('entity_type', 'event')
    setBusy(true)
    try { await api.post('/files', fd); toast('Uploaded', 'success'); reload() } catch (x) { toast(errMsg(x), 'error') } finally { setBusy(false); input.current.value = '' }
  }
  const download = async (f) => {
    const r = await api.get(`/files/${f.id}/download`, { responseType: 'blob' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = f.file_name; a.click()
  }
  return (
    <Card title="Documents" actions={can('staff') && <><input ref={input} type="file" hidden onChange={upload} accept=".pdf,.png,.jpg,.jpeg,.gif,.txt,.csv,.md,.docx,.xlsx,.pptx" /><button className="btn sm primary" disabled={busy} onClick={() => input.current.click()}>{busy ? 'Uploading…' : 'Upload'}</button></>}>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.length ? <Empty title="No documents" hint="PDF, images, text, Word/Excel/PowerPoint up to 10 MB." /> : <ul className="list">{data.map((f) => (
        <li key={f.id}><span><b>{f.file_name}</b> <span className="muted">{(f.file_size / 1024).toFixed(1)} KB · {f.entity_type}</span></span>
          <span className="row"><button className="btn sm" onClick={() => download(f)}>Download</button>
            {can('event_manager') && <button className="btn sm danger" onClick={async () => { await api.delete(`/files/${f.id}`); reload() }}>Delete</button>}</span></li>))}</ul>}
    </Card>
  )
}

function Discussion({ ev }) {
  const { user, toast } = useStore()
  const [page, setPage] = useState(1), [body, setBody] = useState('')
  const { data, loading, error, reload } = useFetch(() => api.get(`/events/${ev.id}/comments`, { params: { page, page_size: 10 } }).then((r) => r.data.data), [ev.id, page])
  const send = async () => {
    if (!body.trim()) return
    try { await api.post(`/events/${ev.id}/comments`, { body }); setBody(''); setPage(1); reload() } catch (e) { toast(errMsg(e), 'error') }
  }
  return (
    <Card title="Discussion">
      <div className="row"><textarea rows={2} placeholder="Write a comment… use @username to mention someone" value={body} onChange={(e) => setBody(e.target.value)} style={{ flex: 1 }} /><button className="btn primary" onClick={send}>Post</button></div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No comments yet" /> : <>{data.items.map((c) => (
        <div className="comment" key={c.id}><div className="row between"><b>{c.user.full_name} <span className="muted">@{c.user.username} · {fmt(c.created_at)}</span></b>
          {c.user.id === user.id && <span className="row"><button className="btn sm" onClick={async () => { const nb = window.prompt('Edit comment', c.body); if (nb?.trim()) { await api.patch(`/comments/${c.id}`, { body: nb }); reload() } }}>Edit</button>
            <button className="btn sm danger" onClick={async () => { await api.delete(`/comments/${c.id}`); reload() }}>Delete</button></span>}</div>
          <p>{c.body.split(/(@[\w.-]+)/g).map((p, i) => p.startsWith('@') ? <strong key={i} className="mention">{p}</strong> : p)}</p></div>))}<Pagination data={data} onPage={setPage} /></>}
    </Card>
  )
}
