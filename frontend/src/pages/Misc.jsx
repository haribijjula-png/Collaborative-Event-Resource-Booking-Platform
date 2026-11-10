import { useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errMsg } from '../api'
import { useRole, useStore } from '../store'
import { fmt, rules, useFetch, validate } from '../utils'
import { Badge, Card, Empty, ErrorBox, Field, Pagination, Spinner } from '../components/ui'

export function Notifications() {
  const { setUnread, toast } = useStore()
  const [page, setPage] = useState(1), [unreadOnly, setUnreadOnly] = useState(false)
  const { data, loading, error, reload } = useFetch(() => api.get('/notifications', { params: { page, page_size: 15, is_read: unreadOnly ? false : undefined } }).then((r) => { setUnread(r.data.data.unread_count); return r.data.data }), [page, unreadOnly])
  const read = async (n) => { if (n.is_read) return; try { await api.patch(`/notifications/${n.id}/read`); reload() } catch (e) { toast(errMsg(e), 'error') } }
  return (
    <>
      <div className="page-h"><h2>Notifications</h2><div className="row">
        <label className="check"><input type="checkbox" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); setPage(1) }} /> Unread only</label>
        <button className="btn" onClick={async () => { await api.patch('/notifications/read-all'); reload() }}>Mark all read</button></div></div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="You're all caught up" /> : <Card><ul className="list">{data.items.map((n) => (
        <li key={n.id} className={n.is_read ? '' : 'unread'} onClick={() => read(n)}>
          <span><b>{n.title}</b><br />{n.message} {n.data?.event_id && <Link to={`/events/${n.data.event_id}`}>View event</Link>}</span><span className="muted nowrap">{fmt(n.created_at)}</span></li>))}</ul>
        <Pagination data={data} onPage={setPage} /></Card>}
    </>
  )
}

export function Profile() {
  const { user, setUser, toast } = useStore(), { role } = useRole()
  const { data } = useFetch(() => api.get('/auth/me').then((r) => { setUser(r.data.data); return r.data.data }), [])
  const u = data || user
  return (
    <><div className="page-h"><h2>Profile</h2></div>
      <Card><dl className="dl"><dt>Name</dt><dd>{u.full_name}</dd><dt>Username</dt><dd>@{u.username}</dd><dt>Email</dt><dd>{u.email}</dd>
        <dt>Role in active org</dt><dd>{role ? <Badge value={role} /> : '—'}</dd><dt>Status</dt><dd><Badge value={u.is_active ? 'active' : 'inactive'} /> {u.is_super_admin && <Badge value="super_admin" />}</dd></dl></Card></>
  )
}

export function Settings() {
  const { theme, setTheme, toast, logout } = useStore()
  const [v, setV] = useState({ old_password: '', new_password: '', confirm: '' }), [errors, setErrors] = useState({}), [err, setErr] = useState(null)
  const save = async (e) => {
    e.preventDefault()
    const er = validate(v, { old_password: rules.required, new_password: rules.password, confirm: (x, a) => (x === a.new_password ? null : 'Passwords do not match') }); setErrors(er); setErr(null)
    if (Object.keys(er).length) return
    try { await api.post('/auth/change-password', { old_password: v.old_password, new_password: v.new_password }); toast('Password changed — please sign in again', 'success'); logout() }
    catch (x) { setErr(errMsg(x)) }
  }
  const set = (k) => (e) => setV({ ...v, [k]: e.target.value })
  return (
    <><div className="page-h"><h2>Settings</h2></div>
      <div className="grid2">
        <Card title="Appearance"><label className="check"><input type="checkbox" checked={theme === 'dark'} onChange={(e) => setTheme(e.target.checked ? 'dark' : 'light')} /> Dark mode</label></Card>
        <Card title="Change password"><form onSubmit={save} noValidate><ErrorBox error={err} />
          <Field label="Current password" error={errors.old_password}><input type="password" autoComplete="current-password" value={v.old_password} onChange={set('old_password')} /></Field>
          <Field label="New password" error={errors.new_password}><input type="password" autoComplete="new-password" value={v.new_password} onChange={set('new_password')} /></Field>
          <Field label="Confirm new password" error={errors.confirm}><input type="password" autoComplete="new-password" value={v.confirm} onChange={set('confirm')} /></Field>
          <button className="btn primary">Update password</button></form></Card></div></>
  )
}

/** Attendance hub: pick an ongoing/completed event and jump to its attendance tab. */
export function AttendanceHub() {
  const { orgId } = useRole()
  const { data, loading, error, reload } = useFetch(() => orgId ? api.get('/events', { params: { organization_id: orgId, page_size: 50, sort: '-start_time' } }).then((r) => r.data.data.items.filter((e) => ['ongoing', 'completed'].includes(e.status))) : Promise.resolve([]), [orgId])
  return (
    <><div className="page-h"><h2>Attendance</h2></div><ErrorBox error={error} onRetry={reload} />
      {loading ? <Spinner /> : !data?.length ? <Empty title="No ongoing or completed events" hint="Start an event to begin recording attendance." /> : <Card><ul className="list">{data.map((e) => <li key={e.id}><span><b>{e.name}</b> <Badge value={e.status} /><br /><span className="muted">{fmt(e.start_time)}</span></span><Link className="btn sm primary" to={`/events/${e.id}`}>Open attendance</Link></li>)}</ul></Card>}</>
  )
}
